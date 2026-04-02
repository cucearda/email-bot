# Logistics Inbox Automator

Backend service from [`CHALLENGE.md`](CHALLENGE.md): Gmail polling (via cron + CLI), Agno + Claude classification and reply drafting, SQLite persistence, Dramatiq actors (in-memory broker today).

## Setup

1. Python 3.12+

2. Create a virtualenv and install:

   ```bash
   pip install -e ".[dev]"
   ```

3. Environment (optional file `.env`):

   - `ANTHROPIC_API_KEY` — required for classification and reply agents.
   - `GMAIL_CREDENTIALS_PATH` — default `./credentials.json` (OAuth client secret JSON from Google Cloud).
   - `GMAIL_TOKEN_PATH` — default `./token.json` (written by `gmail-auth`).
   - `DATABASE_URL` — default `sqlite:///./inbox_automator.db`.
   - `AGNO_CLAUDE_MODEL` — default `claude-sonnet-4-5-20250929` (structured outputs).

4. Gmail OAuth (once):

   ```bash
   python -m app.cli gmail-auth
   ```

   Use the downloaded OAuth client JSON path as `credentials.json` (or set `GMAIL_CREDENTIALS_PATH`).

## Run

**API** (read-only sessions + health):

```bash
uvicorn app.main:app --reload
```

- `GET /health`
- `GET /sessions`
- `GET /sessions/{id}`

**Cron** — processes unread inbox mail **in-process** (no Redis, no separate worker):

```bash
* * * * * cd /path/to/project && /path/to/venv/bin/python -m app.cli poll-inbox
```

### Future: Redis + background workers

To scale out, switch `app/workers/broker_setup.py` to `RedisBroker`, change `_enqueue_draft` in `app/service/pipeline.py` to use `draft_and_send_reply.send(email_id)`, add the `redis` extra to `pyproject.toml`, run `dramatiq app.workers.tasks`, and have cron enqueue via `classify_inbound.send(...)` instead of calling `run_classify_inbound` directly.

## Project layout

- `app/agents/` — Agno agents (classification + reply).
- `app/integrations/gmail/` — Gmail API client.
- `app/workers/tasks.py` — Dramatiq actors (for future Redis).
- `app/service/pipeline.py` — shared pipeline logic.

## Security

Do not commit `credentials.json`, `token.json`, `.env`, or `client_secret*.json`. They are listed in `.gitignore`.
