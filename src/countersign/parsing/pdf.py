"""Read a PDF: text layer, embedded files, and page images for scans.

A PDF is untrusted input. Bounded here, before or while a file is interpreted: its
size, its number of pages, what any one compressed stream may expand to, which
attachments are read at all, and the pixels a page is rendered to. Not bounded: the
total time and memory a file built for the purpose can cost inside those limits; that
takes a process with limits of its own (see docs/production.md).

Whatever the parser raises becomes `UnreadableDocument`, so that the file goes to a
person and not to an error log.
"""

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pypdf
import pypdfium2 as pdfium
from pypdf import PageObject, PdfReader
from pypdf.generic import DictionaryObject

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 12
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
# What one compressed stream (a page's content, an object stream, an attachment) may
# expand to. A page of text is a few tens of kilobytes; pypdf's own default is 75 MB.
MAX_STREAM_BYTES = 4 * 1024 * 1024
# Attachments looked at, by name; only the XML ones are decompressed.
MAX_ATTACHMENTS = 16
# Below this many letters and digits, a page has no text layer worth the name.
MIN_TEXT_CHARACTERS = 80
# An image this large on a page without text is the page itself: 100 DPI on A4.
MIN_SCAN_PIXELS = 800 * 1100
# Pixels one rendered page may have. A4 at 200 DPI is 3.9 million.
MAX_PAGE_PIXELS = 6_000_000
PAGE_BREAK = "\n\n--- page {number} ---\n\n"
# Names how `render_pages` draws a page. It is part of the key under which a model's
# answer to a scan is recorded: change it whenever a page would come out differently
# (another renderer, colour, smoothing), so that answers to the old pictures are not
# replayed for the new ones.
RASTER = "pdfium-gray-1"

# pypdf lays text out on a character grid. A weight below its default narrows the grid:
# columns stay aligned and the text is about a third shorter, which is what the model pays
# for in tokens.
_LAYOUT_SCALE = 0.7
# Text drawn this much larger than the median character of the page is a heading.
_HEADING_RATIO = 1.4
_MAX_HEADING_CHARACTERS = 400
_FORM_DEPTH = 2


class UnreadableDocument(Exception):
    """The file is not a PDF this pipeline accepts; the message says why."""


@dataclass(frozen=True)
class ParsedDocument:
    sha256: str
    page_count: int
    text: str
    # False as soon as one page is a picture: its content cannot be checked against text.
    has_text_layer: bool
    attachments: dict[str, bytes]
    # What the first page prints in large type, in drawing order; "" when nothing stands
    # out. This is where a document says what it is.
    heading: str = ""


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@contextmanager
def _limits() -> Iterator[None]:
    with pypdf.apply_configuration(
        maximum_declared_stream_length=MAX_BYTES,
        array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
        zlib_maximum_output_length=MAX_STREAM_BYTES,
        lzw_maximum_output_length=MAX_STREAM_BYTES,
        run_length_maximum_output_length=MAX_STREAM_BYTES,
        page_tree_maximum_entries=20 * MAX_PAGES,
        xform_maximum_invocations_per_extraction=100,
        disable_legacy_handling=True,
    ):
        yield


def count_pages(data: bytes) -> int:
    """Number of pages, or 0 for a file that cannot be opened. Reads no page content."""
    try:
        with _limits():
            reader = PdfReader(BytesIO(data))
            return 0 if reader.is_encrypted else len(reader.pages)
    except Exception:
        return 0


