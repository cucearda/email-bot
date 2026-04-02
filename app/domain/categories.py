from typing import Literal

EmailCategory = Literal[
    "rfq",
    "booking_request",
    "tracking_inquiry",
    "documentation",
    "complaint",
    "general_inquiry",
    "not_relevant",
]

EMAIL_CATEGORIES: tuple[str, ...] = (
    "rfq",
    "booking_request",
    "tracking_inquiry",
    "documentation",
    "complaint",
    "general_inquiry",
    "not_relevant",
)

# CHALLENGE.md — nested labels under 5u/
CATEGORY_TO_GMAIL_LABEL: dict[str, str] = {
    "rfq": "5u/rfq",
    "booking_request": "5u/booking-request",
    "tracking_inquiry": "5u/tracking",
    "documentation": "5u/documentation",
    "complaint": "5u/complaint",
    "general_inquiry": "5u/general",
    "not_relevant": "5u/not-relevant",
}

RFQ_FIELD_KEYS: tuple[str, ...] = (
    "origin",
    "destination",
    "cargo_type",
    "weight",
    "dates",
)


def gmail_label_for_category(category: str) -> str:
    if category not in CATEGORY_TO_GMAIL_LABEL:
        raise ValueError(f"Unknown category: {category}")
    return CATEGORY_TO_GMAIL_LABEL[category]
