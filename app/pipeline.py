"""Vouching one case end to end: extract, then check."""

from dataclasses import dataclass
from typing import Protocol

from app.checks import CheckReport, run_checks
from app.domain import Case
from app.evidence import EvidenceStore
from app.extractors.base import ExtractionRun


class Extractor(Protocol):
    name: str

    def extract(self, case: Case) -> ExtractionRun: ...


@dataclass
class VouchResult:
    case: Case
    run: ExtractionRun
    report: CheckReport


def vouch(case: Case, extractor: Extractor, store: EvidenceStore) -> VouchResult:
    run = extractor.extract(case)
    return VouchResult(case=case, run=run, report=run_checks(case, run.extraction, store))
