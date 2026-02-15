(function () {
    const apiResponses = new Map();
    let lastProcessorResult = null;

    // --- Configuration for External Libraries ---
    const LIBS = {
        marked: "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
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

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            if (document.querySelector(`script[src="${src}"]`)) {
                return resolve(); // Already loaded
            }
            const script = document.createElement("script");
            script.src = src;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    // Inject Global CSS (Spinner + Animations + Scrollbar Fix)
    function injectGlobalStyles() {
        if (document.getElementById('injected-global-styles')) return;
        const style = document.createElement('style');
        style.id = 'injected-global-styles';
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

            /* --- NEW: Custom Scrollbar to fix corner clipping --- */
            .custom-scrollbar {
                scrollbar-width: thin;
                scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
                overscroll-behavior: contain; /* Prevents scroll chaining to body */
            }
            /* Webkit (Chrome/Safari/Edge) */
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
        `;
        document.head.appendChild(style);
    }

    function toAbsUrl(input) {
        try {
            const u = typeof input === "string" ? input : input?.url;
            return new URL(u, window.location.href).toString();
        } catch {
            return String(input);
        }
    }

    function escapeHtml(str) {
        return String(str)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
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
                data: `[Body not readable in browser] ${e?.message || e}`,
            };
        }

        try {
            return {kind: "json", raw: text, data: JSON.parse(text)};
        } catch {
            return {kind: "text", raw: text, data: text};
        }
    }

    // --- FIX APPLIED HERE ---
    function showModal({title, bodyHtml}) {
        // 1. Prevent background scrolling to stop flicker/repaint issues
        const originalOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        const modal = document.createElement("div");

        // Added 'transform: translateZ(0)' to force GPU layer promotion
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

        // Cleanup function to restore scroll and remove modal
        const closeModal = () => {
            document.body.style.overflow = originalOverflow; // Restore scroll
            if (modal.parentNode) {
                document.body.removeChild(modal);
            }
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
                    typeof response.data === "string"
                        ? response.data
                        : JSON.stringify(response.data, null, 2);

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
        showModal({title: "Captured API Responses", bodyHtml: html});
    }


    function showProcessorModal(result, title = "Operation Result") {
        if (!result) {
            showModal({
                title: title,
                bodyHtml: `<p style="margin:0;">No response yet.</p>`,
            });
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

        let body = "";

        if (result.error != null) {
            body = `<pre style="background:#fef2f2; border:1px solid #fecaca; padding:10px; border-radius:12px; overflow:auto; max-height:320px; margin:12px 0 0; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(result.error)}</pre>`;
        } else {
            // --- MARKDOWN RENDERING LOGIC ---
            let contentToRender = "";

            if (typeof result.data === "string") {
                contentToRender = result.data;
            } else {
                contentToRender = "```json\n" + JSON.stringify(result.data, null, 2) + "\n```";
            }

            let renderedHtml = "";
            if (window.marked && typeof window.marked.parse === 'function') {
                try {
                    renderedHtml = window.marked.parse(contentToRender);
                } catch (e) {
                    renderedHtml = `<p style="color:red">Error rendering markdown: ${e.message}</p><pre>${escapeHtml(contentToRender)}</pre>`;
                }
            } else {
                renderedHtml = `<pre>${escapeHtml(contentToRender)}</pre>`;
            }

            body = `<div class="markdown-body">${renderedHtml}</div>`;
        }

        showModal({title: title, bodyHtml: meta + body});
    }

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
                        status: response.status,
                    });
                } catch (e) {
                    apiResponses.set(url, {
                        url,
                        data: `[capture error] ${e?.message || e}`,
                        timestamp: new Date(),
                        type: "fetch-capture-error",
                        status: response.status,
                    });
                }
            })();
            return response;
        } catch (e) {
            apiResponses.set(url, {
                url,
                data: `[fetch error] ${e?.message || e}`,
                timestamp: new Date(),
                type: "fetch-error",
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
            try { data = JSON.parse(text); } catch {}
            apiResponses.set(url, {
                url,
                data,
                timestamp: new Date(),
                type: "xhr",
                status: this.status,
            });
        });
        return originalXHRSend.apply(this, arguments);
    };

    async function triggerPrAction(btn, operation, loadingText) {
        const url = "http://localhost:8000/confluence";

        const originalContent = btn.innerHTML;
        btn.disabled = true;
        btn.style.opacity = "0.85";
        btn.style.cursor = "wait";
        btn.innerHTML = `<span class="injected-spinner"></span>${loadingText}`;

        try {
            const pageUrl = new URL(window.location.href);
            const res = await originalFetch(url, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    operation: operation,
                    hostname: pageUrl.hostname,
                    pathname: pageUrl.pathname
                }),
            });

            const body = await readBodySafe(res);
            lastProcessorResult = {
                url,
                data: body.data,
                ok: res.ok,
                status: res.status,
                timestamp: new Date(),
            };

            apiResponses.set(url, {
                url,
                data: body.data,
                timestamp: new Date(),
                type: `${operation}(fetch)`,
                status: res.status,
            });

            let modalTitle = "Result";
            if (operation === 'delete') modalTitle = "Delete Result";
            else if (operation === 'rewrite') modalTitle = "PR Review Result";
            else if (operation === 'explain') modalTitle = "Explanation Result";

            showProcessorModal(lastProcessorResult, modalTitle);
        } catch (err) {
            lastProcessorResult = {
                url,
                error: String(err?.message || err),
                timestamp: new Date(),
            };

            apiResponses.set(url, {
                url,
                data: lastProcessorResult.error,
                timestamp: new Date(),
                type: `${operation}(fetch-error)`,
            });

            showProcessorModal(lastProcessorResult, "Operation Error");
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalContent;
            btn.style.opacity = "1";
            btn.style.cursor = "pointer";
        }
    }

    function initButtons() {
        // 1. Load External Libraries for Markdown
        loadCss(LIBS.css);
        loadScript(LIBS.marked).catch(e => console.error("Failed to load Marked.js", e));

        // 2. Inject CSS
        injectGlobalStyles();

        const wrapper = document.createElement("div");

        wrapper.style.cssText = `
          position: fixed;
          bottom: 20px;
          right: 20px;
          z-index: 999999;
          display: flex;
          gap: 12px;
          align-items: center;

          /* Glass Panel Styles */
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
             explainButton.style.backgroundColor = "#4f46e5"; // Indigo-600
             explainButton.style.transform = "translateY(-1px)";
        });
        explainButton.addEventListener("mouseleave", () => {
             explainButton.style.backgroundColor = "#6366f1";
             explainButton.style.transform = "translateY(0)";
        });
        explainButton.addEventListener("click", () => triggerPrAction(explainButton, 'explain', 'Explaining...'));


        // --- BUTTON 2: REVIEW PR (EMERALD) ---
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
             rewriteButton.style.backgroundColor = "#059669"; // Emerald-600
             rewriteButton.style.transform = "translateY(-1px)";
        });
        rewriteButton.addEventListener("mouseleave", () => {
             rewriteButton.style.backgroundColor = "#10b981";
             rewriteButton.style.transform = "translateY(0)";
        });
        rewriteButton.addEventListener("click", () => triggerPrAction(rewriteButton, 'rewrite', 'ReWriting...'));



        // --- BUTTON 4: DELETE (ROSE RED) ---
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
             deleteButton.style.backgroundColor = "#dc2626"; // Red-600
             deleteButton.style.transform = "translateY(-1px)";
        });
        deleteButton.addEventListener("mouseleave", () => {
             deleteButton.style.backgroundColor = "#ef4444";
             deleteButton.style.transform = "translateY(0)";
        });
        deleteButton.addEventListener("click", () => triggerPrAction(deleteButton, 'delete', 'Deleting...'));


        // --- BUTTON 5: API DATA (SLATE GRAY) ---
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
            apiButton.style.backgroundColor = "#374151"; // Gray-700
            apiButton.style.transform = "translateY(-1px)";
        });
        apiButton.addEventListener("mouseleave", () => {
            apiButton.style.backgroundColor = "#4b5563";
            apiButton.style.transform = "translateY(0)";
        });
        apiButton.addEventListener("click", showApiModal);

        wrapper.appendChild(explainButton);
        wrapper.appendChild(rewriteButton);
        wrapper.appendChild(deleteButton);
        wrapper.appendChild(apiButton);
        document.body.appendChild(wrapper);
    }

    if (document.body) initButtons();
    else window.addEventListener("DOMContentLoaded", initButtons);
})();