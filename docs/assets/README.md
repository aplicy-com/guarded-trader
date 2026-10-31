# Images used by the README

| File | What it shows | Source |
|---|---|---|
| `dashboard.png` | Conductor's read-only dashboard, overview page | Screenshot of a local dry-run stack (`make up`), freshly started: principal $100, no trades, one equity snapshot |
| `telegram-halt-flow.png` | `/kill` → confirm → `/status` → `/resume` → confirm | **Mock.** The text is produced by the real `CommandProcessor` against the test fakes; only the chat window is drawn. The chat ID is replaced by `<chat-id>` |
| `architecture.png` | The system diagram | Rendered from the Mermaid block in the top-level `README.md` |
| `social-preview.svg` / `.png` | 1280×640 GitHub social preview | Hand-written SVG; the PNG is rendered from it |

No real chat ID, IP address, account or key appears in any image.

## Regenerating

Needs Docker, `uv`, and Python with Playwright (`pip install playwright && playwright install chromium`).

1. Start the stack with only the three Freqtrade API values filled in `.env` (see the README
   quick start): `make up`. Expected: `make logs` shows `Dry run is enabled`.
2. Produce the chat transcript (no network, no Telegram):
   ```
   mkdir -p /tmp/gt-assets
   cd services/conductor && uv run python ../../scripts/docs_assets/telegram_transcript.py /tmp/gt-assets/telegram.json && cd ../..
   ```
   Expected: a JSON list of messages; `grep -c '<chat-id>' /tmp/gt-assets/telegram.json` prints a number above 0.
3. Render all PNGs: `python scripts/docs_assets/render.py /tmp/gt-assets`.
   It downloads Mermaid 11.4.1 once and refuses to run it if its SHA-256 doesn't match.
   Expected: `rendered: architecture.png, dashboard.png, social-preview.png, telegram-halt-flow.png`.
4. `make down`.

The social preview is uploaded by hand: repository **Settings → General → Social preview →
Edit → Upload an image**, choose `social-preview.png`. GitHub has no API for it.
