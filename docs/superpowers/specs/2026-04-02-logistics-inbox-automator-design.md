# Logistics Inbox Automator — Design Spec

**Date:** 2026-04-02  
**Source:** `CHALLENGE.md`  
**Scope:** Interview / ~60-minute vertical slice (Approach A): core requirements only; bonus UI and Docker out of scope.

---

## 1. Goals

Build a backend service that:

1. Processes new unread mail from a shared Gmail inbox.
2. Classifies each email into exactly one of seven categories (see §3).
3. Applies the matching Gmail nested label under `5u/`.
4. Sends a thread reply (except `not_relevant`) that is professional, references the original subject, and stays in the same Gmail thread.
5. Treats each Gmail thread as one **session**; follow-ups reuse session context from persisted history.
6. Persists classifications and messages; exposes query APIs for sessions and threads.

---

## 2. Stack (constraints)

| Area | Choice |
|------|--------|
| API | FastAPI |
| Agent framework | Agno |
| LLM | Claude (via Agno) |
| Database | SQLite |
| Background work | Dramatiq with **two actors**; smallest viable broker for local demo (e.g. in-memory / stub). Document upgrade path to **Redis** for durable, multi-process queues. |
| Gmail | Gmail API, OAuth2 (`credentials.json` + stored refresh token). |

---

## 3. Classification categories

Exactly one label per inbound message:

| Category | Gmail label | Auto-reply |
|----------|-------------|------------|
| `rfq` | `5u/rfq` | Yes; acknowledge + ask for missing RFQ details if any |
| `booking_request` | `5u/booking-request` | Yes |
| `tracking_inquiry` | `5u/tracking` | Yes |
| `documentation` | `5u/documentation` | Yes |
| `complaint` | `5u/complaint` | Yes |
| `general_inquiry` | `5u/general` | Yes |
| `not_relevant` | `5u/not-relevant` | No |

**RFQ:** Classification step must detect missing pieces among: origin, destination, cargo type, weight, dates — persisted for the reply step.

---

## 4. Architecture overview

- **FastAPI:** Health, session query APIs (`GET /sessions`, `GET /sessions/{id}`), optional OAuth callback if using a web OAuth flow.
- **SQLite:** Sessions (by `gmail_thread_id`), emails, classifications, reply/outbound records, processing status for observability and retries.
- **Gmail integration module:** List/fetch messages, create/apply labels, send replies in-thread.
- **Agno:** Two separate agent definitions (or one module with two entrypoints) backing the two LLM calls.
- **Dramatiq:** Two actors with a thin **cron-driven CLI** that lists work and enqueues actor 1 (see §6).

---

## 5. Scheduling: cron, not HTTP poll

- **Do not** expose a public/internal HTTP route whose purpose is “poll inbox now.”
- **Host cron** (or equivalent) runs a **CLI entrypoint**, e.g. `python -m app.cli poll-inbox`, which:
  - Lists candidate unread messages (per Gmail query agreed in implementation),
  - For each message not yet fully processed, enqueues **Actor 1** with a stable identifier (`gmail_message_id` or internal id after ingest).

Workers run separately (`dramatiq` CLI) per project conventions.

---

## 6. Two-actor pipeline

### Actor 1 — `classify_inbound` (name exact in code TBD)

**Input:** Gmail message id (and/or internal email id after optional ingest row).

**Steps:**

1. Idempotency: if this message already has a **completed** classification row, exit (or follow retry policy).
2. Ensure **session** row exists for `threadId`; ensure **email** row exists with metadata and body/snippet.
3. Load prior messages in thread from DB for context (and fetch from Gmail if implementation chooses to supplement).
4. **LLM 1 (Agno + Claude):** structured output — `category`, and for `rfq`, `missing_fields` (subset of origin, destination, cargo type, weight, dates).
5. **Persist classification immediately** (observability and checkpoint before side effects).
6. **Apply Gmail label** for `category` under `5u/` (create label hierarchy on first use if needed).
7. Enqueue **Actor 2** with `email_id` (or equivalent primary key).

**On failure:** Persist error state on the email or a job row where useful; do not enqueue Actor 2 until classification + label succeed (implementation defines retry semantics).

### Actor 2 — `draft_and_send_reply`

**Input:** `email_id` (FK to inbound message with classification already stored).

**Steps:**

1. Load email, session, thread context, classification (`category`, `missing_fields`).
2. If `category == not_relevant`: **do not send** (challenge). **LLM 2:** either **skip** the model call and persist `reply_skipped_reason` (recommended for cost), or run a **minimal structured** Agno call (e.g. `{ "send": false }`) if you need a uniform “two model invocations per message” story for demos.
3. Otherwise **LLM 2 (Agno + Claude):** draft body — professional freight tone, references original **subject**, uses RFQ missing-field list when category is `rfq`.
4. Persist draft text (and optionally metadata) before send.
5. **Send** via Gmail as **reply in same thread** (correct headers / Gmail thread semantics per API).
6. Persist outbound record / Gmail message id; mark processing complete.

**On failure:** Classification and label remain visible in DB; reply step can be retried without re-classifying (idempotent send flags required).

---

## 7. Data model (SQLite)

Minimum entities:

- **`sessions`:** `id`, `gmail_thread_id` (unique), timestamps; optional denormalized `latest_category` for listing.
- **`emails`:** `id`, `session_id`, `gmail_message_id` (unique), `thread_id`, from/subject/body or snippet, `received_at`, processing/error fields.
- **`classifications`:** `id`, `email_id`, `category`, `missing_rfq_fields` (JSON/text), optional `model_raw`, `created_at`.
- **Outbound / reply tracking:** store draft, sent message id, `sent_at`, skip reason — either dedicated table or columns on `emails` with clear naming.

**Thread = session:** Every inbound message is tied to `gmail_thread_id` for continuity on follow-ups.

---

## 8. APIs (FastAPI)

- `GET /sessions` — list sessions (pagination optional).
- `GET /sessions/{id}` — session detail with ordered messages and linked classification (and reply status).

No poll trigger endpoint (§5).

---

## 9. Error handling and idempotency

- **Unique constraint** on `gmail_message_id` to prevent duplicate processing.
- **Per-message isolation:** failure on one message should not abort the entire cron batch (implementation uses try/except and logging per message).
- **Double-send prevention:** after successful send, flag stored; retries must not send again.
- **Gmail 429:** optional simple backoff (time permitting).

---

## 10. Testing (slice)

- Unit tests: category → **label name** mapping; parsing/normalization of structured LLM output (mocked).
- Optional: mock Gmail client for one integration-style test of the pipeline orchestration.

---

## 11. Open decisions for implementation plan

- Exact Gmail query for “new unread” vs. incremental `history` API (slice may use `is:unread` + processed flag).
- OAuth: desktop/installed flow script vs. FastAPI callback — either acceptable if token is persisted securely.
- Exact Agno API for structured outputs (plan will follow current Agno docs).

---

## 12. Summary

**Cron → CLI → enqueue Actor 1.** Actor 1 classifies, **writes DB**, applies label, enqueues Actor 2. Actor 2 drafts (LLM) and sends except for `not_relevant`. FastAPI exposes **read** APIs for sessions/threads. Broker starts minimal; **Redis** documented as production upgrade.
