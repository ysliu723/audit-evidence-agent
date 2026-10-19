"""Confirming that an extracted value really comes from the document, in the role it was given.

A citation is accepted only if:
1. the page exists in the cited document, which must be in the case's folder,
2. the quote appears on that page (ignoring case and extra spaces),
3. the quote is not text addressed to automated reviewers (see integrity.py),
4. the value can be read from the quote (an amount, date, quantity, or name in it equals the value), and
5. for an amount with a role, the quote's own label fits the role: a total due must be labeled as a total
   (and not as a subtotal), a subtotal as a subtotal, a tax as a tax.

A value that fails is never used by the checks; the check that needs it reports UNABLE and a person looks.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.evidence import CaseFolder
from app.extraction import Cited
from app.integrity import suspicious_lines
from app.parsing import all_amounts, all_dates, normalize

SUBTOTAL_LABEL = re.compile(r"\b(sub-?total|sub total|net amount|goods total|before tax|amount before tax)\b", re.I)
TOTAL_LABEL = re.compile(r"\b(total|amount payable|amount due|balance due|please pay)\b", re.I)
TAX_LABEL = re.compile(r"\b(tax|vat|gst)\b", re.I)
ROLES = {
    "total_due": (lambda q: bool(TOTAL_LABEL.search(q)) and not SUBTOTAL_LABEL.search(q),
                  "is not labeled as the total due"),
    "subtotal": (lambda q: bool(SUBTOTAL_LABEL.search(q)), "is not labeled as a subtotal"),
    "tax": (lambda q: bool(TAX_LABEL.search(q)) and not SUBTOTAL_LABEL.search(q), "is not labeled as tax"),
    "po_total": (lambda q: bool(TOTAL_LABEL.search(q)), "is not labeled as the order total"),
}


def citation_problem(folder: CaseFolder, document_id: str, cited: Cited, kind: str = "text",
                     role: str | None = None) -> str | None:
    """None if the citation holds up, otherwise what is wrong. kind: text, amount, date, quantity, or last4."""
    page_text = folder.page_text(document_id, cited.page)
    if page_text is None:
        return f"page {cited.page} of {document_id} does not exist in this case's documents"
    quote = normalize(cited.quote)
    if not quote or quote not in normalize(page_text):
        return f"the quote does not appear on page {cited.page} of {document_id}"
    for line in suspicious_lines(folder, document_id):
        if quote in normalize(line) or normalize(line) in quote:
            return "the quote comes from text addressed to automated reviewers, not from the document's content"
    if kind == "amount":
        try:
            value = Decimal(cited.value)
        except InvalidOperation:
            return f"{cited.value!r} is not an amount"
        if value not in all_amounts(cited.quote):
            return f"the quote does not show the amount {cited.value}"
        if role in ROLES and not ROLES[role][0](cited.quote):
            return f"the quoted amount {ROLES[role][1]}"
    elif kind == "date":
        try:
            value = date.fromisoformat(cited.value)
        except ValueError:
            return f"{cited.value!r} is not a date in the form YYYY-MM-DD"
        if value not in all_dates(cited.quote):
            return f"the quote does not show the date {cited.value}"
    elif kind == "quantity":
        if not re.fullmatch(r"\d+", cited.value.strip()):
            return f"{cited.value!r} is not a whole quantity"
        if not re.search(rf"(?<![\d.,]){int(cited.value)}(?![\d.,]\d)", cited.quote):
            return f"the quote does not show the quantity {cited.value}"
    elif kind == "last4":
        if not re.fullmatch(r"\d{4}", cited.value.strip()):
            return f"{cited.value!r} is not the last four digits of an account"
        if not re.search(rf"{cited.value.strip()}(?!\d)", cited.quote):
            return f"the quote does not show an account ending {cited.value}"
    elif normalize(cited.value) not in quote:
        return f"the quote does not contain {cited.value!r}"
    return None


# How each extracted field is verified: (kind, role). Used to check a whole submission at once.
INVOICE_FIELDS = {"vendor_name": ("text", None), "tax_id": ("text", None), "invoice_number": ("text", None),
                  "invoice_date": ("date", None), "po_number": ("text", None), "bank_last4": ("last4", None),
                  "subtotal": ("amount", "subtotal"), "tax": ("amount", "tax"), "total_due": ("amount", "total_due")}
INVOICE_LINE = {"description": ("text", None), "quantity": ("quantity", None), "unit_price": ("amount", None),
                "amount": ("amount", None)}
PO_FIELDS = {"po_number": ("text", None), "po_date": ("date", None), "vendor_name": ("text", None),
             "approved_by": ("text", None), "po_total": ("amount", "po_total")}
PO_LINE = {"description": ("text", None), "quantity": ("quantity", None), "unit_price": ("amount", None)}
RR_FIELDS = {"receipt_number": ("text", None), "po_number": ("text", None), "received_date": ("date", None)}
RR_LINE = {"description": ("text", None), "quantity_received": ("quantity", None)}
CONTRACT_FIELDS = {"vendor_name": ("text", None), "term_start": ("date", None), "term_end": ("date", None)}
SECTIONS = {"invoice": ("INVOICE", INVOICE_FIELDS, INVOICE_LINE), "purchase_order": ("PURCHASE_ORDER", PO_FIELDS, PO_LINE),
            "receiving_record": ("RECEIVING_RECORD", RR_FIELDS, RR_LINE), "contract": ("CONTRACT", CONTRACT_FIELDS, None)}


def findings_problems(folder: CaseFolder, findings) -> dict[str, str]:
    """Every citation in a submission that does not hold up, keyed by its path, e.g. 'invoice.lines[2].unit_price'."""
    problems: dict[str, str] = {}
    for section, (document_type, fields, line_fields) in SECTIONS.items():
        document = getattr(findings, section)
        if document is None:
            continue
        stored = folder.documents.get(document.document_id)
        if stored is None:
            problems[f"{section}.document_id"] = f"{document.document_id} is not one of this case's documents"
            continue
        if str(stored.document_type) != document_type:
            problems[f"{section}.document_id"] = f"{document.document_id} is a {stored.document_type}, not a {document_type}"
            continue
        for name, (kind, role) in fields.items():
            cited = getattr(document, name, None)
            if cited is not None and (problem := citation_problem(folder, document.document_id, cited, kind, role)):
                problems[f"{section}.{name}"] = problem
        for n, line in enumerate(getattr(document, "lines", []) if line_fields else [], start=1):
            for name, (kind, role) in line_fields.items():
                problem = citation_problem(folder, document.document_id, getattr(line, name), kind, role)
                if problem:
                    problems[f"{section}.lines[{n}].{name}"] = problem
    return problems
