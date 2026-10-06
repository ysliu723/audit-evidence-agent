"""Taking a flagged entry straight from the Journal Entry Risk Platform.

Its API returns an entry from GET /entries/{id}. This turns that JSON into
the FlaggedEntry the agent works on, so a HIGH entry found by the risk
platform can be vouched without retyping anything.
"""

from decimal import Decimal

from app.domain import FlaggedEntry


def entry_from_risk_platform(detail: dict) -> FlaggedEntry:
    lines = detail["lines"]
    vendor = next((line["vendor"] for line in lines if line.get("vendor")), None)
    if vendor is None:
        raise ValueError("the entry names no vendor on any line, so there is no vendor invoice to look for")
    expense_line = next(line for line in lines if Decimal(str(line["debit"])) > 0)
    return FlaggedEntry(
        entry_id=detail["entry_id"],
        posting_date=detail["posting_date"],
        description=detail["description"],
        amount=Decimal(str(detail["amount"])),
        currency=detail.get("currency", "USD"),
        vendor=vendor,
        account_number=expense_line["account_number"],
        prepared_by=detail["prepared_by"],
        approved_by=detail.get("approved_by"),
        rule_codes=detail.get("rule_codes", []),
    )
