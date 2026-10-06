"""What the agent works with: a flagged entry, the client's documents, and the vendor master.

Amounts are Decimal (exact money), dates are date objects. Pydantic checks
the types when data is loaded from JSON or CSV.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class ServiceCategory(StrEnum):
    TAX_ADVISORY = "TAX_ADVISORY"
    IT_CONSULTING = "IT_CONSULTING"
    MARKETING = "MARKETING"
    LEGAL = "LEGAL"
    OTHER = "OTHER"


class DocumentType(StrEnum):
    INVOICE = "INVOICE"
    CONTRACT = "CONTRACT"


class FlaggedEntry(BaseModel):
    """A journal entry the risk platform ranked for review, in the shape the agent receives it."""

    entry_id: str
    posting_date: date
    description: str
    amount: Decimal
    currency: str = "USD"
    vendor: str
    account_number: str
    prepared_by: str
    approved_by: str | None = None
    rule_codes: list[str] = []  # why the risk platform flagged it


class Document(BaseModel):
    """One document in the client's evidence store. Pages are plain text."""

    document_id: str
    document_type: DocumentType
    vendor_name: str  # as printed on the document
    title: str
    pages: list[str]


class Vendor(BaseModel):
    """An approved vendor in the client's vendor master."""

    vendor_id: str
    name: str
    tax_id: str
    bank_last4: str
    category: ServiceCategory


class PaidInvoice(BaseModel):
    """An invoice the client has already paid, and the entry that paid it."""

    vendor_name: str
    invoice_number: str
    amount: Decimal
    paid_by_entry_id: str


class Case(BaseModel):
    """A flagged entry to vouch, with the answers the evaluation checks against."""

    case_id: str
    entry: FlaggedEntry
    fiscal_year_end: date


class GroundTruth(BaseModel):
    case_id: str
    scenario: str
    template: str | None  # which invoice layout the support uses (A, B, C), if any
    support_document_id: str | None
    contract_document_id: str | None
    expected_status: str
    expected_failures: list[str]  # check codes that must fail
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    total_amount: Decimal | None = None
    bank_last4: str | None = None
    service_category: ServiceCategory | None = None
