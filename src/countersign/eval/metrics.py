"""Score what the pipeline did with a document against what it should have done.

Two things are scored separately, because they fail differently:

- the extraction: is each field what is printed on the page?
- the decision: was the document approved, sent to a person, or set aside, and was
  that harmless?

The number that matters most is the count of harmful decisions. A document reviewed by
a person for nothing costs a few minutes. A wrong amount, a wrong supplier or a changed
bank account approved without anyone looking costs money.
"""

import math
from collections import Counter
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from countersign.domain.schema import CRITICAL_FIELDS, Invoice
from countersign.eval.dataset import Sample
from countersign.pipeline.process import Result

Harm = Literal["wrong_approval", "lost_invoice"]
SCORED_FIELDS: tuple[str, ...] = (
    *CRITICAL_FIELDS,
    "supplier_siret",
    "referenced_invoice",
    "allowance_total",
    "charge_total",
)


class DocumentScore(BaseModel):
    id: str
    scenario: str
    variant: str
    layout: str
    language: str
    held_out: bool
    expected: str
    outcome: str
    reasons: list[str]
    mode: str | None
    tiers: list[str]
    kept_tier: str | None
    # Decision
    harm: Harm | None
    as_expected: bool
    acceptable: bool
    # Whether the document was stopped for the reason it had to be; None when the label
    # names no reason.
    reason_found: bool | None
    # Whether the supplier record the pipeline settled on is the right one: it decides
    # who is paid. None for a document that is not an invoice or was not read.
    supplier_correct: bool | None = None
    # Extraction (None for documents that are not invoices)
    fields: dict[str, bool] | None
    critical_correct: bool | None
    lines_correct: bool | None
    # Cost
    model_seconds: float
    prompt_tokens: int
    output_tokens: int
    errors: list[str]


def score_fields(truth: Invoice, got: Invoice) -> dict[str, bool]:
    """Exact comparison: 663.274 is not 663.27, however close (1.50 does equal 1.5)."""
    return {field: getattr(truth, field) == getattr(got, field) for field in SCORED_FIELDS}


def lines_match(truth: Invoice, got: Invoice) -> bool:
    """Same lines, as a multiset of (quantity, unit price, amount); order is ignored."""

    def keys(invoice: Invoice) -> Counter[tuple[Decimal | None, ...]]:
        return Counter(
            tuple(
                value.normalize() if value is not None else None
                for value in (line.quantity, line.unit_price, line.amount)
            )
            for line in invoice.lines
        )

    return keys(truth) == keys(got)


def score_document(sample: Sample, result: Result) -> DocumentScore:
    truth, got = sample.truth, result.invoice
    is_accounting = truth.document_type != "other"
    fields = critical = lines = supplier = None
    if is_accounting and got is not None:
        fields = score_fields(truth, got)
        critical = all(fields[field] for field in CRITICAL_FIELDS)
        lines = lines_match(truth, got)
        supplier = result.vendor_id == sample.vendor_id
    elif is_accounting:
        fields = dict.fromkeys(SCORED_FIELDS, False)
        critical = lines = supplier = False

    harm: Harm | None = None
    if result.outcome == "approved":
        if not sample.allows("approved") or not critical or not supplier:
            harm = "wrong_approval"
    elif result.outcome in ("rejected", "duplicate") and not sample.allows(result.outcome):
        # A real invoice set aside without anyone being asked to look at it.
        harm = "lost_invoice"

    reason_found = None
    if sample.expected_reason:
        # A document approved by mistake was not stopped for the right reason either.
        reason_found = result.outcome != "approved" and sample.expected_reason in result.reasons

    kept = result.kept
    return DocumentScore(
        id=sample.id,
        scenario=sample.scenario,
        variant=sample.variant,
        layout=sample.layout,
        language=sample.language,
        held_out=sample.held_out,
        expected=sample.expected_outcome,
        outcome=result.outcome,
        reasons=result.reasons,
        mode=result.mode,
        tiers=[attempt.tier for attempt in result.attempts],
        kept_tier=kept.tier if kept else None,
        harm=harm,
        as_expected=result.outcome == sample.expected_outcome,
        acceptable=sample.allows(result.outcome),
        reason_found=reason_found,
        supplier_correct=supplier,
        fields=fields,
        critical_correct=critical,
        lines_correct=lines,
        model_seconds=round(result.model_seconds, 3),
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        errors=[attempt.error for attempt in result.attempts if attempt.error],
    )


