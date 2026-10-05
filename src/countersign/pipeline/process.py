"""Process one document: read it, extract, verify, escalate if that can help, decide.

The cheapest reader that can be trusted goes first:

1. an embedded e-invoice (Factur-X, ZUGFeRD) is read as data, without any model;
2. otherwise the first model tier extracts from the text layer, or from page images
   when the document is a scan;
3. the checks of `countersign.verify.checks` run on the result;
4. a failure that another reading could fix sends the document to the next tier, which
   starts from the document alone. It is never told which check failed: a model that
   knows the sum it must reach can produce it without reading the page;
5. a scan has no text to check values against, so it is always read by two tiers and
   approved only if they agree ("double keying"). With one tier it goes to a person.

The decision is taken by code from the checks. The model fills a form; it never
approves anything. Nothing is set aside on the word of one reading: "not an invoice"
needs the title of the page or a second reading to say the same, and "already received"
needs every other check to pass.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from countersign.domain.normalize import DecimalSeparator
from countersign.domain.schema import (
    CRITICAL_FIELDS,
    Invoice,
    RawExtraction,
    RawLine,
    RawVatLine,
)
from countersign.llm.client import ModelClient, ModelError, ModelRequest
from countersign.llm.prompts import DEFAULT_PROMPT, Prompt, load_prompt
from countersign.master import MasterData
from countersign.obs.tracing import tracer
from countersign.parsing import einvoice
from countersign.parsing.pdf import (
    RASTER,
    ParsedDocument,
    UnreadableDocument,
    parse_pdf,
    render_pages,
    sha256_of,
)
from countersign.pipeline.normalise import normalise
from countersign.verify.checks import Check, CheckContext, Ledger, blocking_failures, run_checks
from countersign.verify.evidence import Evidence

Outcome = Literal["approved", "review", "rejected", "duplicate"]
Mode = Literal["embedded", "text", "vision"]

# Whatever the spelling, the tag that closes the frame the document is quoted in.
_CLOSING_TAG = re.compile(r"(?i)<\s*/\s*document\s*>")


@dataclass(frozen=True)
class Tier:
    name: str
    model: str
    think: bool = False


@dataclass(frozen=True)
class PipelineConfig:
    tiers: tuple[Tier, ...]
    # False turns the checks off: whatever is extracted is approved. Only useful as the
    # baseline that shows what the checks are worth.
    verify: bool = True
    read_embedded_invoice: bool = True
    # Approve a scan only when two tiers read it alike. With a single tier no scan is
    # approved. False approves a scan on one reading that nothing confirms.
    scan_consensus: bool = True
    prompt_id: str = DEFAULT_PROMPT
    context_tokens: int = 16384
    max_output_tokens: int = 6000
    # Measured on the scans of the dev split: at 200 DPI the two models agreed on 7 of 8
    # clean scans, against 5 at 150 DPI, for a third more model time. One page at that
    # resolution is what fits the context window with room for the answer: a scan of
    # several pages goes to a person.
    scan_dpi: int = 200
    max_scan_pages: int = 1


class Attempt(BaseModel):
    """One reading of the document by one tier, with the checks it was put through."""

    tier: str
    mode: Mode
    model: str | None = None
    prompt_id: str | None = None
    raw: RawExtraction | None = None
    invoice: Invoice | None = None
    vendor_id: str | None = None
    checks: list[Check] = []
    error: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0

    @property
    def failures(self) -> list[Check]:
        return blocking_failures(self.checks)

    @property
    def passed(self) -> bool:
        return self.raw is not None and not self.failures

    @property
    def worth_retrying(self) -> bool:
        return self.raw is None or any(check.retriable for check in self.failures)


class Result(BaseModel):
    outcome: Outcome
    # Families of the checks that stopped the document, most specific first.
    reasons: list[str] = []
    mode: Mode | None = None
    attempts: list[Attempt] = []
    # Index of the attempt whose extraction is kept.
    final: int | None = None
    sha256: str | None = None
    page_count: int = 0
    error: str | None = None
    note: str | None = None

    @property
    def kept(self) -> Attempt | None:
        return self.attempts[self.final] if self.final is not None else None

    @property
    def invoice(self) -> Invoice | None:
        return self.kept.invoice if self.kept else None

    @property
    def vendor_id(self) -> str | None:
        return self.kept.vendor_id if self.kept else None

    @property
    def checks(self) -> list[Check]:
        return self.kept.checks if self.kept else []

    @property
    def model_seconds(self) -> float:
        return sum(attempt.duration_s for attempt in self.attempts)

    @property
    def output_tokens(self) -> int:
        return sum(attempt.output_tokens for attempt in self.attempts)

    @property
    def prompt_tokens(self) -> int:
        return sum(attempt.prompt_tokens for attempt in self.attempts)


def disagreement(first: Invoice, second: Invoice) -> list[str]:
    """Header fields on which two readings of the same document differ."""
    differing = [
        field for field in CRITICAL_FIELDS if getattr(first, field) != getattr(second, field)
    ]
    if len(first.lines) != len(second.lines):
        differing.append("lines")
    return differing


def raw_from_invoice(invoice: Invoice) -> RawExtraction:
    """An invoice written back as text, to put a person's corrections through the checks."""

    def text(value: object) -> str | None:
        if value is None:
            return None
        return value.isoformat() if isinstance(value, date) else str(value)

    return RawExtraction(
        document_type=invoice.document_type,
        invoice_number=invoice.invoice_number,
        issue_date=text(invoice.issue_date),
        due_date=text(invoice.due_date),
        currency=invoice.currency,
        supplier_name=invoice.supplier_name,
        supplier_vat_id=invoice.supplier_vat_id,
        supplier_siret=invoice.supplier_siret,
        supplier_iban=invoice.supplier_iban,
        po_number=invoice.po_number,
        referenced_invoice=invoice.referenced_invoice,
        lines=[
            RawLine(
                description=line.description,
                quantity=text(line.quantity),
                unit_price=text(line.unit_price),
                amount=text(line.amount),
                vat_rate=text(line.vat_rate),
            )
            for line in invoice.lines
        ],
        allowance_total=text(invoice.allowance_total),
        charge_total=text(invoice.charge_total),
        total_net=text(invoice.total_net),
        vat_breakdown=[
            RawVatLine(rate=text(row.rate), base=text(row.base), tax=text(row.tax))
            for row in invoice.vat_breakdown
        ],
        total_tax=text(invoice.total_tax),
        total_gross=text(invoice.total_gross),
    )


