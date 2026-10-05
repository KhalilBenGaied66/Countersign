"""Run a dataset split through a pipeline configuration and score every document.

    python -m countersign.eval.run --split dev --config cascade            # live, records
    python -m countersign.eval.run --split test --config cascade --replay  # no GPU needed

The pipeline under evaluation is the one the application runs: same parser, same
checks, same decision code. Only the model client differs: it answers from the
cassette, and in live mode asks the model server for what is missing and records it.
"""

import argparse
import json
import sys
from datetime import date
from functools import cache
from pathlib import Path

from countersign.eval.dataset import Sample, load_samples
from countersign.eval.metrics import DocumentScore, Report, score_document, summarise
from countersign.eval.report import write_report
from countersign.llm.cassette import Cassette, CassetteMiss, Mode, RecordingClient
from countersign.llm.client import ModelClient, OllamaClient
from countersign.master import MasterData
from countersign.parsing.pdf import ParsedDocument, parse_pdf, render_pages
from countersign.pipeline.process import Pipeline, PipelineConfig, Result, Tier
from countersign.verify.checks import Prior

# Every document of the dataset was issued before this date; it is "today" for the checks.
EVAL_TODAY = date(2026, 7, 1)

SMALL = Tier("small", "qwen3.5:4b")
LARGE = Tier("large", "qwen3.5:9b")

CONFIGS: dict[str, PipelineConfig] = {
    # What each model gets right on its own, with nothing checked.
    "small-unverified": PipelineConfig(tiers=(SMALL,), verify=False),
    "large-unverified": PipelineConfig(tiers=(LARGE,), verify=False),
    # One model, every extraction checked.
    "small": PipelineConfig(tiers=(SMALL,)),
    "large": PipelineConfig(tiers=(LARGE,)),
    # The system as designed: small model first, large one when a second reading can help.
    "cascade": PipelineConfig(tiers=(SMALL, LARGE)),
    # Earlier prompt versions, small model with checks: the history of the prompt on the
    # dev split. The current version is the "small" configuration.
    **{
        f"prompt-v{version}": PipelineConfig(tiers=(SMALL,), prompt_id=f"extract_v{version}")
        for version in (1, 2, 3, 4)
    },
    # The cascade as it would be with the third prompt: versions 4 and 5 were written for
    # mistakes of the large model, which the small-model history above cannot show.
    "prompt-v3-cascade": PipelineConfig(tiers=(SMALL, LARGE), prompt_id="extract_v3"),
}


@cache
def _parse(pdf: bytes) -> ParsedDocument:
    """Each file is parsed once per process: the gate reads it under every configuration."""
    return parse_pdf(pdf)


@cache
def _render(data: bytes, *, dpi: int, max_pages: int) -> tuple[bytes, ...]:
    return tuple(render_pages(data, dpi=dpi, max_pages=max_pages))


class MemoryLedger:
    """The invoices taken in during a run, keyed by supplier and number."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], Prior] = {}

    def find(self, vendor_id: str, invoice_number: str) -> Prior | None:
        return self._seen.get((vendor_id, invoice_number))

    def add(self, vendor_id: str, invoice_number: str, prior: Prior) -> None:
        self._seen.setdefault((vendor_id, invoice_number), prior)

    def record(self, document_id: str, result: Result) -> None:
        """Remember a processed document, as the application's database does."""
        invoice = result.invoice
        if result.outcome not in ("approved", "review") or invoice is None:
            return
        if result.vendor_id and invoice.invoice_number:
            prior = Prior(
                document_id, invoice.document_type, invoice.total_gross, invoice.issue_date
            )
            self.add(result.vendor_id, invoice.invoice_number, prior)


def _groups(scores: list[DocumentScore]) -> dict[str, list[DocumentScore]]:
    groups: dict[str, list[DocumentScore]] = {
        "seen suppliers": [s for s in scores if not s.held_out],
        "held-out suppliers": [s for s in scores if s.held_out],
        "text layer": [s for s in scores if s.mode == "text"],
        "scans": [s for s in scores if s.mode == "vision"],
        "embedded e-invoice": [s for s in scores if s.mode == "embedded"],
    }
    for language in sorted({s.language for s in scores}):
        groups[f"language: {language}"] = [s for s in scores if s.language == language]
    for layout in sorted({s.layout for s in scores}):
        groups[f"layout: {layout}"] = [s for s in scores if s.layout == layout]
    return {name: members for name, members in groups.items() if members}


