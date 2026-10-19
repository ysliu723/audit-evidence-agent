"""What the agent works with: a flagged entry, the case's documents, and the client's master data.

A case is one flagged journal entry with its own folder of documents: the vendor's invoice, the purchase
order, the receiving record, and the vendor's contract when there is one. The agent may read only the
case's own folder. The vendor master, the approval limits, and the paid-invoice register are the client's
records; code reads them, the model never sees them.

Amounts are Decimal (exact money), dates are date objects. Pydantic checks the types when data is loaded.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class DocumentType(StrEnum):
    INVOICE = "INVOICE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    RECEIVING_RECORD = "RECEIVING_RECORD"
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


class DocumentFile(BaseModel):
    """One document in a case's folder: a PDF on disk."""

    document_id: str
    document_type: DocumentType
    title: str
    file: str  # path relative to data/evidence/


class Case(BaseModel):
    case_id: str
    entry: FlaggedEntry
    fiscal_year_end: date
    documents: list[DocumentFile]  # the case's folder; the agent's tools cannot reach anything else


class Vendor(BaseModel):
    """An approved vendor in the client's vendor master."""

    vendor_id: str
    name: str
    tax_id: str
    bank_last4: str


class Approver(BaseModel):
    """Who may approve purchase orders, and up to what amount."""

    name: str
    title: str
    limit: Decimal


class PaidInvoice(BaseModel):
    """An invoice the client has already paid, and the entry that paid it."""

    vendor_name: str
    invoice_number: str
    amount: Decimal
    paid_by_entry_id: str


class GroundTruth(BaseModel):
    """What the evaluation checks against: the expected result of each of the eight checks."""

    case_id: str
    split: str  # "dev" (used while building the prompts) or "heldout" (scored once, at the end)
    scenario: str
    layout: str  # the invoice layout: A and B are familiar, C, D, and E appear only in held-out cases
    unseen_layout: bool
    expected: dict[str, str]  # check code -> PASS, FAIL, or UNABLE (when the evidence cannot be read)
    facts: dict  # the true values printed on the documents, for the oracle extractor and for diagnosis