class Rate(BaseModel):
    """A proportion with its 95 % Wilson interval."""

    count: int
    total: int
    value: float | None
    low: float | None
    high: float | None


def rate(count: int, total: int) -> Rate:
    if total == 0:
        return Rate(count=0, total=0, value=None, low=None, high=None)
    z = 1.959964
    p = count / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return Rate(
        count=count,
        total=total,
        value=round(p, 4),
        low=round(max(0.0, centre - margin), 4),
        high=round(min(1.0, centre + margin), 4),
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class Summary(BaseModel):
    documents: int
    # Decisions
    harmful: Rate
    wrong_approvals: int
    lost_invoices: int
    as_expected: Rate
    approved: Rate
    # Of the documents a correct system approves, how many were approved.
    automation: Rate
    # Of the approved documents, how many were right to approve and correctly read.
    approval_precision: Rate
    # Of the documents that must not be approved, how many were stopped.
    stopped: Rate
    # Of the documents labelled with the reason they must be stopped for, how many were
    # stopped for it.
    reason_found: Rate
    # Extraction, over invoices and credit notes
    critical_correct: Rate
    lines_correct: Rate
    field_accuracy: dict[str, Rate]
    # Cost
    escalated: Rate
    seconds_mean: float
    seconds_median: float
    seconds_p95: float
    output_tokens_mean: float
    prompt_tokens_mean: float
    model_errors: int


def summarise(scores: list[DocumentScore]) -> Summary:
    total = len(scores)
    approvable = [score for score in scores if score.expected == "approved"]
    approved = [score for score in scores if score.outcome == "approved"]
    must_stop = [score for score in scores if score.expected != "approved"]
    with_reason = [score for score in scores if score.reason_found is not None]
    accounting = [score for score in scores if score.fields is not None]
    seconds = [score.model_seconds for score in scores]
    return Summary(
        documents=total,
        harmful=rate(sum(score.harm is not None for score in scores), total),
        wrong_approvals=sum(score.harm == "wrong_approval" for score in scores),
        lost_invoices=sum(score.harm == "lost_invoice" for score in scores),
        as_expected=rate(sum(score.as_expected for score in scores), total),
        approved=rate(len(approved), total),
        automation=rate(
            sum(score.outcome == "approved" and score.harm is None for score in approvable),
            len(approvable),
        ),
        approval_precision=rate(sum(score.harm is None for score in approved), len(approved)),
        stopped=rate(sum(score.outcome != "approved" for score in must_stop), len(must_stop)),
        reason_found=rate(sum(bool(score.reason_found) for score in with_reason), len(with_reason)),
        critical_correct=rate(
            sum(bool(score.critical_correct) for score in accounting), len(accounting)
        ),
        lines_correct=rate(sum(bool(score.lines_correct) for score in accounting), len(accounting)),
        field_accuracy={
            field: rate(
                sum(score.fields[field] for score in accounting if score.fields), len(accounting)
            )
            for field in SCORED_FIELDS
        },
        escalated=rate(sum(len(score.tiers) > 1 for score in scores), total),
        seconds_mean=round(sum(seconds) / total, 2) if total else 0.0,
        seconds_median=round(percentile(seconds, 0.5), 2),
        seconds_p95=round(percentile(seconds, 0.95), 2),
        output_tokens_mean=round(sum(score.output_tokens for score in scores) / total, 1)
        if total
        else 0.0,
        prompt_tokens_mean=round(sum(score.prompt_tokens for score in scores) / total, 1)
        if total
        else 0.0,
        model_errors=sum(len(score.errors) for score in scores),
    )


class Report(BaseModel):
    split: str
    config: str
    models: list[str]
    prompt_id: str
    verify: bool
    summary: Summary
    by_scenario: dict[str, Summary]
    by_group: dict[str, Summary]
    documents: list[DocumentScore]
