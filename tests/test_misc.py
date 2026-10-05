"""Locale inference, tracing, logging, the command line and the reference data."""

import gc
import json
import logging
import warnings
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError
from sqlalchemy import select

from countersign import cli
from countersign.config import Settings, get_settings
from countersign.datagen.build import Builder
from countersign.datagen.render import render_pdf
from countersign.domain.schema import RawExtraction, RawLine
from countersign.eval.run import EVAL_TODAY
from countersign.master import MasterData
from countersign.obs.logging import JsonFormatter, configure_logging
from countersign.obs.tracing import configure_tracing
from countersign.pipeline.normalise import infer_day_first, infer_decimal_separator, normalise
from countersign.pipeline.process import Pipeline
from countersign.store.db import create_db_engine, create_schema, session_factory, transaction
from countersign.store.models import Document
from tests.support import (
    LARGE_MODEL,
    SMALL_MODEL,
    TODAY,
    ScriptedModel,
    invoice_data,
    master_data,
    perfect_reply,
)

# ------------------------------------------------------------------ document locale


def raw(**values: Any) -> RawExtraction:
    return RawExtraction(document_type="invoice", **values)


def test_the_decimal_separator_is_voted_by_the_unambiguous_numbers() -> None:
    french = raw(
        total_net="1 234,56",
        total_gross="1 481,47",
        lines=[RawLine(quantity="1.250", amount="12,00")],
    )
    assert infer_decimal_separator(french) == ","
    british = raw(total_net="1,234.56", total_gross="1,481.47")
    assert infer_decimal_separator(british) == "."
    assert infer_decimal_separator(raw(total_net="1.250", total_gross="12")) is None
    assert infer_decimal_separator(raw(total_net="1,50", total_gross="1.50")) is None  # a tie


def test_an_ambiguous_quantity_follows_the_document() -> None:
    german = raw(
        total_net="2.500,00",
        lines=[RawLine(description="Stahl", quantity="1.250", amount="2.500,00")],
    )
    assert normalise(german).invoice.lines[0].quantity == Decimal("1250")
    british = raw(
        total_net="2,500.00",
        lines=[RawLine(description="Steel", quantity="1.250", amount="2,500.00")],
    )
    assert normalise(british).invoice.lines[0].quantity == Decimal("1.250")


def test_day_first_comes_from_a_date_that_can_only_be_read_one_way() -> None:
    european = raw(issue_date="03/04/2026", due_date="18/04/2026")
    american = raw(issue_date="03/04/2026", due_date="04/18/2026")
    assert infer_day_first(european, None, None) == (True, False)
    assert infer_day_first(american, None, None) == (False, False)
    # What the document itself says wins over the supplier's country and the page.
    assert infer_day_first(american, "31/12/2025", "FR") == (False, False)


def test_day_first_comes_from_the_page_for_a_supplier_that_is_not_on_file() -> None:
    extraction = raw(issue_date="03/04/2026")
    page = "Order of 12/31/2025, shipped 01/05/2026"
    assert infer_day_first(extraction, page, None) == (False, False)
    assert infer_day_first(extraction, "Commande du 31/12/2025", None) == (True, False)


def test_the_page_and_the_suppliers_country_must_not_contradict_each_other() -> None:
    extraction = raw(issue_date="03/04/2026")
    american = "Order of 12/31/2025, shipped 01/05/2026"
    assert infer_day_first(extraction, american, "US") == (False, False)
    assert infer_day_first(extraction, american, "FR") == (True, True)  # disputed
    assert infer_day_first(extraction, "Commande du 31/12/2025", "FR") == (True, False)

    disputed = normalise(extraction, text=american, vendor_country="FR")
    assert disputed.ambiguous == ("issue_date",)
    assert disputed.invoice.issue_date == date(2026, 4, 3)
    # A date that can only be read one way is never in dispute.
    clear = normalise(raw(issue_date="23/04/2026"), text=american, vendor_country="FR")
    assert clear.ambiguous == ()


