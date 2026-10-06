"""Confirming that an extracted value really comes from the document.

A citation is accepted only if:
1. the page exists in the cited document,
2. the quote appears on that page (ignoring case and extra spaces),
3. the quote is not text addressed to automated reviewers (see integrity.py), and
4. the value can be read from the quote (an amount or date in it equals the value).

A value that fails is never used by the checks: the check that needs it
reports UNABLE instead, and a person has to look.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from app.evidence import EvidenceStore
from app.extraction import Cited
from app.integrity import suspicious_lines
from app.parsing import all_amounts, all_dates, normalize


def citation_problem(store: EvidenceStore, document_id: str, cited: Cited, kind: str = "text") -> str | None:
    """None if the citation holds up, otherwise what is wrong with it. `kind`: text, amount, or date."""
    page_text = store.page_text(document_id, cited.page)
    if page_text is None:
        return f"page {cited.page} does not exist in {document_id}"
    quote = normalize(cited.quote)
    if not quote or quote not in normalize(page_text):
        return f"the quote does not appear on page {cited.page} of {document_id}"
    for line in suspicious_lines(store.documents[document_id]):
        if quote in normalize(line) or normalize(line) in quote:
            return "the quote comes from text addressed to automated reviewers, not from the invoice itself"
    if kind == "amount":
        try:
            value = Decimal(cited.value)
        except InvalidOperation:
            return f"{cited.value!r} is not an amount"
        if value not in all_amounts(cited.quote):
            return f"the quote does not show the amount {cited.value}"
    elif kind == "date":
        try:
            value = date.fromisoformat(cited.value)
        except ValueError:
            return f"{cited.value!r} is not a date in the form YYYY-MM-DD"
        if value not in all_dates(cited.quote):
            return f"the quote does not show the date {cited.value}"
    elif normalize(cited.value) not in quote:
        return f"the quote does not contain {cited.value!r}"
    return None