def evaluate(
    split: str,
    config_name: str,
    *,
    data: Path,
    cassettes: Path,
    mode: Mode,
    config: PipelineConfig | None = None,
    model: ModelClient | None = None,
    only: set[str] | None = None,
    limit: int | None = None,
    progress: bool = False,
) -> tuple[Report, RecordingClient]:
    """Run every document of a split through a configuration and score the outcome.

    `config` overrides the named configuration; `model` replaces the model server
    that is asked for whatever the cassette does not hold.
    """
    config = config or CONFIGS[config_name]
    directory = data / "dataset" / split
    samples: list[Sample] = load_samples(directory)
    if only:
        samples = [sample for sample in samples if sample.id in only]
    if limit:
        samples = samples[:limit]

    if mode != "replay" and model is None:
        model = OllamaClient()
    client = RecordingClient(Cassette(cassettes / split), model, mode)
    pipeline = Pipeline(
        config, client, MasterData.load(data / "reference"), parse=_parse, render=_render
    )
    ledger = MemoryLedger()
    scores = []
    for position, sample in enumerate(samples, start=1):
        pdf = (directory / sample.file).read_bytes()
        result = pipeline.process(pdf, ledger=ledger, today=EVAL_TODAY, label=sample.id)
        ledger.record(sample.id, result)
        score = score_document(sample, result)
        scores.append(score)
        if progress:
            flag = f" !! {score.harm}" if score.harm else ""
            print(
                f"[{position}/{len(samples)}] {sample.id} {sample.scenario:<18} "
                f"{score.outcome:<9} (expected {score.expected}) "
                f"{score.model_seconds:5.1f}s{flag}",
                file=sys.stderr,
                flush=True,
            )

    by_scenario: dict[str, list[DocumentScore]] = {}
    for score in scores:
        by_scenario.setdefault(score.scenario, []).append(score)
    report = Report(
        split=split,
        config=config_name,
        models=[tier.model for tier in config.tiers],
        prompt_id=config.prompt_id,
        verify=config.verify,
        summary=summarise(scores),
        by_scenario={name: summarise(members) for name, members in sorted(by_scenario.items())},
        by_group={name: summarise(members) for name, members in _groups(scores).items()},
        documents=scores,
    )
    return report, client


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a pipeline configuration on a split.")
    parser.add_argument("--split", choices=("dev", "test", "confirm"), default="dev")
    parser.add_argument("--config", choices=sorted(CONFIGS), default="cascade")
    parser.add_argument("--replay", action="store_true", help="answer from the cassette only")
    parser.add_argument("--record", action="store_true", help="ask the model again for everything")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--cassettes", type=Path, default=Path("evals/cassettes"))
    parser.add_argument("--out", type=Path, default=Path("evals/reports"))
    parser.add_argument("--only", nargs="*", help="document ids to run")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args()

    mode: Mode = "replay" if arguments.replay else "record" if arguments.record else "auto"
    try:
        report, client = evaluate(
            arguments.split,
            arguments.config,
            data=arguments.data,
            cassettes=arguments.cassettes,
            mode=mode,
            only=set(arguments.only) if arguments.only else None,
            limit=arguments.limit,
            progress=not arguments.quiet,
        )
    except CassetteMiss as miss:
        print(
            f"replay failed: {miss}. Run without --replay against a model server.", file=sys.stderr
        )
        return 2

    partial = bool(arguments.only or arguments.limit)
    if not partial:
        write_report(report, arguments.out)
    summary = report.summary
    print(
        json.dumps(
            {
                "split": report.split,
                "config": report.config,
                "documents": summary.documents,
                "harmful": summary.harmful.count,
                "automation": summary.automation.value,
                "approval_precision": summary.approval_precision.value,
                "stopped": summary.stopped.value,
                "critical_correct": summary.critical_correct.value,
                "lines_correct": summary.lines_correct.value,
                "escalated": summary.escalated.value,
                "seconds_mean": summary.seconds_mean,
                "model_calls": client.calls,
                "cassette_hits": client.hits,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