def test_day_first_comes_from_the_payment_term_when_both_dates_are_ambiguous() -> None:
    # Read month first, the invoice is due a month after its date; day first, before it.
    american = raw(issue_date="03/04/2026", due_date="04/03/2026")
    assert infer_day_first(american, None, None) == (False, False)
    european = raw(issue_date="04/03/2026", due_date="03/04/2026")
    assert infer_day_first(european, None, None) == (True, False)


def test_day_first_falls_back_on_the_suppliers_country() -> None:
    lonely = raw(issue_date="03/04/2026")
    assert infer_day_first(lonely, None, "US") == (False, False)
    assert infer_day_first(lonely, None, "FR") == (True, False)
    assert infer_day_first(lonely, None, None) == (True, False)
    assert normalise(lonely, vendor_country="US").invoice.issue_date == date(2026, 3, 4)
    assert normalise(lonely, vendor_country="FR").invoice.issue_date == date(2026, 4, 3)


def test_normalisation_reports_what_it_could_not_read() -> None:
    result = normalise(
        raw(
            invoice_number=" fa 2026 0187 ",
            issue_date="mid March",
            currency="pesos or so",
            supplier_vat_id="FR 44 732 829 320",
            supplier_siret="732 829 320 00074",
            supplier_iban="fr76 3000 6000 0112 3456 7890 189",
            total_net="between 100 and 120",
            total_gross="120,00 €",
            allowance_total="-5,00",
            lines=[RawLine(description=None, quantity="2 pcs", amount="n/a")],
        )
    )
    invoice = result.invoice
    assert sorted(result.unparsed) == ["currency", "issue_date", "total_net"]
    assert invoice.invoice_number == "FA20260187"
    assert invoice.supplier_vat_id == "FR44732829320"
    assert invoice.supplier_siret == "73282932000074"
    assert invoice.supplier_iban == "FR7630006000011234567890189"
    assert invoice.total_gross == Decimal("120.00")
    assert invoice.allowance_total == Decimal("5.00")  # a discount is a magnitude
    assert invoice.lines[0].description == ""
    assert invoice.lines[0].quantity == Decimal("2")
    assert invoice.lines[0].amount is None  # "n/a" is an absent value, not an unreadable one


def test_a_swiss_vat_number_drops_its_suffix() -> None:
    assert (
        normalise(raw(supplier_vat_id="CHE-265.684.389 MWST")).invoice.supplier_vat_id
        == "CHE265684389"
    )


# -------------------------------------------------------------------- reference data


def test_reference_data_is_loaded_from_a_directory(settings: Settings) -> None:
    master = MasterData.load(settings.reference_dir)
    assert master.company.name == "Orvane Industries SAS"
    assert len(master.vendors) == 24
    assert master.vendor("V-1001") is not None
    assert master.vendor("V-9999") is None
    assert master.purchase_order("PO-2026-00412") is None
    assert master.po_regex.fullmatch("PO-2026-00412")


def test_the_committed_reference_data_covers_the_committed_dataset() -> None:
    reference = Path("data/reference")
    if not reference.exists():
        pytest.skip("dataset not built")
    master = MasterData.load(reference)
    orders = json.loads((reference / "purchase_orders.json").read_text(encoding="utf-8"))
    assert len(orders) == len({order["po_number"] for order in orders})
    assert all(master.vendor(order["vendor_id"]) for order in orders)


# --------------------------------------------------------------------------- tracing


@pytest.fixture(scope="module")
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    provider.shutdown()


