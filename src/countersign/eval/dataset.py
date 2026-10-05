"""The evaluation dataset: synthetic documents with their ground truth.

A split is a directory holding PDF files and `truth.jsonl`, one `Sample` per line in
processing order (a duplicate must come after the invoice it repeats).
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from countersign.domain.schema import Invoice

Outcome = Literal["approved", "review", "rejected", "duplicate"]
# "confirm" has the make-up of "test", with other documents: it was generated, and run
# once, after the last change the test split led to.
Split = Literal["dev", "test", "confirm"]

TRUTH_FILE = "truth.jsonl"


class Sample(BaseModel):
    id: str
    file: str
    split: Split
    scenario: str
    variant: str = ""
    vendor_key: str
    vendor_id: str | None
    layout: str
    language: str
    # The supplier, and with it its layout, never appears in the dev split.
    held_out: bool
    is_scan: bool = False
    has_embedded_xml: bool = False
    pages: int = 1
    expected_outcome: Outcome
    # Outcomes that are not the expected one but do no harm, e.g. a person reviewing a
    # document the system could have approved.
    acceptable_outcomes: list[Outcome] = []
    # Family of the check that should send the document to review.
    expected_reason: str | None = None
    truth: Invoice

    def allows(self, outcome: str) -> bool:
        return outcome == self.expected_outcome or outcome in self.acceptable_outcomes


def load_samples(directory: Path) -> list[Sample]:
    path = directory / TRUTH_FILE
    with path.open(encoding="utf-8") as handle:
        return [Sample.model_validate_json(line) for line in handle if line.strip()]


def write_samples(directory: Path, samples: list[Sample]) -> None:
    lines = [sample.model_dump_json(exclude_defaults=False) for sample in samples]
    (directory / TRUTH_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
