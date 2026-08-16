import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PromptExecutor import (
    PromptExecutionError,
    _read_email_export,
    email_summary_operation,
)
from email_manager import extract_todos


class EmailExportTests(unittest.TestCase):
    def test_extracts_markdown_todo_checkboxes(self):
        self.assertEqual(
            extract_todos("### Todo List\n- [ ] Reply to Release email\n- [x] Review deployment notes"),
            [
                {"id": "todo-1", "text": "Reply to Release email", "completed": False},
                {"id": "todo-2", "text": "Review deployment notes", "completed": True},
            ],
        )
    def test_reads_json_array_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emails.json"
            path.write_text(json.dumps([{"subject": "Deployment complete"}]), encoding="utf-8")
            self.assertEqual(_read_email_export(path), [{"subject": "Deployment complete"}])

    def test_reads_json_lines_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emails.jsonl"
            path.write_text('{"subject":"One"}\n{"subject":"Two"}\n', encoding="utf-8")
            self.assertEqual(
                _read_email_export(path),
                [{"subject": "One"}, {"subject": "Two"}],
            )


class EmailSummaryOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_complete_json_feed_to_prompt_executor_and_returns_summary(self):
        emails = [{"date_time": "2026-08-15", "subject": "Release", "content": "Ship it"}]
        data_path = Path("/tmp/export.json")
        prompt_builder = AsyncMock(return_value="prompt containing the email JSON")

        with (
            patch("PromptExecutor.read_email_summary", return_value=None),
            patch("PromptExecutor._load_email_reader_config") as config,
            patch("PromptExecutor.collect_emails", AsyncMock(return_value=(emails, "Inbox", data_path))),
            patch("PromptExecutor.get_prompt_with_data", prompt_builder),
            patch("PromptExecutor.run_codex", AsyncMock(return_value="## TL;DR\n- Release is ready\n\n### Todo List\n- [ ] Reply to Release")),
            patch("PromptExecutor.write_email_summary") as save,
            patch.object(Path, "unlink") as unlink,
        ):
            config.return_value.get.return_value = "Inbox"
            result = await email_summary_operation({"start_date": "2026-08-15", "end_date": "2026-08-16"})

        self.assertEqual(
            result["ai_summary"],
            "## TL;DR\n- Release is ready\n\n### Todo List\n- [ ] Reply to Release",
        )
        self.assertEqual(result["emails"], emails)
        self.assertEqual(result["todos"], [{"id": "todo-1", "text": "Reply to Release", "completed": False}])
        self.assertEqual(prompt_builder.await_args.args[0], "email_interval_summary")
        self.assertEqual(json.loads(prompt_builder.await_args.kwargs["email_data"]), emails)
        save.assert_called_once_with(result)
        unlink.assert_called_once()

    async def test_rejects_invalid_dates_before_collecting_emails(self):
        with self.assertRaisesRegex(PromptExecutionError, "ISO format"):
            await email_summary_operation({"start_date": "15-08-2026", "end_date": "2026-08-16"})
