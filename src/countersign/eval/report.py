"""Write an evaluation report as JSON (for the regression gate) and Markdown (for people).

Reports carry no timestamp and no machine name: replaying the same cassette must give
the same bytes, which is what lets CI prove that the committed numbers are current.
"""

from pathlib import Path

from countersign.eval.metrics import DocumentScore, Rate, Report, Summary


def percent(rate: Rate, *, interval: bool = False) -> str:
    if rate.total == 0:
        return "n/a"
    # From the counts, not from the stored value, which is already rounded.
    text = f"{rate.count / rate.total * 100:.1f} %"
    if interval and rate.low is not None and rate.high is not None:
        text += f" [{rate.low * 100:.1f} to {rate.high * 100:.1f}]"
    return f"{text} ({rate.count}/{rate.total})"


def _summary_rows(summary: Summary) -> list[tuple[str, str]]:
    return [
        ("Documents", str(summary.documents)),
        (
            "**Harmful decisions**",
            f"**{summary.harmful.count}** ({summary.wrong_approvals} wrong approvals, "
            f"{summary.lost_invoices} invoices set aside)",
        ),
        (
            "Approved without a person, among documents that can be",
            percent(summary.automation, interval=True),
        ),
        ("Approvals that were right", percent(summary.approval_precision, interval=True)),
        (
            "Stopped, among documents that must not be approved",
            percent(summary.stopped, interval=True),
        ),
        (
            "Stopped for the expected reason, among documents labelled with one",
            percent(summary.reason_found),
        ),
        ("Outcome exactly as labelled", percent(summary.as_expected)),
        (
            "Invoices with every critical field right",
            percent(summary.critical_correct, interval=True),
        ),
        ("Invoices with every line right", percent(summary.lines_correct)),
        ("Documents read by more than one tier", percent(summary.escalated)),
        (
            "Model time per document",
            f"mean {summary.seconds_mean} s, median {summary.seconds_median} s, "
            f"95th percentile {summary.seconds_p95} s",
        ),
        (
            "Tokens per document",
            f"{summary.prompt_tokens_mean:.0f} in, {summary.output_tokens_mean:.0f} out",
        ),
        ("Model calls that failed", str(summary.model_errors)),
    ]


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _breakdown(groups: dict[str, Summary]) -> list[str]:
    rows = [
        [
            name,
            str(summary.documents),
            str(summary.harmful.count),
            percent(summary.automation),
            percent(summary.stopped),
            percent(summary.critical_correct),
            f"{summary.seconds_mean} s",
        ]
        for name, summary in groups.items()
    ]
    header = [
        "Group",
        "Docs",
        "Harmful",
        "Approved when possible",
        "Stopped when needed",
        "Critical fields right",
        "Model time",
    ]
    return _table(header, rows)


def _wrong_fields(score: DocumentScore) -> str:
    if not score.fields:
        return ""
    wrong = [field for field, correct in score.fields.items() if not correct]
    if score.supplier_correct is False:
        wrong.insert(0, "supplier record")
    return ", ".join(wrong)


def _document_rows(scores: list[DocumentScore]) -> list[str]:
    rows = [
        [
            score.id,
            f"{score.scenario}{'/' + score.variant if score.variant else ''}",
            f"{score.layout}, {score.language}",
            score.expected,
            score.outcome,
            ", ".join(score.reasons) or "",
            _wrong_fields(score),
        ]
        for score in scores
    ]
    return _table(
        ["Document", "Scenario", "Layout", "Expected", "Got", "Reasons", "Wrong fields"], rows
    )


def to_markdown(report: Report) -> str:
    summary = report.summary
    lines = [
        f"# Evaluation: `{report.config}` on the `{report.split}` split",
        "",
        f"Models: {', '.join(f'`{model}`' for model in report.models)}. "
        f"Prompt: `{report.prompt_id}`. Checks: {'on' if report.verify else 'off'}.",
        "",
        "Percentages are followed by their 95 % Wilson interval where it matters, and by "
        "the counts they come from.",
        "",
        "## Summary",
        "",
        *_table(["Measure", "Value"], [[name, value] for name, value in _summary_rows(summary)]),
        "",
        "## Field accuracy (invoices and credit notes)",
        "",
        *_table(
            ["Field", "Correct"],
            [[f"`{field}`", percent(rate)] for field, rate in summary.field_accuracy.items()],
        ),
        "",
        "## By scenario",
        "",
        *_breakdown(report.by_scenario),
        "",
        "## By group",
        "",
        *_breakdown(report.by_group),
        "",
    ]
    harmful = [score for score in report.documents if score.harm]
    lines += ["## Harmful decisions", ""]
    lines += _document_rows(harmful) if harmful else ["None."]
    unexpected = [score for score in report.documents if not score.as_expected and not score.harm]
    lines += ["", "## Other documents not handled as labelled", ""]
    lines += _document_rows(unexpected) if unexpected else ["None."]
    return "\n".join(lines) + "\n"


def write_report(report: Report, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{report.split}-{report.config}"
    (directory / f"{stem}.json").write_text(
        report.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    path = directory / f"{stem}.md"
    path.write_text(to_markdown(report), encoding="utf-8", newline="\n")
    return path
