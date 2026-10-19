"""What an extractor (Claude, the template baseline, or the oracle) hands to the checks.

Every value carries the page and the exact words it came from, so code can confirm it appears in the
document before trusting it. Amounts are labeled by their role: an invoice prints a subtotal, a tax, and
a total due, and a quote that really is on the page can still be the wrong amount (a subtotal reported as
the total). Code checks that the quote's own label matches the role.
"""

from pydantic import BaseModel, ConfigDict, Field


class Cited(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(description="The value, normalized: amounts like 1234.56, dates like 2026-11-14, "
                                   "quantities like 12, bank accounts as the last four digits")
    page: int = Field(description="Page number in the document, starting at 1")
    quote: str = Field(description="The exact line from that page the value was read from, character for character")


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Cited
    quantity: Cited
    unit_price: Cited
    amount: Cited = Field(description="The line's amount as printed")


class InvoiceFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    vendor_name: Cited
    tax_id: Cited | None = Field(description="The vendor's tax ID, if printed")
    invoice_number: Cited
    invoice_date: Cited
    po_number: Cited | None = Field(description="The purchase order number the invoice refers to, if any")
    bank_last4: Cited | None = Field(description="Last four digits of the remit-to bank account, if printed")
    lines: list[InvoiceLine] = Field(description="Every line item, across all pages")
    subtotal: Cited | None = Field(description="The amount before tax, labeled as such on the invoice")
    tax: Cited | None = Field(description="The tax amount, labeled as tax")
    total_due: Cited = Field(description="The final amount to pay, labeled total / amount payable / balance due")


class PurchaseOrderLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Cited
    quantity: Cited
    unit_price: Cited


class PurchaseOrderFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    po_number: Cited
    po_date: Cited
    vendor_name: Cited
    approved_by: Cited = Field(description="The name of the person who approved the order")
    lines: list[PurchaseOrderLine]
    po_total: Cited


class ReceiptLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Cited
    quantity_received: Cited


class ReceivingFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    receipt_number: Cited
    po_number: Cited
    received_date: Cited
    lines: list[ReceiptLine]


class ContractFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    vendor_name: Cited
    term_start: Cited
    term_end: Cited


class Findings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice: InvoiceFindings | None = Field(description="The invoice for this entry, or null if it cannot be read")
    purchase_order: PurchaseOrderFindings | None
    receiving_record: ReceivingFindings | None
    contract: ContractFindings | None
    notes: str = Field(description="Anything the reviewer should know, e.g. a page that could not be read")