def test_a_document_leaves_one_trace_with_a_span_per_stage(spans: InMemorySpanExporter) -> None:
    data = invoice_data("forez")
    wrong = perfect_reply(data)
    wrong["total_gross"] += 100
    model = ScriptedModel({SMALL_MODEL: wrong, LARGE_MODEL: perfect_reply(data)})
    from countersign.eval.run import MemoryLedger
    from countersign.pipeline.process import PipelineConfig
    from tests.conftest import TIERS

    pipeline = Pipeline(PipelineConfig(tiers=TIERS), model, master_data())
    spans.clear()
    pipeline.process(render_pdf(data), ledger=MemoryLedger(), today=TODAY)

    finished = spans.get_finished_spans()
    names = [span.name for span in finished]
    assert names == [
        "countersign.parse",
        "countersign.extract",
        "countersign.verify",
        "countersign.extract",
        "countersign.verify",
        "countersign.process",
    ]
    root = finished[-1]
    assert root.attributes is not None
    assert root.attributes["countersign.outcome"] == "approved"
    assert root.attributes["countersign.attempts"] == 2
    assert {span.context.trace_id for span in finished} == {root.context.trace_id}
    assert all(span.parent is not None for span in finished[:-1])

    extract = finished[1]
    assert extract.attributes is not None
    assert extract.attributes["gen_ai.request.model"] == SMALL_MODEL
    assert extract.attributes["gen_ai.usage.input_tokens"] == 1200
    assert extract.attributes["gen_ai.usage.output_tokens"] == 400
    assert extract.attributes["countersign.tier"] == "small"
    verify = finished[2]
    assert verify.attributes is not None
    assert set(verify.attributes["countersign.checks.failed"]) == {
        "arithmetic.totals",
        "arithmetic.labelled",
        "grounding.header",
    }


def test_spans_carry_no_invoice_content(spans: InMemorySpanExporter) -> None:
    data = invoice_data("forez")
    from countersign.eval.run import MemoryLedger
    from countersign.pipeline.process import PipelineConfig
    from tests.conftest import TIERS

    pipeline = Pipeline(
        PipelineConfig(tiers=TIERS),
        ScriptedModel({SMALL_MODEL: perfect_reply(data)}),
        master_data(),
    )
    spans.clear()
    pipeline.process(render_pdf(data), ledger=MemoryLedger(), today=TODAY)
    recorded = json.dumps(
        [dict(span.attributes or {}) for span in spans.get_finished_spans()], default=str
    )
    for secret in (data.number, data.vendor.name, data.vendor.iban or "-", f"{data.gross}"):
        assert secret not in recorded


def test_tracing_is_off_without_an_endpoint_and_explains_a_missing_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert configure_tracing(None) is None
    import builtins

    real_import = builtins.__import__

    def without_exporter(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("opentelemetry.exporter"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_exporter)
    with pytest.raises(RuntimeError, match=r"countersign\[otlp\]"):
        configure_tracing("http://collector:4318/v1/traces")


# --------------------------------------------------------------------------- logging


def test_log_lines_are_json_objects_with_their_extra_fields() -> None:
    record = logging.LogRecord(
        "countersign.worker", logging.INFO, __file__, 1, "document_processed", (), None
    )
    record.document = 12
    record.outcome = "approved"
    line = json.loads(JsonFormatter().format(record))
    assert line["event"] == "document_processed"
    assert line["level"] == "INFO"
    assert line["logger"] == "countersign.worker"
    assert (line["document"], line["outcome"]) == (12, "approved")
    assert line["at"].endswith("+00:00")


def test_an_exception_is_logged_with_its_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "job_failed", (), sys.exc_info()
        )
    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exception"]


def test_configuring_logging_twice_keeps_one_handler() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("warning")
        configure_logging("INFO")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.INFO
    finally:
        root.handlers[:] = before


# -------------------------------------------------------------------------- settings


def test_api_keys_are_parsed() -> None:
    settings = Settings(
        _env_file=None, api_keys="ann:reviewer:k1, ops:operator:s3cr3t:with:colons "
    )
    assert [(key.name, key.role, key.key) for key in settings.parsed_api_keys()] == [
        ("ann", "reviewer", "k1"),
        ("ops", "operator", "s3cr3t:with:colons"),
    ]
    assert Settings(_env_file=None).parsed_api_keys() == []
    assert Settings(_env_file=None, api_keys="  ").parsed_api_keys() == []


