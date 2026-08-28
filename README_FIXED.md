# PDF Mitra Pro — SQLite build

This build removes MongoDB completely and uses a local SQLite database file.

## What was changed

- MongoDB/PyMongo code removed completely.
- SQLite database added as `pdf_mitra.db`.
- Database is created automatically on first start.
- Existing bot-facing `Database()` API is preserved, so handlers/UI do not need a database rewrite.
- PDF quota, AI quota, premium plans, GenKeys, settings, fonts, history, documents, chunks, config and audit logs are stored in SQLite.
- SQLite uses WAL mode, a 30-second busy timeout and atomic transactions for quota/key operations.
- Telegram bot token and AI API keys are loaded from a local `.env` file.
- `.env` is ignored by Git and `.env.example` is included as a safe template.
- `/setaikey` can still store a runtime AI key in the SQLite config table; a key explicitly set in `config.py` takes priority.
- No `pymongo`, `certifi` or MongoDB URI is required; `python-dotenv` is used for `.env` loading.

## Setup

1. Copy `.env.example` to `.env`.
2. Put your Telegram bot token in `TOKEN`.
3. Put your AI API keys in the corresponding variables if needed.
4. Set `OWNER_ID` if needed.
5. Install dependencies: `pip install -r requirements.txt`.
6. Start: `python main.py`.

The first successful start creates `pdf_mitra.db` automatically beside the Python files.

## Important security note

Do not publish `.env` with real bot/API credentials to GitHub. `.env` is ignored by Git; commit only `.env.example`. If a credential has ever been exposed publicly, rotate it immediately.


## Multi-key AI pool
- Each provider can have any number of keys in the SQLite pool (no application-level storage cap).
- `/setaikey` accepts multiple keys, one per line, and auto-detects Gemini, Groq, OpenRouter, or Mistral.
- AI requests use least-recently-used active keys and automatically rotate to another key when a key returns an authentication, permission, or rate-limit failure.
- A key is marked `down` after repeated qualifying failures; it can be re-enabled from **AI Settings → Manage Keys**.
- `MAX_AI_KEY_ATTEMPTS` controls how many pooled keys a single request will try (default: 20). This is a per-request retry cap, not a storage limit.
