(function () {
    const apiResponses = new Map();
    let lastProcessorResult = null;

    // --- Configuration for External Libraries ---
    const LIBS = {
        marked: "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
        dompurify: "https://cdn.jsdelivr.net/npm/dompurify@3.0.8/dist/purify.min.js",
        css: "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown-light.min.css"
    };

    // --- Helper: Inject External Resources ---
    function loadCss(href) {
        if (document.querySelector(`link[href="${href}"]`)) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = href;
        document.head.appendChild(link);
    }

    // Robust script loader:
    // - If script tag exists but is still loading, wait for it.
    // - If it's already loaded, resolve immediately (via checker).
    function loadScript(src, { checker, timeoutMs = 8000 } = {}) {
        return new Promise((resolve, reject) => {
            try {
                if (checker && checker()) return resolve();

                const existing = document.querySelector(`script[src="${src}"]`);
                if (existing) {
                    // If already available, resolve
                    if (checker && checker()) return resolve();

                    existing.addEventListener("load", () => resolve(), { once: true });
                    existing.addEventListener("error", (e) => reject(e), { once: true });

                    // Fallback polling if load event already fired (rare)
                    const start = Date.now();
                    const timer = setInterval(() => {
                        if (checker && checker()) {
                            clearInterval(timer);
                            resolve();
                        } else if (Date.now() - start > timeoutMs) {
                            clearInterval(timer);
                            reject(new Error("Timed out waiting for script to load: " + src));
                        }
                    }, 50);

                    return;
                }

                const script = document.createElement("script");
                script.src = src;
                script.async = true;
                script.onload = () => resolve();
                script.onerror = (e) => reject(e);
                document.head.appendChild(script);
            } catch (e) {
                reject(e);
            }
        });
    }

    // --- Markdown deps (Explain modal only) ---
    let explainDepsPromise = null;

    function ensureExplainMarkdownDeps() {
        loadCss(LIBS.css);

        const hasMarked = () => !!(window.marked && typeof window.marked.parse === "function");
        const hasPurify = () => !!(window.DOMPurify && typeof window.DOMPurify.sanitize === "function");

        if (hasMarked() && hasPurify()) return Promise.resolve();

        if (!explainDepsPromise) {
            explainDepsPromise = Promise.all([
                loadScript(LIBS.marked, { checker: hasMarked }),
                loadScript(LIBS.dompurify, { checker: hasPurify })
            ]).then(() => {
                // Marked options (nice defaults for LLM responses)
                if (window.marked?.setOptions) {
                    window.marked.setOptions({
                        gfm: true,
                        breaks: true, // IMPORTANT: single newlines -> <br>
                        headerIds: false,
                        mangle: false
                    });
                }
            });
        }

        return explainDepsPromise;
    }

    function escapeHtml(str) {
        return String(str)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function toAbsUrl(input) {
        try {
            const u = typeof input === "string" ? input : input?.url;
            return new URL(u, window.location.href).toString();
        } catch {
            return String(input);
        }
    }

    // --- Timing History (localStorage) ---
    const TIMING_HISTORY_KEY = "injected_timing_history_v1";

    function saveTimingHistory(operation, durationMs) {
        try {
            const stored = localStorage.getItem(TIMING_HISTORY_KEY);
            const all = stored ? JSON.parse(stored) : {};
            if (!Array.isArray(all[operation])) all[operation] = [];
            all[operation].push({ ts: Date.now(), ms: durationMs });
            // Keep last 50 entries per operation
            if (all[operation].length > 50) all[operation] = all[operation].slice(-50);
            localStorage.setItem(TIMING_HISTORY_KEY, JSON.stringify(all));
        } catch {}
    }

    // --- Timer Badge ---
    function wrapWithTimerBadge(btn) {
        const container = document.createElement("div");
        container.style.cssText = "position: relative; display: inline-flex;";
        const badge = document.createElement("div");
        badge.className = "injected-timer-badge";
        container.appendChild(btn);
        container.appendChild(badge);
        btn._timerBadge = badge;
        return container;
    }

    function startTimerBadge(badge) {
        badge.style.removeProperty("animation");
        badge.classList.add("counting");
        badge.textContent = "0.0s";
        badge.style.display = "block";
        badge.style.opacity = "1";
        const startTime = Date.now();
        const interval = setInterval(() => {
            badge.textContent = ((Date.now() - startTime) / 1000).toFixed(1) + "s";
        }, 100);
        return { startTime, interval };
    }

    function stopTimerBadge(badge, timerObj, operation) {
        clearInterval(timerObj.interval);
        const durationMs = Date.now() - timerObj.startTime;
        badge.classList.remove("counting");
        badge.textContent = (durationMs / 1000).toFixed(1) + "s";
        saveTimingHistory(operation, durationMs);
        // Fade out after 2.5s
        setTimeout(() => {
            badge.style.animation = "badge-fade-out 0.4s ease forwards";
            setTimeout(() => {
                badge.style.display = "none";
                badge.style.animation = "";
                badge.style.opacity = "1";
            }, 420);
        }, 2500);
    }

    async function readBodySafe(response) {
        const cloned = response.clone();
        let text = "";
        try {
            text = await cloned.text();
        } catch (e) {
            return {
                kind: "unreadable",
                raw: "",
                data: `[Body not readable in browser] ${e?.message || e}`
            };
        }

        try {
            return { kind: "json", raw: text, data: JSON.parse(text) };
        } catch {
            return { kind: "text", raw: text, data: text };
        }
    }

    // Try to find markdown content inside typical JSON API shapes
    function extractMarkdownCandidate(data) {
        if (typeof data === "string") return data;
        if (!data || typeof data !== "object") return null;

        const keys = ["markdown", "md", "explanation", "content", "result", "message", "text", "output"];
        for (const k of keys) {
            if (typeof data[k] === "string") return data[k];
        }

        if (data.data != null) return extractMarkdownCandidate(data.data);
        return null;
    }

    // Inject Global CSS (Spinner + Animations + Scrollbar Fix)
    function injectGlobalStyles() {
        if (document.getElementById("injected-global-styles")) return;
        const style = document.createElement("style");
        style.id = "injected-global-styles";
        style.innerHTML = `
            @keyframes spin-rotate {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            @keyframes overlay-fade-in {
                0% {
                    background-color: rgba(30, 30, 30, 0);
                    backdrop-filter: blur(0px);
                    -webkit-backdrop-filter: blur(0px);
                }
                100% {
                    background-color: rgba(30, 30, 30, 0.4);
                    backdrop-filter: blur(5px);
                    -webkit-backdrop-filter: blur(5px);
                }
            }

            @keyframes modal-slide-down {
                0% {
                    opacity: 0;
                    transform: translateY(-30px) scale(0.98);
                }
                100% {
                    opacity: 1;
                    transform: translateY(0) scale(1);
                }
            }

            .injected-spinner {
                display: inline-block;
                width: 14px;
                height: 14px;
                border: 2px solid rgba(255, 255, 255, 0.3);
                border-radius: 50%;
                border-top-color: #fff;
                animation: spin-rotate 1s linear infinite;
                margin-right: 8px;
                vertical-align: middle;
            }

            .markdown-body {
                box-sizing: border-box;
                min-width: 200px;
                max-width: 100%;
                margin: 0 auto;
                padding: 15px;
                font-size: 14px;
            }

            .custom-scrollbar {
                scrollbar-width: thin;
                scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
                overscroll-behavior: contain;
            }
            .custom-scrollbar::-webkit-scrollbar {
                width: 10px;
                height: 10px;
            }
            .custom-scrollbar::-webkit-scrollbar-track {
                background: transparent;
                margin-bottom: 12px;
            }
            .custom-scrollbar::-webkit-scrollbar-thumb {
                background-color: rgba(0, 0, 0, 0.2);
                border-radius: 10px;
                border: 2px solid transparent;
                background-clip: content-box;
            }
            .custom-scrollbar::-webkit-scrollbar-thumb:hover {
                background-color: rgba(0, 0, 0, 0.35);
            }

            @keyframes badge-count-pulse {
                0%, 100% { opacity: 1; box-shadow: 0 2px 8px rgba(0,0,0,0.35); }
                50%       { opacity: 0.65; box-shadow: 0 2px 12px rgba(0,0,0,0.5); }
            }

            @keyframes badge-fade-out {
                0%   { opacity: 1; }
                100% { opacity: 0; }
            }

            .injected-timer-badge {
                position: absolute;
                top: -13px;
                right: -10px;
                background: rgba(15, 15, 15, 0.88);
                color: #fff;
                font-size: 10px;
                font-weight: 700;
                padding: 2px 7px;
                border-radius: 20px;
                pointer-events: none;
                white-space: nowrap;
                z-index: 10;
                font-family: ui-monospace, 'Cascadia Code', monospace;
                box-shadow: 0 2px 6px rgba(0,0,0,0.35);
                letter-spacing: 0.02em;
                display: none;
            }

            .injected-timer-badge.counting {
                animation: badge-count-pulse 0.75s ease-in-out infinite;
            }
        `;
        document.head.appendChild(style);
    }

    function showModal({ title, bodyHtml }) {
        const originalOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        const modal = document.createElement("div");
        modal.style.cssText = `
            position: fixed; inset: 0;
            background-color: rgba(30, 30, 30, 0);
            backdrop-filter: blur(0px);
            -webkit-backdrop-filter: blur(0px);
            z-index: 1000000;
            display: flex; justify-content: center; align-items: flex-start;
            padding-top: 60px;
            box-sizing: border-box;
            animation: overlay-fade-in 0.8s cubic-bezier(0.22, 1, 0.36, 1) forwards;
            transform: translateZ(0);
        `;

        const modalContent = document.createElement("div");
        const denseShadow = `0px 4px 6px rgba(0, 0, 0, 0.3), 0px 10px 25px rgba(0, 0, 0, 0.2)`;

        modalContent.style.cssText = `
            background-color: white;
            padding: 0;
            border-radius: 24px;
            width: min(900px, 90vw);
            max-height: 80vh;
            display: flex;
            flex-direction: column;
            box-shadow: ${denseShadow};
            font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
            overflow: hidden;
            animation: modal-slide-down 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            opacity: 0;
            animation-delay: 0.1s;
        `;

        modalContent.innerHTML = `
            <div style="padding: 16px 24px; border-bottom: 1px solid #eee; display:flex; align-items:center; justify-content:space-between; flex-shrink: 0; background: white;">
                <h2 style="margin:0; font-size: 18px; font-weight: 700; color: #333;">${escapeHtml(title)}</h2>
                <button id="closeModal"
                    style="padding:6px 12px; background:#ef4444; color:white; border:none; border-radius:8px; cursor:pointer; font-weight:600; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                    Close
                </button>
            </div>
            <div class="custom-scrollbar" style="overflow-y: auto; padding: 24px; flex-grow: 1;">
                ${bodyHtml}
            </div>
        `;

        modal.appendChild(modalContent);
        document.body.appendChild(modal);

        const closeModal = () => {
            document.body.style.overflow = originalOverflow;
            if (modal.parentNode) document.body.removeChild(modal);
        };

        modalContent.querySelector("#closeModal").addEventListener("click", closeModal);
        modal.addEventListener("click", (e) => {
            if (e.target === modal) closeModal();
        });
    }

    function showApiModal() {
        let html = `<div style="color:#111827;">Captured API Responses (${apiResponses.size})</div>`;

        if (apiResponses.size === 0) {
            html += `<p style="margin:12px 0 0;">No API calls captured yet.</p>`;
        } else {
            const sorted = Array.from(apiResponses.entries()).sort(([, a], [, b]) => {
                const at = a?.timestamp instanceof Date ? a.timestamp.getTime() : 0;
                const bt = b?.timestamp instanceof Date ? b.timestamp.getTime() : 0;
                return bt - at;
            });

            for (const [, response] of sorted) {
                const pretty =
                    typeof response.data === "string" ? response.data : JSON.stringify(response.data, null, 2);

                html += `
                    <div style="margin-top:14px; padding:12px; border:1px solid #e5e7eb; border-radius:12px;">
                        <div><strong>URL:</strong> ${escapeHtml(response.url)}</div>
                        <div><strong>Type:</strong> ${escapeHtml(response.type)}</div>
                        <div><strong>Time:</strong> ${response.timestamp?.toLocaleString?.() ?? "-"}</div>
                        <div><strong>Status:</strong> ${response.status ?? "-"}</div>
                        <div style="margin-top:8px;"><strong>Data:</strong></div>
                        <pre style="background:#f9fafb; border:1px solid #eee; padding:10px; border-radius:8px; overflow:auto; max-height:240px; margin:6px 0 0; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(pretty)}</pre>
                    </div>
                `;
            }
        }

        showModal({ title: "Captured API Responses", bodyHtml: html });
    }

    /**
     * For Explain modal:
     * - Markdown -> HTML via marked
     * - Sanitize via DOMPurify
     * - Insert sanitized HTML into .markdown-body
     * - DO NOT wrap in <pre> unless markdown itself produces it (code fences)
     */
    function renderExplainMarkdownToSafeHtml(markdownInput) {
        const hasMarked = !!(window.marked && typeof window.marked.parse === "function");
        const hasPurify = !!(window.DOMPurify && typeof window.DOMPurify.sanitize === "function");

        // If we cannot sanitize, do not render HTML (avoid XSS); show escaped text with preserved newlines.
        if (!hasMarked || !hasPurify) {
            return `<div style="white-space: pre-wrap;">${escapeHtml(markdownInput)}</div>`;
        }

        const rawHtml = window.marked.parse(markdownInput);
        const safeHtml = window.DOMPurify.sanitize(rawHtml);
        return safeHtml; // may contain <pre> only if markdown had code blocks
    }

    function showProcessorModal(result, title = "Operation Result", opts = {}) {
        if (!result) {
            showModal({ title, bodyHtml: `<p style="margin:0;">No response yet.</p>` });
            return;
        }

        const meta = `
            <div style="display:grid; gap:6px; color:#111827; margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px dashed #e5e7eb;">
                <div><strong>URL:</strong> ${escapeHtml(result.url)}</div>
                <div><strong>Time:</strong> ${result.timestamp.toLocaleString()}</div>
                ${
                    result.error
                        ? `<div><strong>Status:</strong> <span style="color:#b91c1c;">Error</span></div>`
                        : `<div><strong>Status:</strong> ${result.status} (${result.ok ? "OK" : "Not OK"})</div>`
                }
            </div>
        `;

        // Error case
        if (result.error != null) {
            const body = `<pre style="background:#fef2f2; border:1px solid #fecaca; padding:10px; border-radius:12px; overflow:auto; max-height:320px; margin:12px 0 0; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(result.error)}</pre>`;
            showModal({ title, bodyHtml: meta + body });
            return;
        }

        // Explain-only behavior
        if (opts.explainMarkdownMode) {
            const mdCandidate = extractMarkdownCandidate(result.data);

            // If it's not a string, render JSON as a markdown code fence
            // (this will generate <pre> only via markdown, which is "required by markdown").
            const markdownInput =
                mdCandidate != null ? mdCandidate : "```json\n" + JSON.stringify(result.data, null, 2) + "\n```";

            const safeHtml = renderExplainMarkdownToSafeHtml(markdownInput);
            const body = `<div class="markdown-body">${safeHtml}</div>`;
            showModal({ title, bodyHtml: meta + body });
            return;
        }

        // Default behavior for other modals (Rewrite/Delete/etc.)
        // Keep it simple + safe: show string as escaped <pre>, and JSON as escaped <pre>.
        const pretty =
            typeof result.data === "string" ? result.data : JSON.stringify(result.data, null, 2);

        const body = `<pre style="background:#f9fafb; border:1px solid #eee; padding:10px; border-radius:12px; overflow:auto; max-height:420px; margin:12px 0 0; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(pretty)}</pre>`;
        showModal({ title, bodyHtml: meta + body });
    }

    // --- Capture fetch/XHR ---
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
        const url = toAbsUrl(args[0]);
        try {
            const response = await originalFetch.apply(this, args);
            await (async () => {
                try {
                    const body = await readBodySafe(response);
                    apiResponses.set(url, {
                        url,
                        data: body.data,
                        timestamp: new Date(),
                        type: "fetch",
                        status: response.status
                    });
                } catch (e) {
                    apiResponses.set(url, {
                        url,
                        data: `[capture error] ${e?.message || e}`,
                        timestamp: new Date(),
                        type: "fetch-capture-error",
                        status: response.status
                    });
                }
            })();
            return response;
        } catch (e) {
            apiResponses.set(url, {
                url,
                data: `[fetch error] ${e?.message || e}`,
                timestamp: new Date(),
                type: "fetch-error"
            });
            throw e;
        }
    };

    const originalXHROpen = XMLHttpRequest.prototype.open;
    const originalXHRSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url) {
        this._url = toAbsUrl(url);
        return originalXHROpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function () {
        this.addEventListener("load", function () {
            const url = this._url || "(unknown)";
            const text = this.responseText;
            let data = text;
            try {
                data = JSON.parse(text);
            } catch {}
            apiResponses.set(url, {
                url,
                data,
                timestamp: new Date(),
                type: "xhr",
                status: this.status
            });
        });
        return originalXHRSend.apply(this, arguments);
    };

    async function triggerPrAction(btn, operation, loadingText, extraBody = {}, opts = {}) {
        const url = "http://localhost:8000/confluence";

        const badge = btn._timerBadge || null;
        let timerObj = null;

        const originalContent = btn.innerHTML;
        btn.disabled = true;
        btn.style.opacity = "0.85";
        btn.style.cursor = "wait";
        btn.innerHTML = `<span class="injected-spinner"></span>${loadingText}`;

        if (badge) timerObj = startTimerBadge(badge);

        try {
            const pageUrl = new URL(window.location.href);
            const res = await originalFetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    operation,
                    hostname: pageUrl.hostname,
                    pathname: pageUrl.pathname,
                    ...extraBody
                })
            });

            const body = await readBodySafe(res);
            lastProcessorResult = {
                url,
                data: body.data,
                ok: res.ok,
                status: res.status,
                timestamp: new Date()
            };

            apiResponses.set(url, {
                url,
                data: body.data,
                timestamp: new Date(),
                type: `${operation}(fetch)`,
                status: res.status
            });

            let modalTitle = "Result";
            if (operation === "delete") modalTitle = "Delete Result";
            else if (operation === "rewrite") modalTitle = "PR Review Result";
            else if (operation === "explain") modalTitle = "Explanation Result";

            if (opts.refreshOnSuccess && res.ok) {
                window.location.reload();
                return;
            }

            // Only Explain: ensure marked + DOMPurify are available, then render markdown safely.
            if (operation === "explain") {
                await ensureExplainMarkdownDeps().catch(() => {
                    // fallback is handled in renderExplainMarkdownToSafeHtml()
                });
            }

            showProcessorModal(lastProcessorResult, modalTitle, {
                explainMarkdownMode: operation === "explain"
            });
        } catch (err) {
            lastProcessorResult = {
                url,
                error: String(err?.message || err),
                timestamp: new Date()
            };

            apiResponses.set(url, {
                url,
                data: lastProcessorResult.error,
                timestamp: new Date(),
                type: `${operation}(fetch-error)`
            });

            showProcessorModal(lastProcessorResult, "Operation Error");
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalContent;
            btn.style.opacity = "1";
            btn.style.cursor = "pointer";
            if (badge && timerObj) stopTimerBadge(badge, timerObj, operation);
        }
    }

    // --- Page Instruction History (localStorage, keyed per page pathname) ---
    const PAGE_HISTORY_KEY_PREFIX = "ctx_page_instructions_";

    function getHistoryKey() {
        return PAGE_HISTORY_KEY_PREFIX + window.location.pathname;
    }

    function loadPageHistory() {
        try {
            const raw = localStorage.getItem(getHistoryKey());
            return raw ? JSON.parse(raw) : [];
        } catch { return []; }
    }

    function saveToPageHistory(instruction) {
        if (!instruction || !instruction.trim()) return;
        try {
            const history = loadPageHistory();
            history.push({ instruction: instruction.trim(), ts: Date.now() });
            if (history.length > 20) history.splice(0, history.length - 20);
            localStorage.setItem(getHistoryKey(), JSON.stringify(history));
        } catch {}
    }

    function renderPageHistory(container, textInputEl) {
        const history = loadPageHistory();
        container.innerHTML = "";

        if (history.length === 0) {
            container.style.display = "none";
            return;
        }

        container.style.display = "block";

        const header = document.createElement("div");
        header.textContent = "Previous instructions";
        header.style.cssText = `
            font-size: 11px;
            font-weight: 700;
            color: #6b7280;
            margin-bottom: 6px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            font-family: ui-sans-serif, system-ui, -apple-system;
        `;
        container.appendChild(header);

        const entries = [...history].reverse();
        for (const entry of entries) {
            const ts = new Date(entry.ts).toLocaleString([], {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false
            });

            const item = document.createElement("div");
            item.style.cssText = `
                padding: 7px 10px;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.55);
                margin-bottom: 5px;
                cursor: pointer;
                transition: background 0.12s ease;
            `;
            item.addEventListener("mouseenter", () => {
                item.style.background = "rgba(255, 255, 255, 0.85)";
            });
            item.addEventListener("mouseleave", () => {
                item.style.background = "rgba(255, 255, 255, 0.55)";
            });
            item.addEventListener("click", () => {
                textInputEl.value = entry.instruction;
                textInputEl.focus();
            });

            const tsEl = document.createElement("div");
            tsEl.textContent = ts;
            tsEl.style.cssText = `
                font-size: 10px;
                color: #9ca3af;
                margin-bottom: 3px;
                font-family: ui-monospace, 'Cascadia Code', monospace;
            `;

            const textEl = document.createElement("div");
            textEl.textContent = entry.instruction.length > 120
                ? entry.instruction.slice(0, 120) + "\u2026"
                : entry.instruction;
            textEl.style.cssText = `
                font-size: 12px;
                color: #374151;
                line-height: 1.45;
                white-space: pre-wrap;
                word-break: break-word;
                font-family: ui-sans-serif, system-ui, -apple-system;
            `;

            item.appendChild(tsEl);
            item.appendChild(textEl);
            container.appendChild(item);
        }
    }

    function initButtons() {
        injectGlobalStyles();

        // Optional: prefetch deps (best-effort). Explain still works if this fails; it will retry on click.
        ensureExplainMarkdownDeps().catch(() => {});

        const wrapper = document.createElement("div");
        wrapper.style.cssText = `
            position: fixed;
            bottom: 45px;
            right: 20px;
            z-index: 999999;
            display: flex;
            gap: 12px;
            align-items: center;
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.25);
            backdrop-filter: blur(5px);
            -webkit-backdrop-filter: blur(5px);
            border-radius: 20px;
            border: 2px solid rgba(255, 255, 255, 0.4);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.15);
        `;

        // --- BUTTON 1: EXPLAIN (INDIGO) ---
        const explainButton = document.createElement("button");
        explainButton.textContent = "Explain";
        explainButton.style.cssText = `
            padding: 10px 18px;
            background-color: #6366f1;
            color: white;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 8px 24px 0 rgba(99, 102, 241, 0.6);
            transition: all 0.15s ease;
            display: flex;
            align-items: center;
        `;
        explainButton.addEventListener("mouseenter", () => {
            explainButton.style.backgroundColor = "#4f46e5";
            explainButton.style.transform = "translateY(-1px)";
        });
        explainButton.addEventListener("mouseleave", () => {
            explainButton.style.backgroundColor = "#6366f1";
            explainButton.style.transform = "translateY(0)";
        });
        explainButton.addEventListener("click", () =>
            triggerPrAction(explainButton, "explain", "Explaining...")
        );

        // --- BUTTON 2: REWRITE (EMERALD) ---
        const rewriteButton = document.createElement("button");
        rewriteButton.textContent = "Rewrite";
        rewriteButton.style.cssText = `
            padding: 10px 18px;
            background-color: #10b981;
            color: white;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 8px 24px 0 rgba(16, 185, 129, 0.6);
            transition: all 0.15s ease;
            display: flex;
            align-items: center;
        `;
        rewriteButton.addEventListener("mouseenter", () => {
            rewriteButton.style.backgroundColor = "#059669";
            rewriteButton.style.transform = "translateY(-1px)";
        });
        rewriteButton.addEventListener("mouseleave", () => {
            rewriteButton.style.backgroundColor = "#10b981";
            rewriteButton.style.transform = "translateY(0)";
        });
        rewriteButton.addEventListener("click", () =>
            triggerPrAction(rewriteButton, "rewrite", "ReWriting...")
        );

        // --- BUTTON 3: DELETE (RED) ---
        const deleteButton = document.createElement("button");
        deleteButton.textContent = "Delete";
        deleteButton.style.cssText = `
            padding: 10px 18px;
            background-color: #ef4444;
            color: white;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 8px 24px 0 rgba(239, 68, 68, 0.6);
            transition: all 0.15s ease;
            display: flex;
            align-items: center;
        `;
        deleteButton.addEventListener("mouseenter", () => {
            deleteButton.style.backgroundColor = "#dc2626";
            deleteButton.style.transform = "translateY(-1px)";
        });
        deleteButton.addEventListener("mouseleave", () => {
            deleteButton.style.backgroundColor = "#ef4444";
            deleteButton.style.transform = "translateY(0)";
        });
        deleteButton.addEventListener("click", () =>
            triggerPrAction(deleteButton, "delete", "Deleting...")
        );

        // --- BUTTON 4: API DATA (GRAY) ---
        const apiButton = document.createElement("button");
        apiButton.textContent = "API Data";
        apiButton.style.cssText = `
            padding: 10px 18px;
            background-color: #4b5563;
            color: white;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 8px 24px 0 rgba(75, 85, 99, 0.6);
            transition: all 0.15s ease;
        `;
        apiButton.addEventListener("mouseenter", () => {
            apiButton.style.backgroundColor = "#374151";
            apiButton.style.transform = "translateY(-1px)";
        });
        apiButton.addEventListener("mouseleave", () => {
            apiButton.style.backgroundColor = "#4b5563";
            apiButton.style.transform = "translateY(0)";
        });
        apiButton.addEventListener("click", showApiModal);

        // --- TEXT INPUT PANEL (hidden by default) ---
        const textInputPanel = document.createElement("div");
        textInputPanel.style.cssText = `
            position: fixed;
            bottom: 45px;
            right: 20px;
            z-index: 999999;
            display: none;
            flex-direction: column;
            gap: 10px;
            padding: 14px 16px;
            background: rgba(255, 255, 255, 0.25);
            backdrop-filter: blur(5px);
            -webkit-backdrop-filter: blur(5px);
            border-radius: 20px;
            border: 2px solid rgba(255, 255, 255, 0.4);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.15);
            width: 320px;
            box-sizing: border-box;
        `;

        const textInput = document.createElement("textarea");
        textInput.placeholder = "Type your message...";
        textInput.style.cssText = `
            width: 100%;
            padding: 10px 12px;
            border: 1.5px solid #e5e7eb;
            border-radius: 12px;
            font-size: 14px;
            font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
            resize: vertical;
            min-height: 80px;
            outline: none;
            box-sizing: border-box;
            background: rgba(255, 255, 255, 0.92);
            color: #111827;
        `;
        textInput.addEventListener("focus", () => {
            textInput.style.borderColor = "#8b5cf6";
            textInput.style.boxShadow = "0 0 0 3px rgba(139, 92, 246, 0.15)";
        });
        textInput.addEventListener("blur", () => {
            textInput.style.borderColor = "#e5e7eb";
            textInput.style.boxShadow = "none";
        });

        const panelBtnRow = document.createElement("div");
        panelBtnRow.style.cssText = `
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        `;

        const sendInputBtn = document.createElement("button");
        sendInputBtn.textContent = "Send";
        sendInputBtn.style.cssText = `
            padding: 8px 18px;
            background-color: #10b981;
            color: white;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
            transition: all 0.15s ease;
            display: flex;
            align-items: center;
        `;
        sendInputBtn.addEventListener("mouseenter", () => {
            sendInputBtn.style.backgroundColor = "#059669";
            sendInputBtn.style.transform = "translateY(-1px)";
        });
        sendInputBtn.addEventListener("mouseleave", () => {
            sendInputBtn.style.backgroundColor = "#10b981";
            sendInputBtn.style.transform = "translateY(0)";
        });
        sendInputBtn.addEventListener("click", () => {
            const instruction = textInput.value;
            saveToPageHistory(instruction);
            renderPageHistory(historyContainer, textInput);
            textInput.disabled = true;
            textInput.style.opacity = "0.6";
            textInput.style.cursor = "not-allowed";
            triggerPrAction(sendInputBtn, "page_update", "Sending...", { instruction }, { refreshOnSuccess: true })
                .finally(() => {
                    textInput.disabled = false;
                    textInput.style.opacity = "1";
                    textInput.style.cursor = "";
                });
        });

        const closeInputBtn = document.createElement("button");
        closeInputBtn.textContent = "Close";
        closeInputBtn.style.cssText = `
            padding: 8px 16px;
            background-color: #ef4444;
            color: white;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
            transition: all 0.15s ease;
        `;
        closeInputBtn.addEventListener("mouseenter", () => {
            closeInputBtn.style.backgroundColor = "#dc2626";
            closeInputBtn.style.transform = "translateY(-1px)";
        });
        closeInputBtn.addEventListener("mouseleave", () => {
            closeInputBtn.style.backgroundColor = "#ef4444";
            closeInputBtn.style.transform = "translateY(0)";
        });
        closeInputBtn.addEventListener("click", () => {
            textInputPanel.style.display = "none";
            wrapper.style.display = "flex";
        });

        const historyContainer = document.createElement("div");
        historyContainer.className = "custom-scrollbar";
        historyContainer.style.cssText = `
            display: none;
            max-height: 200px;
            overflow-y: auto;
            margin-top: 6px;
            padding-top: 10px;
            border-top: 1px solid rgba(255, 255, 255, 0.5);
        `;

        panelBtnRow.appendChild(sendInputBtn);
        panelBtnRow.appendChild(closeInputBtn);
        textInputPanel.appendChild(textInput);
        textInputPanel.appendChild(panelBtnRow);
        textInputPanel.appendChild(historyContainer);
        document.body.appendChild(textInputPanel);

        // --- BUTTON: UPDATE PAGE (VIOLET) ---
        const askButton = document.createElement("button");
        askButton.textContent = "Update Page";
        askButton.style.cssText = `
            padding: 10px 18px;
            background-color: #8b5cf6;
            color: white;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 8px 24px 0 rgba(139, 92, 246, 0.6);
            transition: all 0.15s ease;
        `;
        askButton.addEventListener("mouseenter", () => {
            askButton.style.backgroundColor = "#7c3aed";
            askButton.style.transform = "translateY(-1px)";
        });
        askButton.addEventListener("mouseleave", () => {
            askButton.style.backgroundColor = "#8b5cf6";
            askButton.style.transform = "translateY(0)";
        });
        askButton.addEventListener("click", () => {
            wrapper.style.display = "none";
            textInputPanel.style.display = "flex";
            renderPageHistory(historyContainer, textInput);
            textInput.focus();
        });

        wrapper.appendChild(wrapWithTimerBadge(askButton));
        wrapper.appendChild(wrapWithTimerBadge(explainButton));
        wrapper.appendChild(wrapWithTimerBadge(rewriteButton));
        wrapper.appendChild(wrapWithTimerBadge(deleteButton));
        wrapper.appendChild(apiButton);
        document.body.appendChild(wrapper);
    }

    if (document.body) initButtons();
    else window.addEventListener("DOMContentLoaded", initButtons);
})();
