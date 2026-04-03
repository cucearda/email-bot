"""Agno agent: draft auto-reply (LLM 2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.anthropic import Claude

from functools import lru_cache

from app.core.config import Settings, get_settings


class ReplyDraftOutput(BaseModel):
    body: str = Field(description="Plain-text email body only, no subject line")


REPLY_INSTRUCTIONS = [
    "You write short, professional auto-replies for a freight forwarding company.",
    "Use clear business English. Be courteous and competent.",
    "The reply must explicitly reference the customer's original subject line (quote it naturally).",
    "Do not invent specific rates, tracking numbers, or legal commitments.",
    "If RFQ details are missing, politely ask only for the listed missing items.",
]


@lru_cache(maxsize=1)
def build_reply_agent() -> Agent:
    s = get_settings()
    return Agent(
        model=Claude(id=s.agno_claude_model, api_key=s.anthropic_api_key or None),
        description="Logistics inbox auto-reply writer.",
        instructions=REPLY_INSTRUCTIONS,
        output_schema=ReplyDraftOutput,
    )


def draft_reply(
    *,
    category: str,
    subject: str,
    customer_body: str,
    missing_rfq_fields: list[str],
    thread_context: str,
    settings: Settings | None = None,
) -> str:
    agent = build_reply_agent()
    mf = ", ".join(missing_rfq_fields) if missing_rfq_fields else "(none — sufficient detail)"
    user = (
        f"Category (already decided): {category}\n"
        f"Original subject: {subject}\n"
        f"Missing RFQ fields to ask for (if category is rfq): {mf}\n\n"
        "Thread context:\n"
        f"{thread_context or '(none)'}\n\n"
        "Customer message:\n"
        f"{customer_body}\n\n"
        "Write the reply body only."
    )
    out = agent.run(user)
    if out.content is None:
        raise RuntimeError("Reply agent returned no structured content")
    if isinstance(out.content, ReplyDraftOutput):
        return out.content.body.strip()
    if hasattr(out.content, "body"):
        return str(getattr(out.content, "body")).strip()
    if isinstance(out.content, dict):
        return ReplyDraftOutput.model_validate(out.content).body.strip()
    return ReplyDraftOutput.model_validate_json(str(out.content)).body.strip()