@pytest.mark.parametrize(
    "value",
    [
        "ann:reviewer:k1-secret,nonsense",
        "ann;reviewer;k1-secret",
        "reviewer:k1-secret",
        "ann:admin:k1-secret",
        "ann:reviewer:k1-secret,",
        ":reviewer:k1-secret",
    ],
)
def test_api_keys_that_do_not_parse_entirely_stop_the_application(value: str) -> None:
    """An entry dropped in silence left fewer keys than intended, and with none left
    the API was open to everyone."""
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, api_keys=value)
    assert "api_keys" in str(raised.value)
    assert "k1-secret" not in str(raised.value)


def test_serving_an_open_api_is_refused_wherever_others_could_reach_it() -> None:
    without_keys = Settings(_env_file=None)
    for loopback in ("127.0.0.1", "localhost", "::1"):
        assert without_keys.refusal_to_serve(loopback) is None
    for exposed in ("192.0.2.10", "::", "intake.example.internal"):
        refusal = without_keys.refusal_to_serve(exposed)
        assert refusal is not None
        assert "COUNTERSIGN_API_KEYS" in refusal
    assert Settings(_env_file=None, allow_open=True).refusal_to_serve("192.0.2.10") is None
    with_keys = Settings(_env_file=None, api_keys="ann:reviewer:k1")
    assert with_keys.refusal_to_serve("192.0.2.10") is None


def test_the_lease_of_a_job_outlasts_the_slowest_document() -> None:
    """Two tiers, three tries each, every one running into the timeout, and the pauses."""
    settings = Settings(_env_file=None)
    slowest = 2 * (3 * settings.model_timeout_s + 2 + 4)
    assert settings.lease_seconds(tiers=2) > slowest > settings.job_lease_s
    assert Settings(_env_file=None, job_lease_s=7200).lease_seconds(tiers=2) == 7200
    quick = Settings(_env_file=None, model_timeout_s=10, model_retries=0)
    assert quick.lease_seconds(tiers=1) == quick.job_lease_s


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COUNTERSIGN_WORKERS", "4")
    monkeypatch.setenv("COUNTERSIGN_SMALL_MODEL", "another:1b")
    monkeypatch.setenv("COUNTERSIGN_TODAY", "2026-07-01")
    monkeypatch.setenv("COUNTERSIGN_ALLOW_OPEN", "true")
    settings = Settings(_env_file=None)
    assert (settings.workers, settings.small_model) == (4, "another:1b")
    assert (settings.today, settings.allow_open) == (date(2026, 7, 1), True)


# ---------------------------------------------------------------------- command line


@pytest.fixture
def cli_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    get_settings.cache_clear()
    return settings


def stored(settings: Settings) -> list[Document]:
    engine = create_db_engine(settings.database_url)
    try:
        create_schema(engine)
        with transaction(session_factory(engine)) as session:
            rows = list(session.scalars(select(Document).order_by(Document.id)))
            session.expunge_all()
            return rows
    finally:
        engine.dispose()


