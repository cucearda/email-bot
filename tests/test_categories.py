import pytest

from app.domain.categories import CATEGORY_TO_GMAIL_LABEL, gmail_label_for_category


@pytest.mark.parametrize(
    "category,label",
    [
        ("rfq", "5u/rfq"),
        ("booking_request", "5u/booking-request"),
        ("tracking_inquiry", "5u/tracking"),
        ("documentation", "5u/documentation"),
        ("complaint", "5u/complaint"),
        ("general_inquiry", "5u/general"),
        ("not_relevant", "5u/not-relevant"),
    ],
)
def test_gmail_label_for_category(category: str, label: str) -> None:
    assert gmail_label_for_category(category) == label
    assert CATEGORY_TO_GMAIL_LABEL[category] == label


def test_unknown_category_raises() -> None:
    with pytest.raises(ValueError, match="Unknown category"):
        gmail_label_for_category("not_a_real_category")
