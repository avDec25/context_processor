const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

// Exercise the sender's real request/response function without loading UI/CDN resources.
const source = readFileSync(`${__dirname}/confluence.js`, 'utf8');
const start = source.indexOf('    async function triggerConfluenceAction(');
const end = source.indexOf('    // --- Page Instruction History', start);
assert.ok(start >= 0 && end > start);

function harness(status = 200) {
    const requests = [];
    const modals = [];
    let reloads = 0;
    const context = vm.createContext({
        URL, Date,
        window: { location: {
            href: 'https://example.com/confluence/pages/viewpage.action?pageId=123',
            reload: () => reloads++,
        } },
        originalFetch: async (url, options) => {
            requests.push({ url, payload: JSON.parse(options.body) });
            return { ok: status === 200, status };
        },
        readBodySafe: async () => ({ data: status === 200 ? 'result' : { detail: 'Update failed' } }),
        apiResponses: new Map(),
        lastProcessorResult: null,
        ensureExplainMarkdownDeps: async () => {},
        showProcessorModal: (...args) => modals.push(args),
    });
    vm.runInContext(source.slice(start, end), context);
    return { context, requests, modals, reloads: () => reloads };
}

for (const operation of ['explain', 'rewrite', 'page_update', 'delete']) {
    test(`${operation} sends page identity and the exact operation`, async () => {
        const h = harness();
        const button = { innerHTML: 'Button', style: {} };
        const extra = operation === 'page_update' ? { instruction: 'Change {instruction}' } : {};
        const refresh = ['rewrite', 'page_update'].includes(operation);
        await h.context.triggerConfluenceAction(button, operation, 'Working', extra, { refreshOnSuccess: refresh });
        assert.deepEqual(h.requests, [{ url: 'http://localhost:8000/confluence', payload: {
            operation, hostname: 'example.com', pathname: '/confluence/pages/viewpage.action',
            search: '?pageId=123', ...extra,
        } }]);
        assert.equal(h.reloads(), refresh ? 1 : 0);
        assert.equal(button.disabled, false);
        assert.equal(button.innerHTML, 'Button');
        if (operation === 'explain') assert.equal(h.modals[0][2].explainMarkdownMode, true);
    });
}

test('failed page updates show the error and do not reload', async () => {
    const h = harness(502);
    await h.context.triggerConfluenceAction({ innerHTML: 'Send', style: {} }, 'page_update', 'Working',
        { instruction: 'Change text' }, { refreshOnSuccess: true });
    assert.equal(h.reloads(), 0);
    assert.equal(h.modals.length, 1);
    assert.equal(h.modals[0][0].data.detail, 'Update failed');
});
