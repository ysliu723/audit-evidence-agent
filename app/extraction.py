"""What an extractor (Claude, or the rule-based baseline) hands to the checks.

Every extracted value carries the page and the exact words it came from, so
code can confirm it really appears in the document before trusting it.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain import ServiceCategory


class Cited(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(description="The value, normalized: amounts like 1234.56, dates like 2026-11-14")
    page: int = Field(description="Page number in the document, starting at 1")
    quote: str = Field(description="The exact words from that page the value was read from")


class InvoiceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    vendor_name: Cited
    invoice_number: Cited
    invoice_date: Cited
    total_amount: Cited
    bank_last4: Cited | None = Field(description="Last four digits of the remit-to bank account, if shown")
    service_description: Cited
    service_category: ServiceCategory


class ContractExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    vendor_name: Cited
    scope: Cited = Field(description="The sentence describing the services the contract covers")
    scope_categories: list[ServiceCategory]
    not_to_exceed: Cited | None = Field(description="The maximum total fees, if the contract states one")


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice: InvoiceExtraction | None = Field(description="The invoice supporting the entry, or null if none was found")
    contract: ContractExtraction | None = Field(description="The vendor's contract, or null if none was found")
    notes: str = Field(description="Anything the reviewer should know, e.g. why no invoice was found")
