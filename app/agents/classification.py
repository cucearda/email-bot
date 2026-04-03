"""Agno agent: classify inbound logistics email (LLM 1)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.anthropic import Claude

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.domain.categories import EMAIL_CATEGORIES, RFQ_FIELD_KEYS


class ClassificationOutput(BaseModel):
    """Structured classification for one inbound email."""

    category: str = Field(
        description=f"Exactly one of: {', '.join(EMAIL_CATEGORIES)}",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "If category is rfq: which of origin, destination, cargo_type, weight, dates "
            "are missing or too vague; empty for other categories"
        ),
    )


CLASSIFIER_INSTRUCTIONS = [
    "You classify emails for a freight forwarding / logistics shared inbox.",
    "Choose exactly one category from the allowed list.",
    "If the email is an RFQ (rate / quote request), list missing_fields from: "
    + ", ".join(RFQ_FIELD_KEYS)
    + " — only fields that are absent or unusably vague.",
    "If the email is not an RFQ, missing_fields must be empty.",
]


@lru_cache(maxsize=1)
def build_classification_agent() -> Agent:
    s = get_settings()
    return Agent(
        model=Claude(id=s.agno_claude_model, api_key=s.anthropic_api_key or None),
        description="Logistics inbox email classifier.",
        instructions=CLASSIFIER_INSTRUCTIONS,
        output_schema=ClassificationOutput,
    )


def classify_email_text(*, thread_context: str, current_email: str, settings: Settings | None = None) -> ClassificationOutput:
    agent = build_classification_agent()
    user = (
        "Thread context (previous messages in this conversation, oldest first):\n"
        f"{thread_context or '(none)'}\n\n"
        "---\nCurrent email to classify:\n"
        f"{current_email}"
    )
    out = agent.run(user)
    if out.content is None:
        raise RuntimeError("Classifier returned no structured content")
    if isinstance(out.content, ClassificationOutput):
        return out.content
    if isinstance(out.content, BaseModel):
        return ClassificationOutput.model_validate(out.content.model_dump())
    if isinstance(out.content, dict):
        return ClassificationOutput.model_validate(out.content)
    return ClassificationOutput.model_validate_json(str(out.content))
