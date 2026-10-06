"""Saving vouching results and the reviewer's decisions (SQLite by default; no server to run).

    vouch_results   one row per run: status, findings, extraction, memo, cost
    reviews         one row per review decision; never updated, so the review history stays intact

A result is only final once a person reviews it. The latest review is the
current decision; earlier ones remain as the record of who decided what, and when.
"""

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.memo import Memo
from app.pipeline import VouchResult

DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "data" / "results.db"
DATABASE_URL = os.environ.get("EVIDENCE_AGENT_DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE}")


class Decision(StrEnum):
    APPROVED = "APPROVED"  # the reviewer agrees with the memo as it is
    EDITED = "EDITED"  # the reviewer agrees after changing the summary
    REJECTED = "REJECTED"  # the reviewer disagrees; notes say why


class Base(DeclarativeBase):
    pass


class VouchRecord(Base):
    __tablename__ = "vouch_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32))
    entry_id: Mapped[str] = mapped_column(String(32))
    extractor: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    findings_json: Mapped[str] = mapped_column(Text)
    extraction_json: Mapped[str] = mapped_column(Text)
    memo_json: Mapped[str] = mapped_column(Text)
    cost_usd: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reviews: Mapped[list["ReviewRecord"]] = relationship(order_by="ReviewRecord.id")


class ReviewRecord(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("vouch_results.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    edited_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def make_session_factory(url: str = DATABASE_URL) -> sessionmaker[Session]:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def save_result(session: Session, result: VouchResult, memo: Memo, extractor: str) -> VouchRecord:
    findings = [
        {"check": f.check, "status": str(f.status), "detail": f.detail, "sources": list(f.sources)}
        for f in result.report.findings
    ]
    record = VouchRecord(
        case_id=result.case.case_id,
        entry_id=result.case.entry.entry_id,
        extractor=extractor,
        model=result.run.model,
        status=result.report.status,
        findings_json=json.dumps(findings),
        extraction_json=result.run.extraction.model_dump_json(),
        memo_json=json.dumps(asdict(memo)),
        cost_usd=result.run.cost_usd + memo.cost_usd,
    )
    session.add(record)
    session.commit()
    return record


class InvalidReview(ValueError):
    pass


def add_review(session: Session, record: VouchRecord, reviewer: str, decision: Decision, notes: str = "",
               edited_summary: str | None = None) -> ReviewRecord:
    if not reviewer.strip():
        raise InvalidReview("a review needs the reviewer's name")
    if decision == Decision.EDITED and not (edited_summary or "").strip():
        raise InvalidReview("an EDITED review needs the edited summary")
    if decision == Decision.REJECTED and not notes.strip():
        raise InvalidReview("a REJECTED review needs notes saying why")
    review = ReviewRecord(
        result_id=record.id, reviewer=reviewer.strip(), decision=str(decision), notes=notes,
        edited_summary=edited_summary, created_at=datetime.now(timezone.utc),
    )
    session.add(review)
    session.commit()
    return review
