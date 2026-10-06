"""Command line.

    python -m app.cli cases                               list the cases
    python -m app.cli vouch CASE-006                      vouch with the rule-based baseline, print the memo
    python -m app.cli vouch CASE-006 --extractor replay   Claude's recorded answers, no API key needed
    python -m app.cli vouch CASE-006 --extractor claude   live (needs ANTHROPIC_API_KEY or `ant auth login`)
"""

import argparse
import sys

from app.evidence import EvidenceStore, load_cases
from app.llm import MissingRecording
from app.memo import render
from app.service import EXTRACTORS, vouch_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vouch flagged journal entries against their evidence.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cases", help="list the cases")
    vouch_parser = commands.add_parser("vouch", help="vouch one case and print its memo")
    vouch_parser.add_argument("case_id")
    vouch_parser.add_argument("--extractor", default="rules", choices=EXTRACTORS)
    args = parser.parse_args(argv)

    cases = {case.case_id: case for case in load_cases()}
    if args.command == "cases":
        for case in cases.values():
            print(f"{case.case_id}  {case.entry.entry_id}  {case.entry.amount:>12,.2f}  {case.entry.description}")
        return 0

    case = cases.get(args.case_id)
    if case is None:
        print(f"error: case {args.case_id} not found", file=sys.stderr)
        return 1
    try:
        result, memo = vouch_case(case, args.extractor, EvidenceStore.load())
    except MissingRecording as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(render(memo))
    if result.run.tool_calls:
        print(f"\n({len(result.run.tool_calls)} tool calls, ${result.run.cost_usd + memo.cost_usd:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
