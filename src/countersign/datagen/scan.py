"""Turn a PDF into what a desktop scanner would produce: page images, no text layer.

Each page is rasterised, slightly rotated, blurred, grained and JPEG-compressed, then
wrapped in a new PDF. The result has no text to extract and nothing to check a value
against: only a model that reads images can process it.
"""

import random
import time
from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter

# A fixed timestamp keeps the output identical from one run to the next.
_EPOCH = time.gmtime(1_767_225_600)  # 2026-01-01T00:00:00Z


def scan(pdf: bytes, rng: random.Random, *, dpi: int = 150) -> bytes:
    document = pdfium.PdfDocument(pdf)
    pages = []
    try:
        for index in range(len(document)):
            image = document[index].render(scale=dpi / 72, grayscale=True).to_pil().convert("L")
            pages.append(_degrade(image, rng))
    finally:
        document.close()
    buffer = BytesIO()
    pages[0].save(
        buffer,
        format="PDF",
        resolution=dpi,
        save_all=True,
        append_images=pages[1:],
        quality=rng.randint(45, 70),
        creationDate=_EPOCH,
        modDate=_EPOCH,
    )
    return buffer.getvalue()


def _degrade(image: Image.Image, rng: random.Random) -> Image.Image:
    image = image.rotate(rng.uniform(-1.2, 1.2), resample=Image.Resampling.BICUBIC, fillcolor=255)
    image = image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))
    grain = Image.frombytes("L", image.size, rng.randbytes(image.width * image.height))
    image = Image.blend(image, grain, alpha=rng.uniform(0.04, 0.09))
    return ImageEnhance.Contrast(image).enhance(rng.uniform(1.0, 1.15))