def parse_pdf(data: bytes) -> ParsedDocument:
    if len(data) > MAX_BYTES:
        raise UnreadableDocument(f"file larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not data.lstrip()[:5] == b"%PDF-":
        raise UnreadableDocument("not a PDF file")
    try:
        with _limits():
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise UnreadableDocument("encrypted PDF")
            page_count = len(reader.pages)
            if page_count == 0:
                raise UnreadableDocument("PDF without pages")
            if page_count > MAX_PAGES:
                raise UnreadableDocument(f"more than {MAX_PAGES} pages")
            pages = [_page_text(reader.pages[index]) for index in range(page_count)]
            scanned = [
                not _has_text(text) and _is_scanned(reader.pages[index])
                for index, text in enumerate(pages)
            ]
            heading = _prominent_text(reader.pages[0])
            attachments = _attachments(reader)
    except UnreadableDocument:
        raise
    except Exception as error:
        # pypdf raises a wide range of exceptions on malformed files, and not only its own:
        # arithmetic and lookup errors, a missing optional dependency for AES.
        raise UnreadableDocument(f"malformed PDF ({type(error).__name__})") from error

    text = pages[0]
    for number, page in enumerate(pages[1:], start=2):
        text += PAGE_BREAK.format(number=number) + page
    return ParsedDocument(
        sha256=sha256_of(data),
        page_count=page_count,
        text=text.strip("\n"),
        has_text_layer=not any(scanned) and any(_has_text(page) for page in pages),
        attachments=attachments,
        heading=heading,
    )


def _has_text(page_text: str) -> bool:
    return sum(1 for char in page_text if char.isalnum()) >= MIN_TEXT_CHARACTERS


def _page_text(page: PageObject) -> str:
    raw = page.extract_text(
        extraction_mode="layout",
        layout_mode_space_vertically=False,
        layout_mode_scale_weight=_LAYOUT_SCALE,
    )
    lines = [line.rstrip() for line in raw.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def _is_scanned(page: PageObject, resources: Any = None, depth: int = 0) -> bool:
    """Whether the page draws an image large enough to be the page itself."""
    resources = page.get("/Resources") if resources is None else resources
    resources = resources.get_object() if resources is not None else None
    if not isinstance(resources, DictionaryObject):
        return False
    xobjects = resources.get("/XObject")
    xobjects = xobjects.get_object() if xobjects is not None else None
    if not isinstance(xobjects, DictionaryObject):
        return False
    for reference in xobjects.values():
        xobject = reference.get_object()
        if not isinstance(xobject, DictionaryObject):
            continue
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            pixels = int(xobject.get("/Width", 0)) * int(xobject.get("/Height", 0))
            if pixels >= MIN_SCAN_PIXELS:
                return True
        elif subtype == "/Form" and depth < _FORM_DEPTH:
            nested = xobject.get("/Resources")
            if nested is not None and _is_scanned(page, nested, depth + 1):
                return True
    return False


def _prominent_text(page: PageObject) -> str:
    """What the page prints clearly larger than most of its characters, in drawing order."""
    fragments: list[tuple[float, str]] = []

    def visit(text: str, cm: list[float], tm: list[float], _font: Any, size: float) -> None:
        words = " ".join(text.split())
        if words:
            scale = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
            fragments.append((abs(size) * scale, words))

    page.extract_text(visitor_text=visit)
    if not fragments:
        return ""
    weights: Counter[float] = Counter()
    for size, words in fragments:
        weights[round(size, 1)] += len(words)
    half, seen, median = sum(weights.values()) / 2, 0, 0.0
    for size in sorted(weights):
        seen += weights[size]
        if seen >= half:
            median = size
            break
    large = " ".join(words for size, words in fragments if size >= median * _HEADING_RATIO)
    return large[:_MAX_HEADING_CHARACTERS]


def _attachments(reader: PdfReader) -> dict[str, bytes]:
    """The XML attachments of the file, by name. Nothing else is decompressed."""
    found: dict[str, bytes] = {}
    for position, embedded in enumerate(reader.attachment_list):
        if position >= MAX_ATTACHMENTS:
            break
        name = str(embedded.name)
        if not name.lower().endswith(".xml") or name in found:
            continue
        declared = embedded.size
        if isinstance(declared, int) and declared > MAX_ATTACHMENT_BYTES:
            continue
        try:
            content = embedded.content
        except pypdf.errors.LimitReachedError:
            continue
        if len(content) <= MAX_ATTACHMENT_BYTES:
            found[name] = content
    return found


def _open(data: bytes) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(data)
    except Exception as error:
        raise UnreadableDocument("PDF could not be rendered") from error


def _render(page: Any, dpi: int, *, grayscale: bool) -> bytes:
    """One page as PNG, at `dpi` or at whatever resolution keeps it under the pixel limit."""
    scale = dpi / 72
    width, height = page.get_size()
    pixels = width * height * scale * scale
    if pixels > MAX_PAGE_PIXELS:
        scale *= math.sqrt(MAX_PAGE_PIXELS / pixels)
    try:
        bitmap = page.render(scale=scale, grayscale=grayscale)
        buffer = BytesIO()
        # Not optimised: the smallest file takes ten times as long to write, for a
        # few percent, and the pixels are the same.
        bitmap.to_pil().save(buffer, format="PNG")
    except Exception as error:
        raise UnreadableDocument("page could not be rendered") from error
    return buffer.getvalue()


def render_page(data: bytes, number: int, *, dpi: int = 110) -> bytes | None:
    """Render one page (numbered from 1) as a PNG for display; None if there is no such page.

    The review console shows these images. The reviewer's browser never opens the
    supplier's file itself.
    """
    document = _open(data)
    try:
        if not 1 <= number <= min(len(document), MAX_PAGES):
            return None
        return _render(document[number - 1], dpi, grayscale=False)
    finally:
        document.close()


def render_pages(data: bytes, *, dpi: int = 150, max_pages: int = 4) -> list[bytes]:
    """Render the first pages as PNG images, for a model that reads images."""
    document = _open(data)
    try:
        return [
            _render(document[index], dpi, grayscale=True)
            for index in range(min(len(document), max_pages))
        ]
    finally:
        document.close()
