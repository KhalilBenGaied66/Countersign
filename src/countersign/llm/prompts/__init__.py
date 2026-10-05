"""Versioned prompts.

A prompt is a file with a version in its name, together with the shape of the JSON it
asks for. Changing the wording or the shape means adding a version, not editing one:
the id is stored with every extraction, so a result can always be traced to the exact
instructions that produced it, and earlier versions stay available to measure against.

- `extract_v1` asked for every value as text copied from the page. Under constrained
  decoding the models wrapped numbers in stray JSON, or left them empty.
- `extract_v2` asks for amounts and quantities as JSON numbers.
- `extract_v3` no longer asks for the taxable base of each VAT rate, which the models
  filled with the VAT amount whenever the page printed no base.
- `extract_v4` says what an IBAN and a purchase order number look like, after the
  larger model built an "IBAN" out of a US routing number and reported customer codes
  as order numbers, and asks for a self-contradicting document to be reported as
  printed rather than tidied up. Its wording of `invoice_number` made the smaller
  model return no number at all for credit notes.
- `extract_v5` rewords that one field.

`docs/evaluation.md` gives the measurements behind each step.
"""

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from countersign.domain.schema import NumericFields, extraction_json_schema

DEFAULT_PROMPT = "extract_v5"


@dataclass(frozen=True)
class Shape:
    """The JSON a prompt version asks for (see `extraction_json_schema`)."""

    numeric: NumericFields
    vat_base: bool
    referenced_invoice: bool


_SHAPES: dict[str, Shape] = {
    "extract_v1": Shape("text", vat_base=True, referenced_invoice=False),
    "extract_v2": Shape("number", vat_base=True, referenced_invoice=False),
    "extract_v3": Shape("number", vat_base=False, referenced_invoice=False),
    "extract_v4": Shape("number", vat_base=False, referenced_invoice=False),
    "extract_v5": Shape("number", vat_base=False, referenced_invoice=True),
}

_TEXT_MESSAGE = "<document>\n{text}\n</document>"
_IMAGE_MESSAGE = (
    "The document is attached as {count} page image(s), in reading order. "
    "Read it and return the JSON object."
)


@dataclass(frozen=True)
class Prompt:
    id: str
    template: str
    shape: Shape

    def system(self, company: str, po_example: str = "") -> str:
        """The instructions, for a given buyer and the look of its order numbers."""
        return self.template.format(company=company, po_example=po_example)

    def schema(self) -> dict[str, Any]:
        return extraction_json_schema(
            self.shape.numeric,
            vat_base=self.shape.vat_base,
            referenced_invoice=self.shape.referenced_invoice,
        )

    @staticmethod
    def for_text(text: str) -> str:
        return _TEXT_MESSAGE.format(text=text)

    @staticmethod
    def for_images(count: int) -> str:
        return _IMAGE_MESSAGE.format(count=count)


@cache
def load_prompt(prompt_id: str = DEFAULT_PROMPT) -> Prompt:
    source = resources.files(__package__).joinpath(f"{prompt_id}.txt")
    return Prompt(
        id=prompt_id,
        template=source.read_text(encoding="utf-8").strip(),
        shape=_SHAPES[prompt_id],
    )
