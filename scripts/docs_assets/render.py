"""Render the PNGs in docs/assets/ with headless Chromium (Playwright).

Usage (from the repo root, see docs/assets/README.md for the full sequence):
    python scripts/docs_assets/render.py <workdir>

<workdir> must hold telegram.json (from telegram_transcript.py). Mermaid is downloaded
once into <workdir>, pinned by version and SHA-256. The dashboard shot needs a running
local dry-run stack (`make up`) on 127.0.0.1:8000. Set CHROME to use a specific browser
binary instead of Playwright's bundled Chromium.
"""

import hashlib
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
WORK = Path(sys.argv[1])
ASSETS = REPO / "docs/assets"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
MERMAID_SHA256 = "a43bc1afd446f9c4cc66ac5dd45d02e8d65e26fc5344ec0ef787f88d6ddb6f9e"


def mermaid_js() -> str:
    path = WORK / "mermaid.min.js"
    if not path.exists():
        urllib.request.urlretrieve(MERMAID_URL, path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != MERMAID_SHA256:
        sys.exit(f"{path}: SHA-256 mismatch, refusing to run it")
    return data.decode()


def telegram_html() -> str:
    chat = json.loads((WORK / "telegram.json").read_text())
    rows = []
    for m in chat:
        side = "me" if m["from"] == "operator" else "bot"
        body = re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(m["text"]))
        rows.append(
            f'<div class="msg {side}"><pre>{body}</pre><span class="t">{m["at"]}</span></div>'
        )
    return f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;background:#0e1621;font:15px -apple-system,'Segoe UI',Arial,sans-serif;color:#e9eef3}}
.wrap{{width:560px;margin:0 auto;padding-bottom:16px}}
header{{background:#17212b;padding:14px 18px;display:flex;gap:12px;align-items:center}}
.av{{width:40px;height:40px;border-radius:50%;background:#2dd4bf;color:#0b1220;font-weight:800;display:grid;place-items:center}}
header b{{display:block}} header small{{color:#7f91a4}}
.note{{margin:12px 18px;padding:8px 12px;border-radius:8px;background:#2b2412;color:#fbbf24;font-size:12.5px}}
.msg{{max-width:78%;margin:6px 14px;padding:8px 12px 18px;border-radius:12px;position:relative;clear:both}}
.bot{{background:#182533;float:left;border-bottom-left-radius:4px}}
.me{{background:#2b5278;float:right;border-bottom-right-radius:4px}}
pre{{margin:0;white-space:pre-wrap;font:14px/1.4 ui-monospace,'SF Mono',Menlo,monospace}}
code{{background:#0e1621;padding:1px 4px;border-radius:4px;color:#5eead4}}
.t{{position:absolute;right:10px;bottom:4px;font-size:11px;color:#7f91a4}}
.end{{clear:both}}
</style><div class="wrap"><header><div class="av">C</div><div><b>Conductor</b>
<small>bot · dry-run</small></div></header>
<div class="note">Mock. Replies are produced by the real CommandProcessor against test fakes;
the chat ID is replaced by &lt;chat-id&gt;. Writes need <code>yes &lt;code&gt;</code> within 60 s.</div>
{"".join(rows)}<div class="end"></div></div>"""


def mermaid_html() -> str:
    src = re.search(
        r"```mermaid\n(.*?)```", (REPO / "README.md").read_text(), re.DOTALL
    ).group(1)
    return f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;background:#fff}} #d{{display:inline-block;padding:24px}}</style>
<div id="d"><pre class="mermaid">{html.escape(src)}</pre></div>
<script>{mermaid_js()}</script><script>
mermaid.initialize({{startOnLoad:false,theme:'neutral',flowchart:{{htmlLabels:true,useMaxWidth:false,
  wrappingWidth:320,subGraphTitleMargin:{{top:6,bottom:30}}}},themeVariables:{{fontSize:'18px'}}}});
mermaid.run().then(()=>document.body.dataset.done='1');</script>"""


with sync_playwright() as p:
    chrome = os.environ.get("CHROME")
    b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()

    pg = b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
    pg.goto("http://127.0.0.1:8000/")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(2500)
    pg.screenshot(path=ASSETS / "dashboard.png", full_page=True)

    pg = b.new_page(viewport={"width": 560, "height": 400}, device_scale_factor=2)
    pg.set_content(telegram_html())
    pg.screenshot(path=ASSETS / "telegram-halt-flow.png", full_page=True)

    pg = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
    pg.set_content(mermaid_html())
    pg.wait_for_selector("body[data-done]")
    pg.locator("#d").screenshot(path=ASSETS / "architecture.png")

    pg = b.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
    pg.goto((ASSETS / "social-preview.svg").as_uri())
    pg.screenshot(path=ASSETS / "social-preview.png")
    b.close()
print("rendered:", ", ".join(sorted(f.name for f in ASSETS.glob("*.png"))))
