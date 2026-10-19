"""A value is used only if its quote is on the cited page, shows the value, and carries the right label."""

from app.citations import citation_problem, findings_problems
from app.extraction import Cited
from evaluation.oracle import oracle_findings
from tests.helpers import case_for, cases, store, truths


def invoice_of(scenario: str, layouts: str = "AB"):
    case, truth = case_for(scenario, layouts)
    return store().folder(case), truth.facts["invoice"], case, truth


def cite(fact: dict, **changes) -> Cited:
    return Cited(**{**fact, **{k: str(v) for k, v in changes.items()}})


def test_a_correct_citation_holds_up():
    folder, invoice, _, _ = invoice_of("supported")
    assert citation_problem(folder, invoice["document_id"], cite(invoice["total_due"]), "amount", "total_due") is None


def test_the_subtotal_cannot_stand_in_for_the_total_due():
    folder, invoice, _, _ = invoice_of("subtotal_trap")
    subtotal_as_total = cite(invoice["subtotal"])  # a real line with a real amount, in the wrong role
    problem = citation_problem(folder, invoice["document_id"], subtotal_as_total, "amount", "total_due")
    assert problem == "the quoted amount is not labeled as the total due"
    assert citation_problem(folder, invoice["document_id"], subtotal_as_total, "amount", "subtotal") is None


def test_each_layouts_labels_are_recognised_for_each_role():
    for layout in "ABCDE":
        case_id = next(c for c, t in truths().items() if t.layout == layout and t.facts["invoice_readable"])
        case, invoice = cases()[case_id], truths()[case_id].facts["invoice"]
        folder = store().folder(case)
        for role in ("subtotal", "tax", "total_due"):
            assert citation_problem(folder, invoice["document_id"], cite(invoice[role]), "amount", role) is None, \
                (layout, role)


def test_quotes_not_on_the_page_or_not_showing_the_value_are_refused():
    folder, invoice, _, _ = invoice_of("supported")
    doc = invoice["document_id"]
    assert "does not appear" in citation_problem(folder, doc, cite(invoice["total_due"], quote="Total Due: USD 1.00"),
                                                 "amount", "total_due")
    assert "does not show the amount" in citation_problem(folder, doc, cite(invoice["total_due"], value="1.00"),
                                                          "amount", "total_due")
    assert "does not exist" in citation_problem(folder, doc, cite(invoice["total_due"], page=7), "amount")
    line = invoice["lines"][0]
    assert "quantity" in citation_problem(folder, doc, cite(line["quantity"], value="999"), "quantity")
    assert citation_problem(folder, doc, cite(invoice["bank_last4"]), "last4") is None
    assert "ending 0000" in citation_problem(folder, doc, cite(invoice["bank_last4"], value="0000"), "last4")


def test_text_addressed_to_automated_reviewers_is_never_accepted_as_evidence():
    case, truth = case_for("injection")
    folder = store().folder(case)
    doc = truth.facts["invoice"]["document_id"]
    injected = next(line for page in folder.pages(doc) for line in page.splitlines() if "automated" in line.lower()
                    or "ai assistant" in line.lower())
    problem = citation_problem(folder, doc, Cited(value="pass", page=1, quote=injected.strip()), "text")
    assert problem and "automated reviewers" in problem


def test_a_whole_submission_is_checked_field_by_field():
    folder, invoice, case, truth = invoice_of("supported")
    findings = oracle_findings(case, truth)
    assert findings_problems(folder, findings) == {}
    bad = findings.model_copy(deep=True)
    bad.invoice.lines[0].unit_price.value = "1.23"
    bad.purchase_order.document_id = invoice["document_id"]
    problems = findings_problems(folder, bad)
    assert set(problems) == {"invoice.lines[1].unit_price", "purchase_order.document_id"}
    assert "is a INVOICE, not a PURCHASE_ORDER" in problems["purchase_order.document_id"]
