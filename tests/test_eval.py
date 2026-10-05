"""The dataset generator, the scoring, and the evaluation run with its cassette."""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from countersign.datagen.build import PLAN, Builder, reference_data
from countersign.domain.schema import CRITICAL_FIELDS, Invoice, Line
from countersign.eval import charts, compare, gate
from countersign.eval import run as eval_run
from countersign.eval.dataset import Sample, load_samples
from countersign.eval.metrics import (
    SCORED_FIELDS,
    Report,
    lines_match,
    percentile,
    rate,
    score_document,
    score_fields,
    summarise,
)
from countersign.eval.report import percent, to_markdown, write_report
from countersign.eval.run import CONFIGS, EVAL_TODAY, LARGE, SMALL, MemoryLedger, evaluate
from countersign.llm.cassette import CassetteMiss
from countersign.llm.client import ModelRequest, ModelResponse
from countersign.llm.prompts import DEFAULT_PROMPT
from countersign.parsing.pdf import parse_pdf
from countersign.pipeline.process import Attempt, PipelineConfig, Result

MINI_PLAN = {
    "clean": 6,
    "credit_note": 1,
    "einvoice": 1,
    "einvoice_tampered": 1,
    "scan": 1,
    "totals_mismatch": 2,
    "bank_changed": 1,
    "unknown_supplier": 1,
    "purchase_order": 1,
    "duplicate": 1,
    "not_invoice": 2,
    "missing_field": 1,
    "injection": 2,
}


