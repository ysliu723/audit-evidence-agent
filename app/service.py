"""Vouch a case with the chosen extractor and write its memo: shared by the API and the command line.

    rules    the rule-based baseline; no model, template memo
    claude   Claude, live (needs credentials); Claude drafts the memo
    replay   Claude's recorded answers from data/recordings/; no API key needed
"""

from app.domain import Case
from app.evidence import EvidenceStore
from app.llm import AnthropicAPI, MissingRecording, ReplayAPI
from app.memo import Memo, draft_memo, template_memo
from app.pipeline import VouchResult, vouch

EXTRACTORS = ("rules", "claude", "replay")


def vouch_case(case: Case, extractor: str, store: EvidenceStore) -> tuple[VouchResult, Memo]:
    if extractor == "rules":
        from app.extractors.rules import RuleBasedExtractor

        result = vouch(case, RuleBasedExtractor(store), store)
        return result, template_memo(result)
    if extractor not in EXTRACTORS:
        raise ValueError(f"extractor must be one of {', '.join(EXTRACTORS)}")

    from app.extractors.claude import ClaudeExtractor

    api = ReplayAPI() if extractor == "replay" else AnthropicAPI()
    claude = ClaudeExtractor(store, api)
    result = vouch(case, claude, store)
    try:
        memo = draft_memo(result, api, model=claude.model)
    except MissingRecording:
        memo = template_memo(result)
        memo.warnings.append("No recorded draft for this memo; the standard memo is used.")
    return result, memo
