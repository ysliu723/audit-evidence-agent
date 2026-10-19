"""Shared lookups for the tests: cases by scenario, and the store."""

from functools import lru_cache

from app.evidence import EvidenceStore, load_cases, load_ground_truth


@lru_cache
def store() -> EvidenceStore:
    return EvidenceStore.load()


@lru_cache
def truths():
    return load_ground_truth()


@lru_cache
def cases():
    return {case.case_id: case for case in load_cases()}


def case_for(scenario: str, layouts: str = "AB", split: str | None = None):
    """The first case built for a scenario, in one of the given invoice layouts."""
    for case_id, truth in truths().items():
        if truth.scenario == scenario and truth.layout in layouts and (split is None or truth.split == split):
            return cases()[case_id], truth
    raise LookupError(f"no {scenario} case in layouts {layouts}")
