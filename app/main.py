"""The web API.

    uvicorn app.main:app --reload --port 8002      (docs at http://localhost:8002/docs)

    GET  /cases                        the cases waiting to be vouched
    POST /cases/{case_id}/vouch        vouch one (?extractor=rules|claude|replay); returns the result and memo
    GET  /results                      saved results (?status=EXCEPTION to filter)
    GET  /results/{id}                 one result: status, findings with sources, memo, reviews
    POST /results/{id}/reviews         a reviewer approves, edits, or rejects the memo
"""

import json
from collections.abc import Iterator
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evidence import EvidenceStore, load_cases
from app.llm import MissingRecording
from app.results import Decision, InvalidReview, VouchRecord, add_review, make_session_factory, save_result
from app.service import EXTRACTORS, vouch_case

app = FastAPI(title="Audit Evidence Agent", version="1.0.0")
store = EvidenceStore.load()
cases = {case.case_id: case for case in load_cases()}
_session_factory = None


def get_session() -> Iterator[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory()
    with _session_factory() as session:
        yield session


class ReviewIn(BaseModel):
    reviewer: str
    decision: Decision
    notes: str = ""
    edited_summary: str | None = None


class ReviewOut(BaseModel):
    reviewer: str
    decision: str
    notes: str
    edited_summary: str | None
    created_at: datetime


class ResultOut(BaseModel):
    id: int
    case_id: str
    entry_id: str
    extractor: str
    model: str | None
    status: str
    findings: list[dict]
    memo: dict
    cost_usd: float
    created_at: datetime
    reviews: list[ReviewOut]
    current_decision: str | None  # the latest review, or None while it waits for one


def result_out(record: VouchRecord) -> ResultOut:
    reviews = [ReviewOut(reviewer=r.reviewer, decision=r.decision, notes=r.notes, edited_summary=r.edited_summary,
                         created_at=r.created_at) for r in record.reviews]
    return ResultOut(
        id=record.id, case_id=record.case_id, entry_id=record.entry_id, extractor=record.extractor,
        model=record.model, status=record.status, findings=json.loads(record.findings_json),
        memo=json.loads(record.memo_json), cost_usd=record.cost_usd, created_at=record.created_at,
        reviews=reviews, current_decision=reviews[-1].decision if reviews else None,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cases")
def list_cases() -> list[dict]:
    return [
        {"case_id": c.case_id, "entry_id": c.entry.entry_id, "vendor": c.entry.vendor, "amount": str(c.entry.amount),
         "description": c.entry.description}
        for c in cases.values()
    ]


@app.post("/cases/{case_id}/vouch", response_model=ResultOut, status_code=status.HTTP_201_CREATED)
def vouch_one(case_id: str, extractor: str = Query("rules", enum=list(EXTRACTORS)),
              session: Session = Depends(get_session)):
    case = cases.get(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"case {case_id} not found")
    try:
        result, memo = vouch_case(case, extractor, store)
    except MissingRecording as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from None
    except Exception as error:  # e.g. no API credentials for a live run
        if type(error).__module__.startswith("anthropic"):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Claude is not available: {error}") from None
        raise
    return result_out(save_result(session, result, memo, extractor))


@app.get("/results", response_model=list[ResultOut])
def list_results(status_filter: str | None = Query(None, alias="status"), session: Session = Depends(get_session)):
    query = select(VouchRecord).order_by(VouchRecord.id.desc())
    if status_filter:
        query = query.where(VouchRecord.status == status_filter)
    return [result_out(record) for record in session.scalars(query)]


@app.get("/results/{result_id}", response_model=ResultOut)
def read_result(result_id: int, session: Session = Depends(get_session)):
    record = session.get(VouchRecord, result_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"result {result_id} not found")
    return result_out(record)


@app.post("/results/{result_id}/reviews", response_model=ResultOut, status_code=status.HTTP_201_CREATED)
def review(result_id: int, body: ReviewIn, session: Session = Depends(get_session)):
    record = session.get(VouchRecord, result_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"result {result_id} not found")
    try:
        add_review(session, record, body.reviewer, body.decision, body.notes, body.edited_summary)
    except InvalidReview as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    session.refresh(record)
    return result_out(record)
