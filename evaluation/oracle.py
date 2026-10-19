"""Perfect extraction, built from the labels: what the checks reach when every value is read correctly.

If the oracle does not score 100%, the checks (not the extractor) are wrong. A scanned invoice cannot be
read, so the oracle reports it as unreadable, as a perfect reader would.
"""

from app.domain import Case, GroundTruth
from app.extraction import (ContractFindings, Findings, InvoiceFindings, PurchaseOrderFindings, ReceivingFindings)


def oracle_findings(case: Case, truth: GroundTruth) -> Findings:
    facts = truth.facts
    invoice = facts["invoice"] if facts.get("invoice_readable", True) else None
    return Findings(
        invoice=InvoiceFindings.model_validate(_with_nulls(invoice, ("tax_id", "po_number", "bank_last4", "subtotal",
                                                                      "tax"))) if invoice else None,
        purchase_order=PurchaseOrderFindings.model_validate(facts["purchase_order"]) if facts.get("purchase_order") else None,
        receiving_record=ReceivingFindings.model_validate(facts["receiving_record"]) if facts.get("receiving_record") else None,
        contract=ContractFindings.model_validate(facts["contract"]) if facts.get("contract") else None,
        notes="" if invoice or not facts.get("invoice") else "The invoice is a scanned image and could not be read.",
    )


def _with_nulls(document: dict, optional: tuple[str, ...]) -> dict:
    return {**{name: None for name in optional}, **document}
