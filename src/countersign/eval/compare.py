"""Tables that put the committed reports side by side, as Markdown.

    python -m countersign.eval.compare --split confirm      # print them
    python -m countersign.eval.compare --update             # write them into the pages

The tables in the README and in docs/evaluation.md are the output of this module: a
page marks where a table goes with `<!-- table:configurations:confirm-run -->` and
`<!-- /table -->`, and `--update` writes what the committed reports give between the
two. A test compares the pages with the reports, so that a number quoted in the
documentation cannot drift from the report it comes from.
"""

import argparse
import re
from collections.abc import Callable
from pathlib import Path

from countersign.eval.metrics import DocumentScore, Rate, Report, Summary, summarise

CONFIGURATIONS: tuple[tuple[str, str], ...] = (
    ("small-unverified", "Small model, nothing checked"),
    ("large-unverified", "Large model, nothing checked"),
    ("small", "Small model + checks"),
    ("large", "Large model + checks"),
    ("cascade", "**Cascade + checks**"),
)
PROMPTS: tuple[tuple[str, str], ...] = (
    ("prompt-v1", "v1: every value as text"),
    ("prompt-v2", "v2: amounts as numbers"),
    ("prompt-v3", "v3: no VAT base asked"),
    ("prompt-v4", "v4: IBAN and order number defined"),
    ("small", "v5: credit note number reworded, referenced invoice added"),
)


def load(reports: Path, split: str, names: tuple[str, ...]) -> dict[str, Report]:
    found = {}
    for name in names:
        path = reports / f"{split}-{name}.json"
        if path.exists():
            found[name] = Report.model_validate_json(path.read_text(encoding="utf-8"))
    return found


def share(rate: Rate) -> str:
    if rate.total == 0:
        return "n/a"
    # From the counts, not from the stored value, which is already rounded.
    return f"{rate.count / rate.total * 100:.1f} % ({rate.count}/{rate.total})"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _clean_seconds(report: Report) -> float:
    """Mean model time on the documents a correct system approves: the everyday case."""
    clean = [score.model_seconds for score in report.documents if score.expected == "approved"]
    return sum(clean) / len(clean) if clean else 0.0


def configurations(reports: dict[str, Report]) -> str:
    """The headline table: one row per configuration."""
    rows = []
    for name, label in CONFIGURATIONS:
        if name not in reports:
            continue
        summary = reports[name].summary
        rows.append(
            [
                label,
                f"{summary.harmful.count} ({summary.wrong_approvals} + {summary.lost_invoices})",
                share(summary.automation),
                share(summary.stopped),
                share(summary.critical_correct),
                f"{summary.seconds_mean:.1f} s",
                f"{_clean_seconds(reports[name]):.1f} s",
            ]
        )
    header = [
        "Configuration",
        "Harmful decisions (wrong approvals + invoices lost)",
        "Approved without a person, of those that can be",
        "Stopped, of those that must be",
        "Read with every critical field right",
        "Model time per document",
        "per clean document",
    ]
    return _table(header, rows)


def prompts(reports: dict[str, Report]) -> str:
    """The history of the prompt on the dev split, small model with checks."""
    rows = []
    for name, label in PROMPTS:
        if name not in reports:
            continue
        summary = reports[name].summary
        rows.append(
            [
                label,
                str(summary.harmful.count),
                share(summary.automation),
                share(summary.critical_correct),
                share(summary.lines_correct),
                f"{summary.output_tokens_mean:.0f}",
                f"{summary.seconds_mean:.1f} s",
            ]
        )
    header = [
        "Prompt",
        "Harmful",
        "Approved without a person",
        "Every critical field right",
        "Every line right",
        "Output tokens",
        "Model time",
    ]
    return _table(header, rows)


def _group_rows(groups: dict[str, Summary]) -> list[list[str]]:
    return [
        [
            name,
            str(summary.documents),
            str(summary.harmful.count),
            share(summary.automation),
            share(summary.stopped),
            share(summary.critical_correct),
            f"{summary.seconds_mean:.1f} s",
        ]
        for name, summary in groups.items()
    ]


