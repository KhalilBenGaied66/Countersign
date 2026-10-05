"""Prometheus metrics.

Counters and histograms are updated where things happen (a document decided, a model
call made). Queue depth and review backlog are read from the database at scrape time
by a collector, so that they are right whichever process is scraped.
"""

from collections.abc import Callable, Iterator

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from countersign.pipeline.process import Result

REGISTRY = CollectorRegistry()

DOCUMENTS = Counter(
    "countersign_documents_total",
    "Documents processed, by outcome and by how they were read.",
    ["outcome", "mode"],
    registry=REGISTRY,
)
ATTEMPTS = Counter(
    "countersign_extraction_attempts_total",
    "Extraction attempts, by tier and result (passed, failed_checks, error).",
    ["tier", "result"],
    registry=REGISTRY,
)
CHECK_FAILURES = Counter(
    "countersign_check_failures_total",
    "Blocking checks failed by the kept extraction, by family.",
    ["family"],
    registry=REGISTRY,
)
JOB_FAILURES = Counter(
    "countersign_job_failures_total",
    "Jobs that raised, by whether it was their last attempt.",
    ["final"],
    registry=REGISTRY,
)
MODEL_SECONDS = Histogram(
    "countersign_model_seconds",
    "Wall-clock seconds of a model call, by tier.",
    ["tier"],
    buckets=(1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128),
    registry=REGISTRY,
)
DOCUMENT_SECONDS = Histogram(
    "countersign_document_model_seconds",
    "Model seconds spent on a document, all tiers together.",
    buckets=(1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128),
    registry=REGISTRY,
)
TOKENS = Counter(
    "countersign_tokens_total",
    "Tokens sent to and received from models, by tier and direction.",
    ["tier", "direction"],
    registry=REGISTRY,
)


def observe_result(result: Result, outcome: str) -> None:
    DOCUMENTS.labels(outcome=outcome, mode=result.mode or "unreadable").inc()
    DOCUMENT_SECONDS.observe(result.model_seconds)
    for attempt in result.attempts:
        status = "error" if attempt.error else "passed" if attempt.passed else "failed_checks"
        ATTEMPTS.labels(tier=attempt.tier, result=status).inc()
        if attempt.model:
            MODEL_SECONDS.labels(tier=attempt.tier).observe(attempt.duration_s)
            TOKENS.labels(tier=attempt.tier, direction="input").inc(attempt.prompt_tokens)
            TOKENS.labels(tier=attempt.tier, direction="output").inc(attempt.output_tokens)
    if outcome != "approved":
        for family in result.reasons:
            CHECK_FAILURES.labels(family=family).inc()


class BacklogCollector(Collector):
    """Gauges computed from the database when Prometheus scrapes."""

    def __init__(self, read: Callable[[], dict[str, dict[str, int]]]) -> None:
        self._read = read

    def collect(self) -> Iterator[GaugeMetricFamily]:
        snapshot = self._read()
        jobs = GaugeMetricFamily(
            "countersign_jobs", "Jobs in the queue, by status.", labels=["status"]
        )
        for status, count in snapshot.get("jobs", {}).items():
            jobs.add_metric([status], count)
        yield jobs
        documents = GaugeMetricFamily(
            "countersign_documents", "Documents in the database, by status.", labels=["status"]
        )
        for status, count in snapshot.get("documents", {}).items():
            documents.add_metric([status], count)
        yield documents


def render(registry: CollectorRegistry = REGISTRY) -> bytes:
    return generate_latest(registry)