@pytest.fixture(scope="module")
def mini(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small dataset with every kind of scenario, and the reference data to check it."""
    root = tmp_path_factory.mktemp("mini")
    builder = Builder("dev")
    builder.build(root / "dataset" / "dev", MINI_PLAN)
    reference = root / "reference"
    reference.mkdir()
    for name, content in reference_data(builder.purchase_orders).items():
        (reference / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    return root


class Oracle:
    """A model that answers with the ground truth of the document it is asked about."""

    def __init__(self, samples: list[Sample]) -> None:
        self.truth = {sample.id: sample.truth for sample in samples}
        self.calls = 0

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        truth = self.truth[request.label]
        reply: dict[str, Any] = json.loads(truth.model_dump_json())
        for field in ("total_net", "total_tax", "total_gross", "allowance_total", "charge_total"):
            reply[field] = float(reply[field]) if reply[field] is not None else None
        for line in reply["lines"]:
            for field in ("quantity", "unit_price", "amount", "vat_rate"):
                line[field] = float(line[field]) if line[field] is not None else None
        reply["vat_breakdown"] = [
            {"rate": float(row["rate"]), "tax": float(row["tax"])} for row in reply["vat_breakdown"]
        ]
        return ModelResponse(
            content=json.dumps(reply),
            model=request.model,
            prompt_tokens=1000,
            output_tokens=300,
            duration_s=4.0,
        )


# --------------------------------------------------------------------------- dataset


def test_a_dataset_is_rebuilt_identically(mini: Path, tmp_path: Path) -> None:
    again = Builder("dev")
    again.build(tmp_path / "dev", MINI_PLAN)
    first = mini / "dataset" / "dev"
    assert (first / "truth.jsonl").read_bytes() == (tmp_path / "dev" / "truth.jsonl").read_bytes()
    for pdf in sorted(first.glob("*.pdf")):
        assert pdf.read_bytes() == (tmp_path / "dev" / pdf.name).read_bytes(), pdf.name


def test_the_two_splits_do_not_share_documents(tmp_path: Path) -> None:
    plan = {"clean": 4}
    dev = Builder("dev").build(tmp_path / "dev", plan)
    test = Builder("test").build(tmp_path / "test", plan)
    assert [sample.id for sample in dev] == ["D-001", "D-002", "D-003", "D-004"]
    assert [sample.id[0] for sample in test] == ["T"] * 4
    numbers = lambda samples: {(s.vendor_key, s.truth.invoice_number) for s in samples}  # noqa: E731
    assert not numbers(dev) & numbers(test)
    assert not any(sample.held_out for sample in dev)


def test_every_scenario_is_labelled_with_what_a_correct_system_does(mini: Path) -> None:
    samples = load_samples(mini / "dataset" / "dev")
    assert len(samples) == sum(MINI_PLAN.values())
    by_scenario: dict[str, list[Sample]] = {}
    for sample in samples:
        by_scenario.setdefault(sample.scenario, []).append(sample)
    assert set(by_scenario) == set(MINI_PLAN)

    for scenario in ("clean", "credit_note", "einvoice", "scan"):
        assert {s.expected_outcome for s in by_scenario[scenario]} == {"approved"}, scenario
    for scenario, reason in (
        ("totals_mismatch", "arithmetic"),
        ("bank_changed", "bank_details"),
        ("unknown_supplier", "supplier"),
        ("purchase_order", "purchase_order"),
        ("missing_field", "missing_field"),
    ):
        assert {(s.expected_outcome, s.expected_reason) for s in by_scenario[scenario]} == {
            ("review", reason)
        }
    assert {s.expected_outcome for s in by_scenario["duplicate"]} == {"duplicate"}
    assert {s.expected_outcome for s in by_scenario["not_invoice"]} == {"rejected"}
    assert all(s.truth.document_type == "other" for s in by_scenario["not_invoice"])
    assert all(s.vendor_id is None for s in by_scenario["unknown_supplier"])
    assert all(s.is_scan for s in by_scenario["scan"])
    assert all(
        s.has_embedded_xml for s in by_scenario["einvoice"] + by_scenario["einvoice_tampered"]
    )


def test_a_duplicate_comes_after_the_invoice_it_repeats(mini: Path) -> None:
    samples = load_samples(mini / "dataset" / "dev")
    duplicate = next(sample for sample in samples if sample.scenario == "duplicate")
    key = (duplicate.vendor_key, duplicate.truth.invoice_number)
    positions = [i for i, s in enumerate(samples) if (s.vendor_key, s.truth.invoice_number) == key]
    assert len(positions) == 2
    assert samples[positions[0]].scenario == "clean"
    assert samples[positions[1]] is duplicate


def test_clean_documents_are_internally_consistent(mini: Path) -> None:
    for sample in load_samples(mini / "dataset" / "dev"):
        truth = sample.truth
        if sample.expected_outcome != "approved" or truth.document_type == "other":
            continue
        assert truth.total_net is not None
        assert truth.total_tax is not None
        lines = sum((line.amount or 0 for line in truth.lines), Decimal(0))
        assert (
            lines - (truth.allowance_total or 0) + (truth.charge_total or 0) == truth.total_net
        ), sample.id
        assert truth.total_net + truth.total_tax == truth.total_gross, sample.id
        assert sum((row.tax or 0 for row in truth.vat_breakdown), Decimal(0)) == truth.total_tax, (
            sample.id
        )


def test_the_truth_of_a_text_document_is_what_its_page_prints(mini: Path) -> None:
    directory = mini / "dataset" / "dev"
    for sample in load_samples(directory):
        truth = sample.truth
        if sample.is_scan or truth.document_type == "other":
            continue
        text = parse_pdf((directory / sample.file).read_bytes()).text
        squeezed = "".join(text.split())
        if truth.invoice_number:
            assert truth.invoice_number in squeezed.upper(), sample.id
        if truth.supplier_iban:
            assert truth.supplier_iban in squeezed, sample.id


def test_the_plans_hold_out_layouts_and_languages_for_the_test_split() -> None:
    assert set(PLAN["dev"]) == set(PLAN["test"])
    dev = Builder("dev")
    test = Builder("test")
    assert {vendor.spec.layout for vendor in dev.known} == {"classic", "columns", "ledger", "anglo"}
    assert {vendor.spec.language for vendor in dev.known} == {"fr", "en"}
    assert {vendor.spec.layout for vendor in test.known} - {
        vendor.spec.layout for vendor in dev.known
    } == {
        "footer_ids",
        "german",
        "compact",
    }
    assert {vendor.spec.language for vendor in test.known} == {"fr", "en", "de", "es", "it"}


@pytest.mark.parametrize("split", ["dev", "test", "confirm"])
def test_the_committed_dataset_is_the_one_the_generator_builds(split: str, tmp_path: Path) -> None:
    """Guards against a dataset edited by hand, or a generator that drifted from it.

    The ground truth is compared byte for byte. The PDF files are compared by name: their
    bytes depend on the compression library and the rasteriser of the platform.
    """
    committed = Path("data/dataset") / split
    if not committed.exists():
        pytest.skip("dataset not built")
    Builder(split).build(tmp_path / split, PLAN[split])  # type: ignore[arg-type]
    built = sorted(path.name for path in (tmp_path / split).iterdir())
    assert built == sorted(path.name for path in committed.iterdir())
    assert len(built) == sum(PLAN[split].values()) + 1  # the documents and their ground truth
    truth = "truth.jsonl"
    assert (tmp_path / split / truth).read_bytes() == (committed / truth).read_bytes()


# --------------------------------------------------------------------------- scoring


def invoice(**values: Any) -> Invoice:
    base: dict[str, Any] = {
        "document_type": "invoice",
        "invoice_number": "FA-1",
        "currency": "EUR",
        "total_net": Decimal("100.00"),
        "total_tax": Decimal("20.00"),
        "total_gross": Decimal("120.00"),
        "lines": [
            Line(
                description="x",
                quantity=Decimal(2),
                unit_price=Decimal("50"),
                amount=Decimal("100"),
            )
        ],
    }
    return Invoice(**{**base, **values})


def sample(**values: Any) -> Sample:
    base: dict[str, Any] = {
        "id": "D-001",
        "file": "D-001.pdf",
        "split": "dev",
        "scenario": "clean",
        "vendor_key": "forez",
        "vendor_id": "V-1002",
        "layout": "columns",
        "language": "fr",
        "held_out": False,
        "expected_outcome": "approved",
        "truth": invoice(),
    }
    return Sample(**{**base, **values})


def result(
    outcome: str,
    got: Invoice | None = None,
    reasons: list[str] | None = None,
    vendor_id: str | None = "V-1002",
) -> Result:
    attempts = [
        Attempt(
            tier="small",
            mode="text",
            model="m",
            invoice=got,
            vendor_id=vendor_id,
            raw=None,
            duration_s=3.0,
        )
    ]
    return Result(outcome=outcome, reasons=reasons or [], mode="text", attempts=attempts, final=0)  # type: ignore[arg-type]


def test_fields_are_compared_exactly() -> None:
    truth = invoice()
    assert all(score_fields(truth, invoice()).values())
    assert score_fields(truth, invoice(total_gross=Decimal("120")))["total_gross"]  # 120 is 120.00
    assert not score_fields(truth, invoice(total_gross=Decimal("120.004")))["total_gross"]
    assert not score_fields(truth, invoice(invoice_number="FA-2"))["invoice_number"]
    assert set(score_fields(truth, truth)) == set(SCORED_FIELDS)
    assert set(CRITICAL_FIELDS) <= set(SCORED_FIELDS)


def test_lines_are_compared_as_a_multiset() -> None:
    a = Line(description="a", quantity=Decimal(1), unit_price=Decimal("10"), amount=Decimal("10"))
    b = Line(description="b", quantity=Decimal(2), unit_price=Decimal("5.50"), amount=Decimal("11"))
    assert lines_match(invoice(lines=[a, b]), invoice(lines=[b, a]))
    assert lines_match(
        invoice(lines=[a]), invoice(lines=[a.model_copy(update={"description": "other"})])
    )
    assert not lines_match(invoice(lines=[a, b]), invoice(lines=[a]))
    assert not lines_match(
        invoice(lines=[a]), invoice(lines=[a.model_copy(update={"quantity": Decimal(3)})])
    )


def test_a_correct_approval_is_harmless() -> None:
    score = score_document(sample(), result("approved", invoice()))
    assert (score.harm, score.as_expected, score.acceptable, score.critical_correct) == (
        None,
        True,
        True,
        True,
    )


def test_an_approval_with_a_wrong_critical_field_is_a_wrong_approval() -> None:
    score = score_document(sample(), result("approved", invoice(total_gross=Decimal("1200.00"))))
    assert score.harm == "wrong_approval"
    assert score.fields is not None
    assert not score.fields["total_gross"]


def test_an_approval_under_another_suppliers_record_is_a_wrong_approval() -> None:
    """Every field is right, and the payment would go to the account of someone else."""
    score = score_document(sample(), result("approved", invoice(), vendor_id="V-1099"))
    assert (score.critical_correct, score.supplier_correct) == (True, False)
    assert score.harm == "wrong_approval"
    assert score_document(sample(), result("review", invoice(), vendor_id=None)).harm is None


def test_approving_a_document_that_had_to_be_stopped_is_a_wrong_approval() -> None:
    must_stop = sample(
        scenario="bank_changed", expected_outcome="review", expected_reason="bank_details"
    )
    approved = score_document(must_stop, result("approved", invoice()))
    assert (approved.harm, approved.reason_found) == ("wrong_approval", False)
    stopped = score_document(must_stop, result("review", invoice(), ["bank_details"]))
    assert (stopped.harm, stopped.reason_found) == (None, True)
    other_reason = score_document(must_stop, result("review", invoice(), ["arithmetic"]))
    assert (other_reason.harm, other_reason.as_expected, other_reason.reason_found) == (
        None,
        True,
        False,
    )


def test_reviewing_a_good_document_costs_time_not_money() -> None:
    score = score_document(sample(), result("review", invoice(), ["arithmetic"]))
    assert (score.harm, score.as_expected, score.acceptable) == (None, False, False)
    scan = sample(scenario="scan", acceptable_outcomes=["review"])
    assert score_document(scan, result("review", invoice(), ["consensus"])).acceptable


def test_setting_a_real_invoice_aside_is_a_lost_invoice() -> None:
    assert score_document(sample(), result("rejected")).harm == "lost_invoice"
    assert score_document(sample(), result("duplicate", invoice())).harm == "lost_invoice"
    quote = sample(
        scenario="not_invoice",
        expected_outcome="rejected",
        acceptable_outcomes=["review"],
        truth=Invoice(document_type="other"),
    )
    assert score_document(quote, result("rejected")).harm is None
    assert score_document(quote, result("review")).harm is None
    assert score_document(quote, result("approved", invoice())).harm == "wrong_approval"


def test_a_document_nobody_could_read_counts_every_field_wrong() -> None:
    unread = Result(outcome="review", reasons=["extraction_failed"], mode="text")
    score = score_document(sample(), unread)
    assert score.critical_correct is False
    assert score.harm is None


def test_rates_carry_a_wilson_interval() -> None:
    half = rate(50, 100)
    assert (half.value, half.low, half.high) == (0.5, 0.4038, 0.5962)
    perfect = rate(20, 20)
    assert perfect.value == 1.0
    assert perfect.high == 1.0
    assert perfect.low == pytest.approx(0.839, abs=0.001)  # 20 out of 20 is not proof of 100 %
    none = rate(0, 30)
    assert (none.value, none.low) == (0.0, 0.0)
    assert none.high == pytest.approx(0.114, abs=0.001)
    empty = rate(0, 0)
    assert (empty.value, empty.low, empty.high) == (None, None, None)
    assert percent(empty) == "n/a"
    assert percent(half) == "50.0 % (50/100)"
    assert percent(half, interval=True) == "50.0 % [40.4 to 59.6] (50/100)"


def test_percentiles() -> None:
    assert percentile([], 0.5) == 0.0
    assert percentile([4.0], 0.95) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0, 100.0], 0.95) == pytest.approx(80.8)


def test_a_summary_counts_what_matters() -> None:
    scores = [
        score_document(sample(id="1"), result("approved", invoice())),
        score_document(sample(id="2"), result("approved", invoice(total_gross=Decimal("1.00")))),
        score_document(sample(id="3"), result("review", invoice(), ["arithmetic"])),
        score_document(
            sample(
                id="4",
                scenario="bank_changed",
                expected_outcome="review",
                expected_reason="bank_details",
            ),
            result("review", invoice(), ["bank_details"]),
        ),
    ]
    summary = summarise(scores)
    assert summary.documents == 4
    assert (summary.harmful.count, summary.wrong_approvals, summary.lost_invoices) == (1, 1, 0)
    assert (summary.automation.count, summary.automation.total) == (1, 3)
    assert (summary.approval_precision.count, summary.approval_precision.total) == (1, 2)
    assert (summary.stopped.count, summary.stopped.total) == (1, 1)
    assert (summary.reason_found.count, summary.reason_found.total) == (1, 1)
    assert (summary.critical_correct.count, summary.critical_correct.total) == (3, 4)
    assert summary.field_accuracy["total_gross"].count == 3
    assert summary.seconds_mean == 3.0
    assert summarise([]).documents == 0


def test_a_reader_that_stops_nothing_did_not_find_the_reasons() -> None:
    """Approving what had to be stopped must not leave the reasons at 100 %."""
    labelled = sample(
        scenario="bank_changed", expected_outcome="review", expected_reason="bank_details"
    )
    scores = [
        score_document(labelled, result("approved", invoice())),
        score_document(labelled, result("approved", invoice())),
        score_document(labelled, result("review", invoice(), ["bank_details"])),
    ]
    summary = summarise(scores)
    assert (summary.stopped.count, summary.stopped.total) == (1, 3)
    assert (summary.reason_found.count, summary.reason_found.total) == (1, 3)


# ------------------------------------------------------------------------------- runs


def run(mini: Path, cassettes: Path, name: str = "cascade", **options: Any) -> Any:
    samples = load_samples(mini / "dataset" / "dev")
    options.setdefault("mode", "auto")
    if options["mode"] != "replay":
        options.setdefault("model", Oracle(samples))
    return evaluate("dev", name, data=mini, cassettes=cassettes, **options)


def test_a_perfect_reader_behind_the_checks_makes_no_harmful_decision(
    mini: Path, tmp_path: Path
) -> None:
    report, client = run(mini, tmp_path)
    summary = report.summary
    assert summary.documents == sum(MINI_PLAN.values())
    assert summary.harmful.count == 0
    assert summary.stopped.value == 1.0
    assert summary.automation.value == 1.0
    assert summary.as_expected.value == 1.0
    # The one extraction that differs from the page is the forged embedded invoice,
    # which is read as data, found to disagree with the page, and stopped.
    misread = [document for document in report.documents if document.critical_correct is False]
    assert [(document.scenario, document.outcome) for document in misread] == [
        ("einvoice_tampered", "review")
    ]
    assert set(report.by_scenario) == set(MINI_PLAN)
    assert {"seen suppliers", "text layer", "scans", "embedded e-invoice"} <= set(report.by_group)
    assert report.models == [SMALL.model, LARGE.model]
    assert client.calls > 0
    by_id = {document.id: document for document in report.documents}
    embedded = next(d for d in report.documents if d.scenario == "einvoice")
    assert (embedded.mode, embedded.model_seconds, embedded.tiers) == (
        "embedded",
        0.0,
        ["embedded-xml"],
    )
    scan = next(d for d in report.documents if d.scenario == "scan")
    assert (scan.mode, scan.tiers) == ("vision", ["small", "large"])
    assert all(by_id[d.id].reason_found for d in report.documents if d.reason_found is not None)


def test_without_checks_the_same_reader_approves_what_had_to_be_stopped(
    mini: Path, tmp_path: Path
) -> None:
    report, _ = run(mini, tmp_path, "small-unverified")
    summary = report.summary
    # Nearly every field is read correctly, and documents that had to be stopped are
    # approved all the same: reading well is not the same as deciding well.
    assert summary.critical_correct.value is not None
    assert summary.critical_correct.value > 0.9
    assert summary.wrong_approvals > 0
    assert summary.stopped.value is not None
    assert summary.stopped.value < 1.0
    harmed = {document.scenario for document in report.documents if document.harm}
    assert {"totals_mismatch", "bank_changed", "unknown_supplier"} <= harmed


def test_a_replay_reproduces_the_run_without_the_model(mini: Path, tmp_path: Path) -> None:
    live, _ = run(mini, tmp_path)
    replayed, client = run(mini, tmp_path, mode="replay")
    assert replayed == live
    assert client.calls == 0
    assert client.hits > 0
    assert (
        write_report(live, tmp_path / "a").read_bytes()
        == write_report(replayed, tmp_path / "b").read_bytes()
    )
    assert (tmp_path / "a" / "dev-cascade.json").read_bytes() == (
        tmp_path / "b" / "dev-cascade.json"
    ).read_bytes()


def test_a_replay_refuses_to_answer_for_a_prompt_that_was_not_recorded(
    mini: Path, tmp_path: Path
) -> None:
    run(mini, tmp_path)
    changed = PipelineConfig(tiers=(SMALL, LARGE), prompt_id="extract_v2")
    with pytest.raises(CassetteMiss):
        run(mini, tmp_path, mode="replay", config=changed)


def test_a_run_can_be_limited_to_some_documents(mini: Path, tmp_path: Path) -> None:
    report, _ = run(mini, tmp_path, only={"D-001", "D-003"})
    assert [document.id for document in report.documents] == ["D-001", "D-003"]
    report, _ = run(mini, tmp_path, limit=5)
    assert len(report.documents) == 5


def test_the_markdown_report_names_harmful_and_unexpected_documents(
    mini: Path, tmp_path: Path
) -> None:
    report, _ = run(mini, tmp_path, "small-unverified")
    text = to_markdown(report)
    assert text.startswith("# Evaluation: `small-unverified` on the `dev` split")
    assert "Checks: off." in text
    assert "## Harmful decisions" in text
    harmful = next(document for document in report.documents if document.harm)
    assert f"| {harmful.id} |" in text
    clean, _ = run(mini, tmp_path)
    assert "## Harmful decisions\n\nNone." in to_markdown(clean)


def test_named_configurations() -> None:
    assert {"small-unverified", "large-unverified", "small", "large", "cascade"} <= set(CONFIGS)
    assert CONFIGS["prompt-v2"].prompt_id == "extract_v2"
    assert CONFIGS["small"].prompt_id == DEFAULT_PROMPT
    assert [tier.name for tier in CONFIGS["cascade"].tiers] == ["small", "large"]
    assert not CONFIGS["small-unverified"].verify
    assert EVAL_TODAY.isoformat() == "2026-07-01"


def test_the_ledger_of_a_run_remembers_what_was_taken_in() -> None:
    ledger = MemoryLedger()
    ledger.record("D-001", result("approved", invoice(), vendor_id=None))
    assert ledger.find("V-1002", "FA-1") is None  # no supplier was matched in this result
    matched = result("approved", invoice(issue_date=date(2026, 3, 14)))
    ledger.record("D-001", matched)
    ledger.record("D-009", matched)
    prior = ledger.find("V-1002", "FA-1")
    assert prior is not None
    assert (prior.document_id, prior.total_gross) == ("D-001", Decimal("120.00"))
    assert (prior.issue_date, prior.rejected_by) == (date(2026, 3, 14), None)
    ledger.record("D-010", result("rejected", invoice(invoice_number="FA-2")))
    assert ledger.find("V-1002", "FA-2") is None


# ------------------------------------------------------------- gate, tables, figure


def committed(mini: Path, root: Path, *names: str) -> Path:
    """Run configurations on the mini dataset and write their reports, as committed."""
    reports = root / "reports"
    for name in names:
        report, _ = run(mini, root / "cassettes", name)
        write_report(report, reports)
    return reports


def test_the_gate_accepts_reports_that_replay_identically(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade", "small-unverified")
    assert gate.stale_reports(reports, mini, tmp_path / "cassettes") == []


def test_the_gate_rejects_a_report_that_no_longer_matches_the_code(
    mini: Path, tmp_path: Path
) -> None:
    reports = committed(mini, tmp_path, "cascade")
    path = reports / "dev-cascade.json"
    report = Report.model_validate_json(path.read_text(encoding="utf-8"))
    report.documents[0].outcome = (
        "review" if report.documents[0].outcome == "approved" else "approved"
    )
    path.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    problems = gate.stale_reports(reports, mini, tmp_path / "cassettes")
    assert len(problems) == 1
    assert "dev-cascade.json is out of date" in problems[0]
    assert report.documents[0].id in problems[0]


def test_the_gate_rejects_a_page_that_is_not_what_its_report_renders_to(
    mini: Path, tmp_path: Path
) -> None:
    reports = committed(mini, tmp_path, "cascade")
    page = reports / "dev-cascade.md"
    page.write_text(page.read_text(encoding="utf-8").replace("0", "1", 1), encoding="utf-8")
    problems = gate.stale_reports(reports, mini, tmp_path / "cassettes")
    assert problems == ["dev-cascade.md is not the page dev-cascade.json renders to"]
    page.unlink()
    assert len(gate.stale_reports(reports, mini, tmp_path / "cassettes")) == 1


def test_the_gate_fails_without_its_thresholds(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade")
    problems = gate.broken_thresholds(reports, tmp_path / "missing.json")
    assert len(problems) == 1
    assert "no thresholds file" in problems[0]


def test_the_gate_rejects_a_report_whose_answers_were_not_recorded(
    mini: Path, tmp_path: Path
) -> None:
    reports = committed(mini, tmp_path, "cascade")
    for cassette in (tmp_path / "cassettes" / "dev").glob("*.jsonl"):
        cassette.unlink()
    problems = gate.stale_reports(reports, mini, tmp_path / "cassettes")
    assert len(problems) == 1
    assert "cannot be replayed" in problems[0]


def test_the_gate_rejects_a_report_of_an_unknown_configuration(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade")
    path = reports / "dev-cascade.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"config": "cascade"', '"config": "gone"'), "utf-8"
    )
    assert "unknown configuration" in gate.stale_reports(reports, mini, tmp_path / "cassettes")[0]


def test_thresholds_are_held(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade", "small-unverified")
    limits = tmp_path / "thresholds.json"
    limits.write_text(
        json.dumps(
            {
                "dev-cascade": {"harmful_max": 0, "automation_min": 0.9, "stopped_min": 1.0},
                "dev-small-unverified": {"harmful_max": 0, "stopped_min": 0.9},
                "dev-large": {"harmful_max": 0},
            }
        ),
        encoding="utf-8",
    )
    problems = gate.broken_thresholds(reports, limits)
    assert len(problems) == 3
    assert any(problem.startswith("dev-small-unverified: harmful is") for problem in problems)
    assert any(problem.startswith("dev-small-unverified: stopped is") for problem in problems)
    assert any(
        "dev-large: a threshold is set but there is no report" in problem for problem in problems
    )


def test_comparison_tables(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade", "small-unverified", "small")
    loaded = compare.load(reports, "dev", ("cascade", "small-unverified", "small", "large"))
    assert set(loaded) == {"cascade", "small-unverified", "small"}

    table = compare.configurations(loaded).splitlines()
    assert len(table) == 2 + 3
    assert table[0].startswith("| Configuration | Harmful decisions")
    cascade = next(line for line in table if "Cascade" in line)
    assert "| 0 (0 + 0) |" in cascade
    assert "100.0 %" in cascade
    unverified = next(line for line in table if "nothing checked" in line)
    assert "| 0 (0 + 0) |" not in unverified

    assert "| scans |" in compare.groups(loaded["cascade"])
    assert "| totals_mismatch |" in compare.scenarios(loaded["cascade"])
    readers = compare.tiers(loaded["cascade"])
    assert "| small |" in readers
    assert "| embedded-xml |" in readers
    assert "v5" in compare.prompts(loaded)
    assert compare.share(rate(0, 0)) == "n/a"
    assert compare.share(rate(1, 4)) == "25.0 % (1/4)"


def test_tables_are_written_into_a_page_between_their_markers(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade", "small")
    history = tmp_path / "history"
    history.mkdir()
    for report in reports.glob("dev-*.json"):
        (history / report.name.replace("dev-", "test-")).write_bytes(report.read_bytes())
    page = tmp_path / "page.md"
    page.write_text(
        "Before.\n\n<!-- table:configurations:dev -->\nstale\n<!-- /table -->\n\n"
        "<!-- table:tiers:dev -->\n<!-- /table -->\n\n"
        "<!-- table:configurations:test-run -->\n<!-- /table -->\nAfter.\n",
        encoding="utf-8",
    )
    assert compare.update((page,), reports, history) == 3
    text = page.read_text(encoding="utf-8")
    loaded = compare.load(reports, "dev", ("small", "cascade"))
    assert "stale" not in text
    assert text.count(compare.configurations(loaded)) == 2  # the split, and its first run
    assert compare.tiers(loaded["cascade"]) in text
    assert text.startswith("Before.\n")
    assert text.endswith("After.\n")

    compare.update((page,), reports, history)
    assert page.read_text(encoding="utf-8") == text


def test_the_figure_counts_each_document_once_and_is_written(mini: Path, tmp_path: Path) -> None:
    reports = committed(mini, tmp_path, "cascade", "small-unverified")
    loaded = compare.load(reports, "dev", ("cascade", "small-unverified"))
    for report in loaded.values():
        tally = charts.counts(report)
        assert sum(tally.values()) == len(report.documents)
    assert charts.counts(loaded["cascade"])["harmful"] == 0
    assert charts.counts(loaded["small-unverified"])["harmful"] > 0

    for theme in charts.THEMES:
        target = tmp_path / f"figure-{theme.name}.svg"
        charts.draw(loaded, "dev", theme, target)
        assert target.read_text(encoding="utf-8").lstrip().startswith("<?xml")
        assert "<svg" in target.read_text(encoding="utf-8")


# --------------------------------------------------------------------- command lines


def test_the_evaluation_commands_end_to_end(
    mini: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cassettes, reports = tmp_path / "cassettes", tmp_path / "reports"
    run(mini, cassettes)  # record what the cascade asks
    common = ["--data", str(mini), "--cassettes", str(cassettes)]

    def call(module: Any, *arguments: str) -> int:
        monkeypatch.setattr(sys, "argv", [module.__name__, *arguments])
        code: int = module.main()
        return code

    replay = ["--split", "dev", "--replay", "--quiet", "--out", str(reports), *common]
    assert call(eval_run, "--config", "cascade", *replay) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["harmful"], printed["model_calls"]) == (0, 0)
    assert (reports / "dev-cascade.json").exists()
    assert (reports / "dev-cascade.md").exists()

    assert call(eval_run, "--config", "prompt-v1", *replay) == 2  # never recorded
    assert "replay failed" in capsys.readouterr().err
    assert call(eval_run, "--config", "cascade", "--limit", "3", *replay) == 0  # partial: no report
    capsys.readouterr()

    limits = tmp_path / "thresholds.json"
    limits.write_text(json.dumps({"dev-cascade": {"harmful_max": 0}}), encoding="utf-8")
    gate_arguments = ["--reports", str(reports), "--thresholds", str(limits), *common]
    assert call(gate, *gate_arguments) == 0
    assert "1 reports recomputed" in capsys.readouterr().out
    limits.write_text(json.dumps({"dev-cascade": {"automation_min": 1.1}}), encoding="utf-8")
    assert call(gate, *gate_arguments) == 1
    assert "FAIL dev-cascade: automation" in capsys.readouterr().err
    assert (
        call(gate, "--reports", str(tmp_path / "nothing"), "--thresholds", str(limits), *common)
        == 2
    )
    capsys.readouterr()

    assert call(compare, "--reports", str(reports), "--split", "dev") == 0
    assert "## Cascade by scenario" in capsys.readouterr().out
    assert call(compare, "--reports", str(reports), "--split", "test") == 2
    figures = tmp_path / "img"
    assert call(charts, "--reports", str(reports), "--split", "dev", "--out", str(figures)) == 0
    assert sorted(path.name for path in figures.iterdir()) == [
        "outcomes-dark.svg",
        "outcomes-light.svg",
    ]
    assert call(charts, "--reports", str(reports), "--split", "test", "--out", str(figures)) == 2
