# Live Coding Challenge: The Logistics Inbox Automator

**Duration:** 60 minutes (+5 for explanaiton)

---

## Context

You're building a backend service for a freight forwarding company. Emails arrive in a shared Gmail inbox — quote requests, booking requests, tracking questions, complaints, etc. Today, a human reads every email and manually responds. We want to automate this.

## Your Task

Build a **Gmail inbox automation service** that:

1. **Polls** a Gmail inbox for new unread emails
2. **Classifies** each email's intent using an AI agent
3. **Applies a Gmail label** matching the classification
4. **Sends an auto-reply** with an appropriate initial response based on the category
5. **Tracks conversation threads** — if someone replies to our auto-reply, it should be linked to the same session (not start a new one)

## Technical Constraints

| Requirement               | Spec                                                 |
| ------------------------- | ---------------------------------------------------- |
| **Framework**             | FastAPI                                              |
| **AI Agent**              | Agno framework                                       |
| **LLM**                   | Claude (via Agno)                                    |
| **Database**              | SQLite                                               |
| **Background Processing** | Dramatiq worker (preferred) — or async processing    |
| **Gmail**                 | Real Gmail API — OAuth2 credentials provided         |

## Classification Categories

The system must classify each email into exactly one of these:

| Category          | Gmail Label          | Auto-Reply?                                          |
| ----------------- | -------------------- | ---------------------------------------------------- |
| `rfq`             | `5u/rfq`             | Yes — acknowledge + ask for missing details if any   |
| `booking_request` | `5u/booking-request` | Yes — confirm receipt, say we're processing          |
| `tracking_inquiry`| `5u/tracking`        | Yes — acknowledge, say we're investigating           |
| `documentation`   | `5u/documentation`   | Yes — confirm docs received                          |
| `complaint`       | `5u/complaint`       | Yes — apologize, promise follow-up                   |
| `general_inquiry` | `5u/general`         | Yes — acknowledge receipt                            |
| `not_relevant`    | `5u/not-relevant`    | No reply                                             |

## Business Rules

### Classification
- Every incoming email must be classified into one of the categories above
- For RFQ emails: the system should detect if key information is missing (origin, destination, cargo type, weight, dates) and ask for it in the reply
- Classification results should be persisted

### Auto-Replies
- Replies must be professional and freight-industry appropriate
- Replies must reference the sender's original subject
- Replies must be sent as a reply within the same Gmail thread (not a new separate email)
- No reply should be sent for `not_relevant` emails

### Session/Thread Tracking
- Emails in the same Gmail thread belong to the same session
- When a follow-up arrives on an existing thread, the system should have context of previous messages when processing it
- Sessions and their emails should be queryable via API

## Provided to You

1. Gmail OAuth2 credentials (`credentials.json`)
2. Anthropic API key (will be shared with you)
3. This document

You are responsible for initializing the project from scratch — tooling, dependencies, project structure, everything.

## Bonus (If Time Permits)

- Build a simple UI to visualize sessions. Anything works — plain HTML served from FastAPI, React, Next.js. Show the list of sessions with their classification and allow drilling into the email thread.
- Conterization
---

**Timer starts when you open the project.**
