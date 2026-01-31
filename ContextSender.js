(function () {
    const apiResponses = new Map();
    let lastProcessorResult = null;

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

    function showModal({title, bodyHtml}) {
        const modal = document.createElement("div");
        modal.style.cssText = `
      position: fixed; inset: 0;
      background-color: rgba(0,0,0,0.7);
      z-index: 1000000;
      display: flex; justify-content: center; align-items: center;
      padding: 16px; box-sizing: border-box;
    `;

        const modalContent = document.createElement("div");
        modalContent.style.cssText = `
      background-color: white;
      padding: 20px;
      border-radius: 8px;
      width: min(900px, 90vw);
      max-height: 80vh;
      overflow: auto;
      box-shadow: rgba(50, 50, 93, 0.25) 0px 2px 5px -1px, rgba(0, 0, 0, 0.3) 0px 1px 3px -1px;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    `;

        modalContent.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
        <h2 style="margin:0;">${escapeHtml(title)}</h2>
        <button id="closeModal"
          style="padding:8px 12px; background:#f44336; color:white; border:none; border-radius:6px; cursor:pointer;">
          Close
        </button>
      </div>
      <div style="margin-top:14px;">${bodyHtml}</div>
    `;

        modal.appendChild(modalContent);
        document.body.appendChild(modal);

        modalContent.querySelector("#closeModal").addEventListener("click", () => {
            document.body.removeChild(modal);
        });
        modal.addEventListener("click", (e) => {
            if (e.target === modal) document.body.removeChild(modal);
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
              <div style="margin-top:14px; padding:12px; border:1px solid #e5e7eb; border-radius:8px;">
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


    function showProcessorModal(result) {
        if (!result) {
            showModal({
                title: "Processor Result",
                bodyHtml: `<p style="margin:0;">No response yet. Click <strong>Summarize</strong> first.</p>`,
            });
            return;
        }

        const meta = `
      <div style="display:grid; gap:6px; color:#111827;">
        <div><strong>URL:</strong> ${escapeHtml(result.url)}</div>
        <div><strong>Time:</strong> ${result.timestamp.toLocaleString()}</div>
        ${
            result.error
                ? `<div><strong>Status:</strong> <span style="color:#b91c1c;">Error</span></div>`
                : `<div><strong>Status:</strong> ${result.status} (${result.ok ? "OK" : "Not OK"})</div>`
        }
      </div>
    `;

        const body =
            result.error != null
                ? `<pre style="background:#fef2f2; border:1px solid #fecaca; padding:10px; border-radius:8px; overflow:auto; max-height:320px; margin:12px 0 0; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(
                    result.error
                )}</pre>
           <div style="margin-top:10px; color:#374151; font-size:13px; line-height:1.35;">
             If your backend logs the request but the browser shows <em>Failed to fetch</em>, it’s usually:
             <ul style="margin:6px 0 0 18px;">
               <li><strong>CORS</strong> blocked (missing <code>Access-Control-Allow-Origin</code>).</li>
               <li><strong>Mixed content</strong> (page is https, calling http backend).</li>
             </ul>
           </div>`
                : `<pre style="background:#f9fafb; border:1px solid #eee; padding:10px; border-radius:8px; overflow:auto; max-height:320px; margin:12px 0 0; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(
                    typeof result.data === "string"
                        ? result.data
                        : JSON.stringify(result.data, null, 2)
                )}</pre>`;

        showModal({title: "Context Processor Response", bodyHtml: meta + body});
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
            try {
                data = JSON.parse(text);
            } catch {
            }

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

    async function prProcessor(btn) {
        const url = "http://localhost:8000/pullrequest";

        const prevText = btn.textContent;
        btn.disabled = true;
        btn.style.opacity = "0.85";
        btn.style.cursor = "not-allowed";

        try {
            const pageUrl = new URL(window.location.href);
            const res = await originalFetch(url, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    operation: "summarize:engineer",
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
                type: "hello(fetch)",
                status: res.status,
            });

            showProcessorModal(lastProcessorResult);
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
                type: "hello(fetch-error)",
            });

            showProcessorModal(lastProcessorResult);
        } finally {
            btn.disabled = false;
            btn.textContent = prevText;
            btn.style.opacity = "1";
            btn.style.cursor = "pointer";
        }
    }

    function initButtons() {
        const wrapper = document.createElement("div");
        wrapper.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 999999;
      display: flex;
      gap: 10px;
      align-items: center;
    `;

        const smallShadow = `box-shadow: rgba(50, 50, 93, 0.25) 0px 2px 5px -1px, rgba(0, 0, 0, 0.3) 0px 1px 3px -1px;`;

        const summarizeButton = document.createElement("button");
        summarizeButton.textContent = "Summarize";
        summarizeButton.style.cssText = `
      padding: 8px 16px;
      background-color: #10b981;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      ${smallShadow}
      transition: background-color 0.15s ease;
    `;
        summarizeButton.addEventListener("mouseenter", () => (summarizeButton.style.backgroundColor = "#059669"));
        summarizeButton.addEventListener("mouseleave", () => (summarizeButton.style.backgroundColor = "#10b981"));
        summarizeButton.addEventListener("click", () => prProcessor(summarizeButton));

        const apiButton = document.createElement("button");
        apiButton.textContent = "API Data";
        apiButton.style.cssText = `
      padding: 8px 16px;
      background-color: #3b82f6;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      ${smallShadow}
      transition: background-color 0.15s ease;
    `;
        apiButton.addEventListener("mouseenter", () => (apiButton.style.backgroundColor = "#2563eb"));
        apiButton.addEventListener("mouseleave", () => (apiButton.style.backgroundColor = "#3b82f6"));
        apiButton.addEventListener("click", showApiModal);

        wrapper.appendChild(summarizeButton);
        wrapper.appendChild(apiButton);
        document.body.appendChild(wrapper);
    }

    if (document.body) initButtons();
    else window.addEventListener("DOMContentLoaded", initButtons);
})();
