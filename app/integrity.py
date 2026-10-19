"""Spotting text in a document that tries to instruct whoever reviews it.

A genuine invoice never tells "automated review systems" what to report. Text like that is a
prompt-injection attempt, and to an auditor it is also a red flag about the document itself. This is plain
pattern matching on the document, so it works whether or not the model was fooled. Values quoted from such
text are refused, and the case is flagged for a person.
"""

import re

from app.evidence import CaseFolder

INSTRUCTION_PATTERNS = [
    re.compile(r"\b(automated|ai)\s+(review|reviewer|reviewers|review systems?|systems?|assistants?)\b", re.IGNORECASE),
    re.compile(r"\bignore\s+(the|all|any|previous|prior)\s+(audit\s+)?(rules|instructions|checks)\b", re.IGNORECASE),
    re.compile(r"\bmark\s+(every\s+check|all\s+checks|everything)\s+as\s+(pass|passed|approved)\b", re.IGNORECASE),
    re.compile(r"\breport\s+(the|all)\s+[a-z ]{0,30}\s+as\s+(matching|pass|passed)\b", re.IGNORECASE),
]


def suspicious_lines(folder: CaseFolder, document_id: str) -> list[str]:
    try:
        pages = folder.pages(document_id)
    except LookupError:
        return []
    lines = [line for page in pages for line in page.splitlines()]
    return [line.strip() for line in lines if any(pattern.search(line) for pattern in INSTRUCTION_PATTERNS)]


def instructions_anywhere(folder: CaseFolder) -> dict[str, list[str]]:
    found = {d.document_id: suspicious_lines(folder, d.document_id) for d in folder.case.documents}
    return {doc: lines for doc, lines in found.items() if lines}
