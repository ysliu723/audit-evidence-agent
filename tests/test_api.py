from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.cli import main as cli
from app.evidence import load_ground_truth
from app.integration import entry_from_risk_platform
from app.main import app, get_session
from app.results import make_session_factory


@pytest.fixture
def client(tmp_path):
    factory = make_session_factory(f"sqlite:///{tmp_path / 'results.db'}")

    def test_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def truths():
    return load_ground_truth()


def case_for(truths, scenario, layouts=("A", "B")):
    return next(t.case_id for t in truths.values() if t.scenario == scenario and t.template in layouts)


def test_list_cases(client):
    cases = client.get("/cases").json()
    assert len(cases) == 80 and cases[0]["case_id"] == "CASE-001"


def test_vouching_saves_the_result_and_memo(client, truths):
    case_id = case_for(truths, "BANK_ACCOUNT_CHANGED")
    response = client.post(f"/cases/{case_id}/vouch")

    assert response.status_code == 201
    result = response.json()
    assert (result["status"], result["extractor"], result["current_decision"]) == ("EXCEPTION", "rules", None)
    bank = next(f for f in result["findings"] if f["check"] == "BANK_ACCOUNT")
    assert bank["status"] == "FAIL" and bank["sources"]
    assert any("contact details on file" in step for step in result["memo"]["next_steps"])
    assert client.get(f"/results/{result['id']}").json() == result
    assert [r["id"] for r in client.get("/results", params={"status": "EXCEPTION"}).json()] == [result["id"]]


def test_reviews_are_kept_in_order_and_the_latest_one_counts(client, truths):
    result_id = client.post(f"/cases/{case_for(truths, 'SUPPORTED')}/vouch").json()["id"]

    first = client.post(f"/results/{result_id}/reviews", json={"reviewer": "senior1", "decision": "REJECTED",
                                                                "notes": "Need the PO as well."})
    second = client.post(f"/results/{result_id}/reviews", json={"reviewer": "manager1", "decision": "APPROVED"})

    assert first.status_code == second.status_code == 201
    result = second.json()
    assert [r["decision"] for r in result["reviews"]] == ["REJECTED", "APPROVED"]
    assert result["current_decision"] == "APPROVED"


@pytest.mark.parametrize(
    "body, message",
    [
        ({"reviewer": "manager1", "decision": "EDITED"}, "needs the edited summary"),
        ({"reviewer": "manager1", "decision": "REJECTED"}, "needs notes"),
        ({"reviewer": " ", "decision": "APPROVED"}, "reviewer's name"),
    ],
)
def test_incomplete_reviews_are_refused(client, truths, body, message):
    result_id = client.post(f"/cases/{case_for(truths, 'SUPPORTED')}/vouch").json()["id"]
    response = client.post(f"/results/{result_id}/reviews", json=body)
    assert response.status_code == 422 and message in response.json()["detail"]


def test_replay_without_recordings_says_how_to_record(client, truths):
    response = client.post(f"/cases/{case_for(truths, 'SUPPORTED')}/vouch", params={"extractor": "replay"})
    assert response.status_code == 409 and "record it first" in response.json()["detail"]


def test_not_found(client):
    assert client.post("/cases/CASE-999/vouch").status_code == 404
    assert client.get("/results/999").status_code == 404


def test_the_command_line_prints_the_memo(truths, capsys):
    assert cli(["vouch", case_for(truths, "CUTOFF")]) == 0
    out = capsys.readouterr().out
    assert "Status: EXCEPTION" in out and "[FAIL] CUTOFF" in out


def test_an_entry_from_the_risk_platform_api_becomes_a_flagged_entry():
    detail = {  # the shape of GET /entries/{id} on the journal entry risk platform
        "id": 7, "run_id": 1, "entry_id": "JE000007", "posting_date": "2026-11-20", "created_at": "2026-11-20T16:40:00",
        "source": "MANUAL", "description": "Consulting fee - Fabrikam project", "prepared_by": "gl_acct1",
        "approved_by": None, "amount": "97500.00", "risk_score": 70, "risk_level": "HIGH",
        "rule_codes": ["MISSING_APPROVAL", "NEAR_APPROVAL_THRESHOLD"], "currency": "USD",
        "lines": [
            {"line_number": 1, "account_number": "610100", "debit": "97500.00", "credit": "0.00",
             "department": "Finance", "vendor": "Fabrikam"},
            {"line_number": 2, "account_number": "200100", "debit": "0.00", "credit": "97500.00",
             "department": "Finance", "vendor": "Fabrikam"},
        ],
        "hits": [],
    }
    entry = entry_from_risk_platform(detail)
    assert (entry.entry_id, entry.vendor, entry.account_number) == ("JE000007", "Fabrikam", "610100")
    assert entry.amount == Decimal("97500.00") and entry.rule_codes == ["MISSING_APPROVAL", "NEAR_APPROVAL_THRESHOLD"]
