import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.parse import urlsplit

import requests
from fastapi.testclient import TestClient

import PromptExecutor as executor
from confluence_manager import delete_confluence_ai_response
from main import app
from prompt_db import get_prompt_with_data, update_prompt


def seed_prompts():
    sql = Path('deploy/db_setup.sql').read_text()
    return dict(re.findall(r"\('(confluence_[a-z_]+)',\n'((?:[^']|'')*)',\n'", sql))


class PromptContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_confluence_templates_and_inputs(self):
        prompts = seed_prompts()
        self.assertEqual(set(prompts), set(executor.CONFLUENCE_PROMPTS.values()))
        for key, template in prompts.items():
            with self.subTest(key=key), patch('prompt_db.get_prompt', AsyncMock(return_value=template)):
                kwargs = {'confluence_content': '<p>Original {instruction} {info}</p>'}
                if key == 'confluence_page_update':
                    kwargs['instruction'] = 'Insert literal {confluence_content} and \\1'
                result = await get_prompt_with_data(key, **kwargs)
                self.assertIn(kwargs['confluence_content'], result)
                if 'instruction' in kwargs:
                    self.assertIn(kwargs['instruction'], result)
                migration = Path('deploy/migrations/20260929_confluence_prompts.sql').read_text()
                self.assertIn(template, migration)

    async def test_rejects_template_missing_instruction(self):
        with patch('prompt_db.get_prompt', AsyncMock(return_value='{confluence_content}')):
            with self.assertRaisesRegex(ValueError, 'instruction'):
                await get_prompt_with_data('confluence_page_update', confluence_content='x', instruction='y')
        with self.assertRaisesRegex(ValueError, 'instruction'):
            await update_prompt('confluence_page_update', '{confluence_content}')

    async def test_rejects_missing_input(self):
        with patch('prompt_db.get_prompt', AsyncMock(return_value='{confluence_content} {instruction}')):
            with self.assertRaisesRegex(ValueError, 'Missing prompt inputs'):
                await get_prompt_with_data('confluence_page_update', confluence_content='x')


class ConfluenceOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload = {
            'hostname': urlsplit(executor.CONFLUENCE_URL).hostname,
            'pathname': '/confluence/spaces/SPACE/pages/123/Title',
            'instruction': 'Change the paragraph',
        }
        self.fetch = self.patch('get_confluence_data', AsyncMock(return_value=('<p>Original</p>', 4, '123', 'Title')))
        self.prompt = self.patch('get_prompt_with_data', AsyncMock(return_value='Rendered prompt'))
        self.model = self.patch('run_codex', AsyncMock(return_value='<p>Updated</p>'))
        self.read = self.patch('read_confluence_ai_response', Mock(return_value={}))
        self.write = self.patch('write_confluence_ai_response', Mock())
        self.delete = self.patch('delete_confluence_ai_response', Mock(return_value=True))
        self.put = self.patch('requests.put', Mock(return_value=Mock()))

    def patch(self, target, mock):
        patcher = patch('PromptExecutor.' + target, mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    async def run_operation(self, operation):
        return await executor.confluence_operation({**self.payload, 'operation': operation})

    async def test_every_ai_operation_maps_to_expected_prompt_and_action(self):
        for operation, key in executor.CONFLUENCE_PROMPTS.items():
            with self.subTest(operation=operation):
                self.put.reset_mock()
                self.write.reset_mock()
                self.delete.reset_mock()
                await self.run_operation(operation)
                expected = {'confluence_content': '<p>Original</p>'}
                if operation == 'page_update':
                    expected['instruction'] = self.payload['instruction']
                self.prompt.assert_awaited_with(key, **expected)
                if operation == 'explain':
                    self.put.assert_not_called()
                    self.write.assert_called_once()
                else:
                    body = self.put.call_args.kwargs['json']
                    self.assertEqual(body['body']['storage'], {'value': '<p>Updated</p>', 'representation': 'storage'})
                    self.assertEqual(body['version']['number'], 5)
                    self.assertEqual(body['title'], 'Title')
                    self.assertEqual(body['id'], '123')
                    self.delete.assert_called_once_with('123')

    async def test_delete_never_fetches_or_runs_prompt(self):
        await self.run_operation('delete')
        self.delete.assert_called_once_with('123')
        self.fetch.assert_not_awaited()
        self.prompt.assert_not_awaited()
        self.model.assert_not_awaited()
        self.put.assert_not_called()

    async def test_legacy_cache_cannot_skip_mutations(self):
        self.read.return_value = {'rewrite': '<p>Old</p>', 'page_update': '<p>Old</p>'}
        for operation in ('rewrite', 'page_update'):
            await self.run_operation(operation)
        self.assertEqual(self.put.call_count, 2)
        self.read.assert_not_called()

    async def test_explain_cache_tracks_page_and_prompt_changes(self):
        await self.run_operation('explain')
        self.read.return_value = self.write.call_args.args[1]
        self.model.reset_mock()
        await self.run_operation('explain')
        self.model.assert_not_awaited()
        self.fetch.return_value = ('<p>External edit</p>', 5, '123', 'Title')
        await self.run_operation('explain')
        self.model.assert_awaited_once()
        self.read.return_value = self.write.call_args.args[1]
        self.prompt.return_value = 'Edited prompt'
        await self.run_operation('explain')
        self.assertEqual(self.model.await_count, 2)

    async def test_invalid_instruction_fails_before_read_or_generation(self):
        for instruction in ('', '   ', None):
            self.payload['instruction'] = instruction
            with self.assertRaises(ValueError):
                await self.run_operation('page_update')
        self.fetch.assert_not_awaited()
        self.model.assert_not_awaited()

    async def test_wrong_host_or_operation_rejected(self):
        with self.assertRaises(ValueError):
            await self.run_operation('review')
        self.payload['hostname'] = 'wrong.example.com'
        with self.assertRaises(ValueError):
            await self.run_operation('rewrite')
        self.fetch.assert_not_awaited()

    async def test_bad_model_output_never_published(self):
        for content in ('# Markdown', '```xml\n<p>x</p>\n```', '<p>broken', '', '<p>x</p>explanation', '<html><body>x</body></html>'):
            with self.subTest(content=content):
                self.model.return_value = content
                with self.assertRaises(executor.PromptExecutionError):
                    await self.run_operation('rewrite')
        self.put.assert_not_called()

    async def test_unchanged_output_does_not_create_version(self):
        self.model.return_value = '<p>Original</p>'
        await self.run_operation('page_update')
        self.put.assert_not_called()

    async def test_missing_prompt_never_runs_model_or_put(self):
        self.prompt.return_value = None
        with self.assertRaisesRegex(executor.PromptExecutionError, 'confluence_rewrite'):
            await self.run_operation('rewrite')
        self.model.assert_not_awaited()
        self.put.assert_not_called()

    async def test_put_failures_propagate_without_invalidating_cache(self):
        for error in (requests.Timeout('timeout'), requests.HTTPError('409 conflict')):
            self.put.return_value.raise_for_status.side_effect = error
            with self.assertRaisesRegex(executor.PromptExecutionError, 'Failed to update'):
                await self.run_operation('page_update')
        self.delete.assert_not_called()


class StorageAndURLTests(unittest.TestCase):
    def test_supported_page_urls(self):
        for path, search in [('/confluence/spaces/A/pages/123/title', ''), ('/wiki/spaces/A/pages/123', ''),
                             ('/confluence/pages/viewpage.action', '?pageId=123'),
                             ('/pages/viewpage.action?pageId=123', '')]:
            self.assertEqual(executor.get_confluence_id(path, search), '123')
        for path in ('/', '/spaces/A/pages/not-an-id/title', None):
            with self.assertRaises(ValueError):
                executor.get_confluence_id(path)

    def test_valid_macros_entities_and_cdata_preserved(self):
        body = '<ac:structured-macro ac:name="toc"/><p>A&nbsp;B &amp; C</p><ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[# x < y {instruction}]]></ac:plain-text-body></ac:structured-macro><ac:image><ri:attachment ri:filename="test.png"/></ac:image>'
        self.assertEqual(executor.validate_confluence_storage(body), body)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_returns_current_storage_version_and_title(self):
        response = Mock()
        response.json.return_value = {
            'body': {'storage': {'value': '<p>Current</p>'}},
            'version': {'number': 7}, 'title': 'Current title',
        }
        with patch('PromptExecutor.requests.get', return_value=response) as get:
            result = await executor.get_confluence_data('example.com', '/pages/viewpage.action', '?pageId=123')
        self.assertEqual(result, ('<p>Current</p>', 7, '123', 'Current title'))
        self.assertEqual(get.call_args.kwargs['params'], {'expand': 'body.storage,version'})
        self.assertEqual(get.call_args.kwargs['timeout'], 30)

    async def test_fetch_errors_propagate(self):
        with patch('PromptExecutor.requests.get', side_effect=requests.Timeout('timeout')):
            with self.assertRaisesRegex(executor.PromptExecutionError, 'Failed to fetch'):
                await executor.get_confluence_data('example.com', '/spaces/A/pages/123/title')


class CacheDeletionTests(unittest.TestCase):
    def test_clearing_absent_entry_is_successful(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.rowcount = 0
        with patch('confluence_manager.get_connection', return_value=connection):
            self.assertTrue(delete_confluence_ai_response('123'))
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_database_failure_is_not_reported_as_success(self):
        with patch('confluence_manager.get_connection', return_value=None):
            self.assertFalse(delete_confluence_ai_response('123'))


class EndpointTests(unittest.TestCase):
    def test_invalid_requests_return_422(self):
        client = TestClient(app)
        for payload in ({}, {'operation': 'review', 'hostname': 'x', 'pathname': '/'},
                        {'operation': 'page_update', 'hostname': urlsplit(executor.CONFLUENCE_URL).hostname,
                         'pathname': '/spaces/A/pages/123/title', 'instruction': ' '}):
            self.assertEqual(client.post('/confluence', json=payload).status_code, 422)

    def test_upstream_failures_return_502_so_sender_will_not_reload(self):
        with patch('main.confluence_operation', AsyncMock(side_effect=executor.PromptExecutionError('Update failed'))):
            response = TestClient(app).post('/confluence', json={
                'operation': 'rewrite', 'hostname': 'example.com', 'pathname': '/spaces/A/pages/123/title'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['detail'], 'Update failed')


if __name__ == '__main__':
    unittest.main()
