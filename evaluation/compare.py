"""Compare two evaluation runs of the same cases, such as the baseline and optimized retrieval profiles.

    python -m evaluation.compare docs/results/claude-baseline.json docs/results/claude-optimized.json

Prints a table of accuracy, mean cost per case, latency (median and p95), and input tokens, with the
change from the first run to the second. Both runs must cover the same cases.
"""

import json
import statistics
import sys
from pathlib import Path


def summary(records: list[dict]) -> dict:
    seconds = sorted(r["seconds"] for r in records)
    p95 = seconds[min(len(seconds) - 1, int(round(0.95 * (len(seconds) - 1))))]
    decisions = sum(len(r["expected"]) for r in records)
    return {"cases": len(records), "accuracy": (decisions - sum(len(r["wrong"]) for r in records)) / decisions,
            "mean_cost": statistics.mean(r["cost_usd"] for r in records),
            "median_seconds": statistics.median(seconds), "p95_seconds": p95,
            "mean_input_tokens": statistics.mean(r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"]
                                                 for r in records)}


def change(before: float, after: float) -> str:
    return f"{100 * (after - before) / before:+.0f}%" if before else "n/a"


def compare(first: list[dict], second: list[dict], names: tuple[str, str]) -> str:
    if sorted(r["case_id"] for r in first) != sorted(r["case_id"] for r in second):
        raise ValueError("the two runs do not cover the same cases")
    a, b = summary(first), summary(second)
    rows = [("Check-level accuracy", f"{a['accuracy']:.1%}", f"{b['accuracy']:.1%}",
             f"{100 * (b['accuracy'] - a['accuracy']):+.1f} points"),
            ("Mean cost per case", f"${a['mean_cost']:.4f}", f"${b['mean_cost']:.4f}", change(a["mean_cost"], b["mean_cost"])),
            ("Median latency", f"{a['median_seconds']:.1f} s", f"{b['median_seconds']:.1f} s",
             change(a["median_seconds"], b["median_seconds"])),
            ("p95 latency", f"{a['p95_seconds']:.1f} s", f"{b['p95_seconds']:.1f} s", change(a["p95_seconds"], b["p95_seconds"])),
            ("Mean input tokens per case", f"{a['mean_input_tokens']:,.0f}", f"{b['mean_input_tokens']:,.0f}",
             change(a["mean_input_tokens"], b["mean_input_tokens"]))]
    lines = [f"| | {names[0]} | {names[1]} | Change |", "|---|---|---|---|"]
    lines += [f"| {label} | {x} | {y} | {d} |" for label, x, y, d in rows]
    return f"{a['cases']} cases, same model and settings except retrieval.\n\n" + "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    if len(paths) != 2:
        print("usage: python -m evaluation.compare <first.json> <second.json>", file=sys.stderr)
        return 2
    first, second = (json.loads(p.read_text(encoding="utf-8")) for p in paths)
    print(compare(first, second, (paths[0].stem, paths[1].stem)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