def test_submit_queues_files_once(
    cli_settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "a.pdf"
    first.write_bytes(render_pdf(invoice_data("forez")))
    second = tmp_path / "b.pdf"
    second.write_bytes(render_pdf(invoice_data("breval")))

    assert cli.main(["submit", str(first), str(second)]) == 0
    assert cli.main(["submit", str(first)]) == 0
    output = capsys.readouterr().out
    assert output.count("queued") == 2
    assert "a.pdf: document 1 (already received)" in output
    documents = stored(cli_settings)
    assert [(document.filename, document.status, document.source) for document in documents] == [
        ("a.pdf", "queued", "cli"),
        ("b.pdf", "queued", "cli"),
    ]


def test_submit_refuses_a_path_that_is_not_a_file(
    cli_settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["submit", str(tmp_path / "missing.pdf")]) == 2
    assert "not a file" in capsys.readouterr().err
    assert stored(cli_settings) == []


def test_samples_queues_documents_of_the_dataset(
    cli_settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Builder("dev").build(tmp_path / "dataset" / "dev", {"clean": 3})
    arguments = ["samples", "--split", "dev", "--limit", "2", "--data", str(tmp_path)]
    assert cli.main(arguments) == 0
    assert "2 new documents queued from the dev split" in capsys.readouterr().out
    assert [document.source for document in stored(cli_settings)] == ["samples", "samples"]


def test_the_command_line_needs_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_the_command_line_leaves_no_database_connection_open(
    cli_settings: Settings, tmp_path: Path
) -> None:
    """Python 3.13 reports a connection that was never closed: that failed the suite."""
    path = tmp_path / "a.pdf"
    path.write_bytes(render_pdf(invoice_data("forez")))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        assert cli.main(["submit", str(path)]) == 0
        assert cli.main(["migrate"]) == 0
        gc.collect()
    assert [str(warning.message) for warning in caught if "unclosed" in str(warning.message)] == []


def test_serving_beyond_the_loopback_needs_keys_or_an_explicit_word(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    served: list[str] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: served.append(options["host"]))

    assert cli.main(["serve", "--host", "192.0.2.10"]) == 2
    assert "COUNTERSIGN_API_KEYS" in capsys.readouterr().err
    assert served == []

    cli_settings.allow_open = True
    assert cli.main(["serve", "--host", "192.0.2.10"]) == 0
    cli_settings.allow_open, cli_settings.api_keys = False, "ann:reviewer:k1"
    assert cli.main(["serve", "--host", "192.0.2.10", "--no-workers"]) == 0
    cli_settings.api_keys = ""
    assert cli.main(["serve"]) == 0
    assert served == ["192.0.2.10", "192.0.2.10", "127.0.0.1"]


def test_demo_serves_the_recorded_samples_as_of_their_own_date(
    cli_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One command: the samples queued, the recordings for a model, and a "today" that
    does not make documents of 2026 too old to approve when the demo runs in 2027."""
    Builder("test").build(tmp_path / "dataset" / "test", {"clean": 3})
    seen: dict[str, Any] = {}

    def app_for(settings: Settings, **options: Any) -> str:
        seen.update(settings=settings, **options)
        return "the application"

    monkeypatch.setattr(cli, "create_app", app_for)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: seen.update(app=app, **options))
    tapes = tmp_path / "tapes"
    arguments = ["demo", "--limit", "2", "--data", str(tmp_path), "--cassettes", str(tapes)]
    assert cli.main(arguments) == 0

    assert "2 new documents queued from the test split" in capsys.readouterr().out
    assert [document.source for document in stored(cli_settings)] == ["samples", "samples"]
    assert (seen["app"], seen["host"], seen["start_workers"]) == (
        "the application",
        "127.0.0.1",
        True,
    )
    assert (seen["settings"].replay_dir, seen["settings"].today) == (tapes, EVAL_TODAY)
    assert cli_settings.today is None  # the settings of the other commands are untouched

    assert cli.main([*arguments, "--host", "192.0.2.10"]) == 2  # same rule as `serve`


def test_migrate_brings_the_database_to_the_current_schema(
    cli_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["migrate"]) == 0
    assert cli.main(["migrate"]) == 0  # nothing left to do
    assert "current schema" in capsys.readouterr().out
    assert stored(cli_settings) == []


def test_a_setting_that_does_not_validate_is_named_without_its_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COUNTERSIGN_API_KEYS", "ann:reviewer:k1-secret,broken")
    get_settings.cache_clear()
    served: list[Any] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **options: served.append(app))
    try:
        assert cli.main(["serve"]) == 2
    finally:
        get_settings.cache_clear()
    error = capsys.readouterr().err
    assert "configuration error: api_keys" in error
    assert "entry 2" in error
    assert "k1-secret" not in error
    assert served == []