_GROUP_HEADER = [
    "",
    "Documents",
    "Harmful",
    "Approved without a person",
    "Stopped when required",
    "Every critical field right",
    "Model time",
]


def groups(report: Report) -> str:
    """One configuration, broken down by how the document was read and where it came from."""
    return _table(["Group", *_GROUP_HEADER[1:]], _group_rows(report.by_group))


def scenarios(report: Report) -> str:
    return _table(["Scenario", *_GROUP_HEADER[1:]], _group_rows(report.by_scenario))


def tiers(report: Report) -> str:
    """Who read the documents of a cascade run, and what it cost."""
    by_path: dict[str, list[DocumentScore]] = {}
    for score in report.documents:
        path = " then ".join(score.tiers) if score.tiers else "not read"
        by_path.setdefault(path, []).append(score)
    rows = []
    for path, scores in sorted(by_path.items(), key=lambda item: -len(item[1])):
        summary = summarise(scores)
        rows.append(
            [
                path,
                str(len(scores)),
                str(summary.approved.count),
                str(summary.harmful.count),
                f"{summary.seconds_mean:.1f} s",
            ]
        )
    return _table(["Read by", "Documents", "Approved", "Harmful", "Model time"], rows)


PAGES = (Path("README.md"), Path("docs/evaluation.md"))
# A table is drawn from the reports of a split as the current code gives them ("test"),
# or as the one live run of that split wrote them ("test-run", kept in evals/history).
AS_RUN = "-run"
_NAMES = tuple(name for name, _ in (*CONFIGURATIONS, *PROMPTS))
_OF_ALL: dict[str, Callable[[dict[str, Report]], str]] = {
    "configurations": configurations,
    "prompts": prompts,
}
_OF_CASCADE: dict[str, Callable[[Report], str]] = {
    "groups": groups,
    "scenarios": scenarios,
    "tiers": tiers,
}
_BLOCK = re.compile(r"<!-- table:([a-z]+):([a-z-]+) -->\n.*?<!-- /table -->", re.DOTALL)


def table(kind: str, source: str, reports: Path, history: Path) -> str:
    """One table of a page: `kind` of the reports of `source` (see `AS_RUN`)."""
    as_run = source.endswith(AS_RUN)
    directory, split = (history, source.removesuffix(AS_RUN)) if as_run else (reports, source)
    found = load(directory, split, _NAMES)
    if kind in _OF_CASCADE:
        return _OF_CASCADE[kind](found["cascade"])
    return _OF_ALL[kind](found)


def update(pages: tuple[Path, ...], reports: Path, history: Path) -> int:
    """Rewrite every marked table of `pages` from the reports; returns how many."""
    written = 0

    def block(match: re.Match[str]) -> str:
        nonlocal written
        written += 1
        kind, source = match[1], match[2]
        content = table(kind, source, reports, history)
        return f"<!-- table:{kind}:{source} -->\n{content}\n<!-- /table -->"

    for page in pages:
        text = page.read_text(encoding="utf-8")
        page.write_text(_BLOCK.sub(block, text), encoding="utf-8", newline="\n")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", type=Path, default=Path("evals/reports"))
    parser.add_argument("--history", type=Path, default=Path("evals/history"))
    parser.add_argument("--split", default="confirm")
    parser.add_argument("--update", action="store_true", help="write the tables into the pages")
    arguments = parser.parse_args()

    if arguments.update:
        count = update(PAGES, arguments.reports, arguments.history)
        print(f"{count} tables written into {', '.join(str(page) for page in PAGES)}")
        return 0
    names = _NAMES
    reports = load(arguments.reports, arguments.split, names)
    if not reports:
        print(f"no report for the {arguments.split} split under {arguments.reports}")
        return 2
    print(f"## Configurations ({arguments.split} split)\n\n{configurations(reports)}\n")
    if any(name.startswith("prompt-") for name in reports):
        print(f"## Prompt versions ({arguments.split} split)\n\n{prompts(reports)}\n")
    if "cascade" in reports:
        cascade = reports["cascade"]
        print(f"## Cascade by group\n\n{groups(cascade)}\n")
        print(f"## Cascade by scenario\n\n{scenarios(cascade)}\n")
        print(f"## Cascade by reader\n\n{tiers(cascade)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