def decide(checks: list[Check]) -> tuple[Outcome, list[str]]:
    """The outcome a list of checks leads to.

    A document is set aside without anyone looking only when that is the single thing
    wrong with it: it is not an invoice, or it is a copy of one already taken in, and no
    other check failed. Any failure next to that one means the document was not
    understood well enough to be dropped.
    """
    failures = blocking_failures(checks)
    if not failures:
        return "approved", []
    families = list(dict.fromkeys(check.family for check in failures))
    failed = {check.id for check in failures}
    if failed == {"document.accounting"}:
        return "rejected", ["not_invoice"]
    if failed == {"duplicate.unique"}:
        return "duplicate", families
    return "review", families


Reader = Callable[[bytes], ParsedDocument]


class Renderer(Protocol):
    def __call__(self, data: bytes, *, dpi: int, max_pages: int) -> Sequence[bytes]: ...


class Pipeline:
    def __init__(
        self,
        config: PipelineConfig,
        client: ModelClient,
        master: MasterData,
        *,
        parse: Reader = parse_pdf,
        render: Renderer = render_pages,
    ) -> None:
        self.config = config
        self.client = client
        self.master = master
        # Replaceable so that an evaluation reads each file once, whatever the number
        # of configurations it is put through.
        self._parse = parse
        self._render = render
        self.prompt: Prompt = load_prompt(config.prompt_id)
        self._system = self.prompt.system(master.company.name, master.company.po_example)
        self._schema = self.prompt.schema()

    def process(self, pdf: bytes, *, ledger: Ledger, today: date, label: str = "") -> Result:
        with tracer().start_as_current_span("countersign.process") as span:
            result = self._process(pdf, ledger, today, label)
            span.set_attribute("countersign.outcome", result.outcome)
            span.set_attribute("countersign.reasons", result.reasons)
            span.set_attribute("countersign.mode", result.mode or "unreadable")
            span.set_attribute("countersign.pages", result.page_count)
            span.set_attribute("countersign.attempts", len(result.attempts))
            return result

    def _process(self, pdf: bytes, ledger: Ledger, today: date, label: str) -> Result:
        try:
            with tracer().start_as_current_span("countersign.parse"):
                parsed = self._parse(pdf)
        except UnreadableDocument as error:
            return Result(outcome="review", reasons=["unreadable"], error=str(error))
        evidence = _evidence(parsed)
        config = self.config

        attempts: list[Attempt] = []
        if config.read_embedded_invoice:
            xml = einvoice.find_embedded_invoice(parsed.attachments)
            if xml is not None:
                attempt = self._read_embedded(xml, parsed, evidence, ledger, today)
                attempts.append(attempt)
                if attempt.raw is not None:
                    # Data supplied by the issuer is not second-guessed by a model: it
                    # passes the checks or a person looks at it.
                    return self._conclude(parsed, "embedded", attempts, evidence)

        mode: Mode = "text" if evidence is not None else "vision"
        images: tuple[bytes, ...] = ()
        if mode == "vision":
            if parsed.page_count > config.max_scan_pages:
                return self._failed(parsed, mode, attempts, "too_long")
            try:
                images = tuple(
                    self._render(pdf, dpi=config.scan_dpi, max_pages=config.max_scan_pages)
                )
            except UnreadableDocument as error:
                return Result(outcome="review", reasons=["unreadable"], error=str(error))

        read_twice = mode == "vision" and config.scan_consensus
        for tier in config.tiers:
            attempt = self._extract(tier, mode, parsed, images, evidence, ledger, today, label)
            attempts.append(attempt)
            if not config.verify:
                break
            if not read_twice and (attempt.passed or not attempt.worth_retrying):
                break
        return self._conclude(parsed, mode, attempts, evidence)

    def recheck(self, pdf: bytes, invoice: Invoice, *, ledger: Ledger, today: date) -> Attempt:
        """Put an invoice corrected by a reviewer through the same checks, without a model.

        A file the parser refuses can still be decided by a person who holds the paper:
        the checks then run without the page, and one of them says so.
        """
        unreadable = None
        try:
            parsed = self._parse(pdf)
        except UnreadableDocument as error:
            unreadable = str(error)
            parsed = ParsedDocument(
                sha256=sha256_of(pdf), page_count=0, text="", has_text_layer=False, attachments={}
            )
        evidence = _evidence(parsed)
        mode: Mode = "text" if evidence is not None else "vision"
        raw = raw_from_invoice(invoice)
        attempt = self._assess(
            raw, "reviewer", mode, parsed, evidence, ledger, today, separator="."
        )
        if unreadable is not None:
            attempt.checks.append(
                Check(
                    id="document.unreadable",
                    family="unreadable",
                    passed=False,
                    message=f"the file cannot be read ({unreadable}): nothing was "
                    "compared with the page",
                )
            )
        return attempt

    # ------------------------------------------------------------------------ readers

    def _read_embedded(
        self,
        xml: bytes,
        parsed: ParsedDocument,
        evidence: Evidence | None,
        ledger: Ledger,
        today: date,
    ) -> Attempt:
        try:
            raw = einvoice.read_cii(xml)
        except einvoice.EInvoiceError as error:
            return Attempt(tier=einvoice.TIER_NAME, mode="embedded", error=str(error))
        attempt = self._assess(
            raw, einvoice.TIER_NAME, "embedded", parsed, evidence, ledger, today, separator="."
        )
        if evidence is None and self.config.verify:
            attempt.checks.append(
                Check(
                    id="embedded.cross_check",
                    family="grounding",
                    passed=False,
                    message="the embedded invoice cannot be compared with the page: no text layer",
                )
            )
        return attempt

    def _extract(
        self,
        tier: Tier,
        mode: Mode,
        parsed: ParsedDocument,
        images: tuple[bytes, ...],
        evidence: Evidence | None,
        ledger: Ledger,
        today: date,
        label: str,
    ) -> Attempt:
        config = self.config
        if mode == "vision":
            user = Prompt.for_images(len(images))
        else:
            # The closing tag is the only thing a document could use to step out of its
            # frame; it has no reason to appear on an invoice, and is rewritten as
            # something that is not a tag.
            user = Prompt.for_text(_CLOSING_TAG.sub("[/document]", parsed.text))
        request = ModelRequest(
            model=tier.model,
            system=self._system,
            user=user,
            images=images,
            image_source=(
                f"{parsed.sha256}@{config.scan_dpi}dpi:{len(images)}:{RASTER}" if images else ""
            ),
            schema=self._schema,
            think=tier.think,
            max_output_tokens=config.max_output_tokens,
            context_tokens=config.context_tokens,
            label=label,
        )
        base = Attempt(tier=tier.name, mode=mode, model=tier.model, prompt_id=self.prompt.id)
        with tracer().start_as_current_span("countersign.extract") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", tier.model)
            span.set_attribute("countersign.tier", tier.name)
            span.set_attribute("countersign.mode", mode)
            try:
                response = self.client.generate(request)
            except ModelError as error:
                span.set_attribute("error.type", error.kind)
                return base.model_copy(update={"error": error.kind})
            span.set_attribute("gen_ai.usage.input_tokens", response.prompt_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", response.output_tokens)
        usage = {
            "prompt_tokens": response.prompt_tokens,
            "output_tokens": response.output_tokens,
            "duration_s": response.duration_s,
        }
        try:
            # Decimal keeps a number exactly as the model wrote it: 464.60, not 464.6.
            raw = RawExtraction.model_validate(json.loads(response.content, parse_float=Decimal))
        except (ValueError, ValidationError):
            return base.model_copy(update={"error": "invalid_output", **usage})
        # A JSON number is written with a point, whatever the page uses. Without this,
        # 2.125 alone among whole numbers would be read as two thousand.
        separator: DecimalSeparator | None = "." if self.prompt.shape.numeric == "number" else None
        attempt = self._assess(
            raw, tier.name, mode, parsed, evidence, ledger, today, separator=separator
        )
        return attempt.model_copy(
            update={"model": tier.model, "prompt_id": self.prompt.id, **usage}
        )

    def _assess(
        self,
        raw: RawExtraction,
        tier: str,
        mode: Mode,
        parsed: ParsedDocument,
        evidence: Evidence | None,
        ledger: Ledger,
        today: date,
        separator: DecimalSeparator | None = None,
    ) -> Attempt:
        vendor = self.master.match_vendor(raw).vendor
        normalised = normalise(
            raw,
            text=parsed.text if evidence is not None else None,
            vendor_country=vendor.country if vendor else None,
            decimal_separator=separator,
            order_pattern=self.master.po_regex,
        )
        checks: list[Check] = []
        if self.config.verify:
            with tracer().start_as_current_span("countersign.verify") as span:
                checks = run_checks(
                    CheckContext(
                        raw=raw,
                        invoice=normalised.invoice,
                        unparsed=normalised.unparsed,
                        ambiguous=normalised.ambiguous,
                        evidence=evidence,
                        master=self.master,
                        vendor=vendor,
                        ledger=ledger,
                        today=today,
                    )
                )
                failed = [check.id for check in blocking_failures(checks)]
                span.set_attribute("countersign.tier", tier)
                span.set_attribute("countersign.checks.failed", failed)
        return Attempt(
            tier=tier,
            mode=mode,
            raw=raw,
            invoice=normalised.invoice,
            vendor_id=vendor.vendor_id if vendor else None,
            checks=checks,
        )

    # ----------------------------------------------------------------------- decision

    def _failed(
        self, parsed: ParsedDocument, mode: Mode, attempts: list[Attempt], reason: str
    ) -> Result:
        return Result(
            outcome="review",
            reasons=[reason],
            mode=mode,
            attempts=attempts,
            sha256=parsed.sha256,
            page_count=parsed.page_count,
        )

    def _conclude(
        self,
        parsed: ParsedDocument,
        mode: Mode,
        attempts: list[Attempt],
        evidence: Evidence | None,
    ) -> Result:
        readings = [index for index, attempt in enumerate(attempts) if attempt.raw is not None]
        if not readings:
            return self._failed(parsed, mode, attempts, "extraction_failed")
        final = readings[-1]
        kept = attempts[final]
        invoice = kept.invoice
        assert invoice is not None
        result = Result(
            outcome="approved",
            mode=mode,
            attempts=attempts,
            final=final,
            sha256=parsed.sha256,
            page_count=parsed.page_count,
        )
        if not self.config.verify:
            if invoice.document_type == "other":
                result.outcome, result.reasons = "rejected", ["not_invoice"]
            return result

        earlier = attempts[readings[-2]] if len(readings) > 1 else None
        previous = earlier.invoice if earlier else None
        titled_other = evidence is not None and evidence.title_kind == "other"
        if (
            earlier is not None
            and previous is not None
            and invoice.document_type == "other"
            and previous.document_type != "other"
            and not titled_other
        ):
            # The readings disagree on what the document is, and its title does not
            # settle it. A person decides, and works from the reading that found an
            # invoice.
            result.final, kept, invoice, previous = readings[-2], earlier, previous, None
            kept.checks.append(
                Check(
                    id="document.disputed",
                    family="not_invoice",
                    passed=False,
                    message="another reading says this is not an invoice",
                    fields=["document_type"],
                )
            )
        elif invoice.document_type == "other":
            kept.checks.append(_second_opinion(evidence, previous))
        elif mode == "vision" and self.config.scan_consensus:
            kept.checks.append(_consensus(previous, invoice))
        elif mode == "text" and previous is not None and evidence is not None:
            competing = _competing_amounts(previous, invoice, evidence)
            if competing is not None:
                kept.checks.append(competing)
        result.outcome, result.reasons = decide(kept.checks)
        if (
            result.outcome == "review"
            and previous is not None
            and "arithmetic" in result.reasons
            # Figures that are not on the page were misread twice, not misprinted.
            and "grounding" not in result.reasons
            and not disagreement(previous, invoice)
        ):
            result.note = (
                "Two independent readings give the same figures: the document itself "
                "is inconsistent."
            )
        return result


def _evidence(parsed: ParsedDocument) -> Evidence | None:
    return Evidence.of(parsed.text, has_text_layer=parsed.has_text_layer, heading=parsed.heading)


def _second_opinion(evidence: Evidence | None, previous: Invoice | None) -> Check:
    """Whether anything besides the reading kept says the document is not an invoice."""
    family = "not_invoice"
    if evidence is not None and evidence.title_kind == "other":
        message = "the title of the page says so too"
    elif previous is not None and previous.document_type == "other":
        message = "two independent readings say so"
    else:
        return Check(
            id="document.second_opinion",
            family=family,
            passed=False,
            message="one reading alone says this is not an invoice",
            fields=["document_type"],
        )
    return Check(id="document.second_opinion", family=family, passed=True, message=message)


_AMOUNTS = ("total_net", "total_tax", "total_gross")


def _competing_amounts(earlier: Invoice, kept: Invoice, evidence: Evidence) -> Check | None:
    """Refuse a second reading that overrules an amount the page really prints.

    A second reading may replace a value that was not on the page: that was a
    misreading. When the first value is on the page and the second reading reports
    another one, the page offers two candidates for the same amount, typically a
    misprinted total next to a correct VAT table, or a line whose amount is not its
    quantity times its price, and choosing between them is not for a model to do. A
    first value that is only some digits of a longer number ("435,57" out of
    "1 435,57") is not a candidate.

    Lines are compared one by one when both readings found as many: a reading that
    counted a subtotal as a line is corrected by the other, not contradicted.
    """

    def printed_twice(first: Decimal | None, second: Decimal | None) -> bool:
        return (
            first is not None
            and second is not None
            and first != second
            and evidence.has_number(first, whole=True)
        )

    candidates = {
        field: (getattr(earlier, field), getattr(kept, field))
        for field in _AMOUNTS
        if printed_twice(getattr(earlier, field), getattr(kept, field))
    }
    if len(earlier.lines) == len(kept.lines):
        for index, (before, after) in enumerate(zip(earlier.lines, kept.lines, strict=True)):
            if printed_twice(before.amount, after.amount):
                candidates[f"lines[{index}].amount"] = (before.amount, after.amount)
    if not candidates:
        return None
    details = ", ".join(
        f"{field} ({first} or {second})" for field, (first, second) in candidates.items()
    )
    return Check(
        id="arithmetic.competing",
        family="arithmetic",
        passed=False,
        message=f"the page prints two candidates for {details}",
        fields=list(candidates),
    )


def _consensus(previous: Invoice | None, kept: Invoice) -> Check:
    family = "consensus"
    if previous is None:
        return Check(
            id="consensus.two_readings",
            family=family,
            passed=False,
            message="a scan needs two readings that agree, and there is only one",
        )
    differing = disagreement(previous, kept)
    if differing:
        return Check(
            id="consensus.two_readings",
            family=family,
            passed=False,
            message="two readings of the scan differ on: " + ", ".join(differing),
            fields=differing,
        )
    return Check(
        id="consensus.two_readings",
        family=family,
        passed=True,
        message="two independent readings of the scan agree",
    )
