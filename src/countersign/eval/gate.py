"""Regression gate: recompute every committed evaluation report and hold it to its limits.

    python -m countersign.eval.gate

It answers two questions, without a GPU:

1. Are the committed reports current? Each report under `evals/reports` is recomputed
   from the recorded model answers and must come out identical, and so must the
   Markdown page next to it. A change to the parser, a check or the decision code that
   moves a single document shows up here, and so does a prompt change that was not
   recorded again.
2. Are they still good enough? `evals/thresholds.json` gives, per report, the most
   harmful decisions tolerated and the least automation accepted. A report without
   limits is only checked for being current.
"""

import argparse
import json
import sys
from pathlib import Path

from countersign.eval.metrics import Report
from countersign.eval.report import to_markdown
from countersign.eval.run import CONFIGS, evaluate
from countersign.llm.cassette import CassetteMiss


def _differences(committed: Report, current: Report) -> str:
    """A short description of what changed between two reports of the same run."""
    before = {document.id: document for document in committed.documents}
    changed = [
        f"{document.id} ({before[document.id].outcome} -> {document.outcome})"
        for document in current.documents
        if document.id in before and before[document.id] != document
    ]
    if not changed:
        return "summary or document list differs"
    more = f" and {len(changed) - 5} more" if len(changed) > 5 else ""
    return "changed: " + ", ".join(changed[:5]) + more


def stale_reports(reports: Path, data: Path, cassettes: Path) -> list[str]:
    problems = []
    for path in sorted(reports.glob("*.json")):
        committed = Report.model_validate_json(path.read_text(encoding="utf-8"))
        if committed.config not in CONFIGS:
            problems.append(f"{path.name}: unknown configuration '{committed.config}'")
            continue
        try:
            current, _ = evaluate(
                committed.split, committed.config, data=data, cassettes=cassettes, mode="replay"
            )
        except CassetteMiss as miss:
            problems.append(f"{path.name}: cannot be replayed ({miss})")
            continue
        if current != committed:
            problems.append(f"{path.name} is out of date; {_differences(committed, current)}")
            continue
        page = path.with_suffix(".md")
        if not page.exists() or page.read_text(encoding="utf-8") != to_markdown(current):
            problems.append(f"{page.name} is not the page {path.name} renders to")
    return problems


def broken_thresholds(reports: Path, thresholds: Path) -> list[str]:
    if not thresholds.exists():
        return [f"{thresholds}: no thresholds file"]
    limits: dict[str, dict[str, float]] = json.loads(thresholds.read_text(encoding="utf-8"))
    problems = []
    for name, limit in limits.items():
        path = reports / f"{name}.json"
        if not path.exists():
            problems.append(f"{name}: a threshold is set but there is no report")
            continue
        summary = Report.model_validate_json(path.read_text(encoding="utf-8")).summary
        measured = {
            "harmful_max": summary.harmful.count,
            "automation_min": summary.automation.value,
            "stopped_min": summary.stopped.value,
            "critical_correct_min": summary.critical_correct.value,
        }
        for key, bound in limit.items():
            value = measured[key]
            if value is None:
                problems.append(f"{name}: {key.rsplit('_', 1)[0]} cannot be measured")
                continue
            ok = value <= bound if key.endswith("_max") else value >= bound
            if not ok:
                problems.append(f"{name}: {key.rsplit('_', 1)[0]} is {value}, the limit is {bound}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--cassettes", type=Path, default=Path("evals/cassettes"))
    parser.add_argument("--reports", type=Path, default=Path("evals/reports"))
    parser.add_argument("--thresholds", type=Path, default=Path("evals/thresholds.json"))
    arguments = parser.parse_args()

    count = len(list(arguments.reports.glob("*.json")))
    if count == 0:
        print(f"no report under {arguments.reports}", file=sys.stderr)
        return 2
    problems = stale_reports(arguments.reports, arguments.data, arguments.cassettes)
    problems += broken_thresholds(arguments.reports, arguments.thresholds)
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{count} reports recomputed from recorded answers: all identical, all within limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
