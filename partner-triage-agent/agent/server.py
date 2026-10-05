"""
Local web front end for the triage agent.

Run:  python server.py        # then open http://127.0.0.1:8765
"""

import contextlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import EXAMPLE, run

HOST = "127.0.0.1"
PORT = 8765

# run() prints its tool-call trace to stdout; capture it one request at a time.
RUN_LOCK = threading.Lock()

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Partner Triage Agent</title>
<style>
  :root { --bg:#f7f7f5; --card:#fff; --text:#1c1c1a; --muted:#6b6b66; --line:#e2e2dd; --accent:#b4532a; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#191918; --card:#232321; --text:#ececea; --muted:#9c9c95; --line:#363632; --accent:#e08a5f; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  main { max-width:820px; margin:0 auto; padding:32px 16px 64px; }
  h1 { font-size:24px; margin:0 0 4px; }
  p.sub { color:var(--muted); margin:0 0 20px; }
  textarea { width:100%; min-height:170px; padding:12px; border:1px solid var(--line); border-radius:8px;
             background:var(--card); color:var(--text); font:inherit; resize:vertical; }
  button { margin-top:12px; padding:10px 18px; border:0; border-radius:8px; background:var(--accent);
           color:#fff; font:inherit; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.55; cursor:default; }
  textarea.drag { border-color:var(--accent); outline:2px dashed var(--accent); outline-offset:-6px; }
  .upload { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; margin-top:10px; color:var(--muted); font-size:14px; }
  .upload label { padding:6px 12px; border:1px solid var(--line); border-radius:8px; background:var(--card);
                  color:var(--text); cursor:pointer; }
  .upload input { display:none; }
  #status { margin-left:12px; color:var(--muted); }
  section { margin-top:24px; padding:16px; background:var(--card); border:1px solid var(--line); border-radius:8px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 8px; }
  h3 { font-size:15px; margin:16px 0 4px; }
  h3:first-of-type { margin-top:0; }
  pre { margin:0; white-space:pre-wrap; word-break:break-word; font:13px/1.5 ui-monospace, Menlo, monospace; }
  ul { margin:4px 0 0; padding-left:20px; }
  .hidden { display:none; }
</style>
</head>
<body>
<main>
  <h1>Partner Triage Agent</h1>
  <p class="sub">Paste a partner-submitted customer use case, or upload text files, and run the triage.</p>
  <textarea id="use-case"></textarea>
  <div class="upload">
    <label for="files">Upload text files</label>
    <input type="file" id="files" accept=".txt,.md,.markdown,.csv,.json,text/plain" multiple>
    <span id="file-status">or drag files onto the text box. Uploaded text replaces what's in the box.</span>
  </div>
  <div><button id="go">Run triage</button><span id="status"></span></div>
  <section id="trace-box" class="hidden"><h2>Tool calls</h2><pre id="trace"></pre></section>
  <section id="result-box" class="hidden"><h2>Recommendation</h2><div id="result"></div></section>
</main>
<script>
const EXAMPLE = __EXAMPLE__;
const LABELS = {
  recommended_pattern: "Recommended pattern", why: "Why", data_risks: "Data risks",
  complexity_band: "Complexity", biggest_unknown: "Biggest unknown"
};
const $ = id => document.getElementById(id);
$("use-case").value = EXAMPLE;

const MAX_FILE_BYTES = 200 * 1024;

async function loadFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const parts = [], skipped = [];
  for (const f of files) {
    if (f.size > MAX_FILE_BYTES) { skipped.push(f.name + " (over 200 KB)"); continue; }
    const text = (await f.text()).trim();
    if (text.includes("\\u0000")) { skipped.push(f.name + " (not a text file)"); continue; }
    // Label each file when several are combined so the agent can tell them apart.
    parts.push(files.length > 1 ? "--- " + f.name + " ---\\n" + text : text);
  }
  if (parts.length) $("use-case").value = parts.join("\\n\\n");
  const loaded = files.length - skipped.length;
  $("file-status").textContent = "Loaded " + loaded + " file" + (loaded === 1 ? "" : "s") +
    (skipped.length ? ". Skipped: " + skipped.join(", ") : ".");
}

$("files").addEventListener("change", async e => { await loadFiles(e.target.files); e.target.value = ""; });
const ta = $("use-case");
ta.addEventListener("dragover", e => { e.preventDefault(); ta.classList.add("drag"); });
ta.addEventListener("dragleave", () => ta.classList.remove("drag"));
ta.addEventListener("drop", e => { e.preventDefault(); ta.classList.remove("drag"); loadFiles(e.dataTransfer.files); });

function render(text) {
  const box = $("result");
  box.replaceChildren();
  let data;
  try { data = JSON.parse(text.replace(/^```(?:json)?\\s*|\\s*```$/g, "").trim()); } catch (e) {}
  if (!data || typeof data !== "object") {
    const pre = document.createElement("pre"); pre.textContent = text; box.append(pre); return;
  }
  for (const [key, value] of Object.entries(data)) {
    const h = document.createElement("h3"); h.textContent = LABELS[key] || key; box.append(h);
    if (Array.isArray(value)) {
      const ul = document.createElement("ul");
      for (const item of value) { const li = document.createElement("li"); li.textContent = String(item); ul.append(li); }
      box.append(ul);
    } else {
      const p = document.createElement("div");
      p.textContent = typeof value === "string" ? value : JSON.stringify(value);
      box.append(p);
    }
  }
}

$("go").addEventListener("click", async () => {
  const useCase = $("use-case").value.trim();
  if (!useCase) return;
  $("go").disabled = true;
  $("status").textContent = "Running\\u2026 this usually takes 20\\u201360 seconds.";
  $("trace-box").classList.add("hidden");
  $("result-box").classList.add("hidden");
  try {
    const resp = await fetch("/api/triage", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({use_case: useCase})
    });
    const body = await resp.json();
    if (!resp.ok) throw new Error(body.error || resp.statusText);
    $("trace").textContent = body.trace || "(no tool calls)";
    $("trace-box").classList.remove("hidden");
    render(body.result);
    $("result-box").classList.remove("hidden");
    $("status").textContent = "";
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
  } finally {
    $("go").disabled = false;
  }
});
</script>
</body>
</html>
""".replace("__EXAMPLE__", json.dumps(EXAMPLE).replace("</", "<\\/"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/triage":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            use_case = json.loads(self.rfile.read(length))["use_case"].strip()
        except Exception:
            self._json(400, {"error": "expected JSON body with a 'use_case' string"})
            return
        if not use_case:
            self._json(400, {"error": "use_case is empty"})
            return

        buf = io.StringIO()
        try:
            with RUN_LOCK, contextlib.redirect_stdout(buf):
                result = run(use_case)
        except Exception as e:
            self._json(500, {"error": f"{type(e).__name__}: {e}"})
            return
        trace = "\n".join(l for l in buf.getvalue().splitlines() if l.startswith("[turn"))
        self._json(200, {"result": result, "trace": trace})


if __name__ == "__main__":
    print(f"Serving on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
