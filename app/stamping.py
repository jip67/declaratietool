"""Paraaf: zet een goedkeuringsstempel op de bon en sla het resultaat op als pdf."""

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

try:  # foto's van iPhones
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

STAMP_COLOR = (20, 90, 200)


def stamp_lines(title: str, name: str, when: datetime, reference: str) -> list[str]:
    return [title, name, when.strftime("%d-%m-%Y %H:%M"), reference]


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def stamp_image(source: Path, target: Path, lines: list[str]) -> None:
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    width, height = img.size
    size = max(14, width // 40)
    font = _font(size)
    pad = size // 2
    text_w = max(draw.textlength(line, font=font) for line in lines)
    box_w = int(text_w + 2 * pad)
    box_h = int(len(lines) * size * 1.3 + 2 * pad)
    x1, y1 = width - box_w - pad * 2, height - box_h - pad * 2
    draw.rectangle([x1, y1, x1 + box_w, y1 + box_h], fill=(255, 255, 255, 200), outline=STAMP_COLOR, width=max(2, size // 8))
    for i, line in enumerate(lines):
        draw.text((x1 + pad, y1 + pad + i * size * 1.3), line, fill=STAMP_COLOR, font=font)
    img.save(target, "PDF", resolution=150)


def _overlay(width: float, height: float, lines: list[str]) -> PdfReader:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    size = 10
    pad = 6
    box_w = max(c.stringWidth(line, "Helvetica-Bold", size) for line in lines) + 2 * pad
    box_h = len(lines) * size * 1.3 + 2 * pad
    x, y = width - box_w - 20, 20
    blue = Color(*(v / 255 for v in STAMP_COLOR))
    c.setFillColor(Color(1, 1, 1, alpha=0.85))
    c.setStrokeColor(blue)
    c.setLineWidth(1.5)
    c.rect(x, y, box_w, box_h, fill=1, stroke=1)
    c.setFillColor(blue)
    c.setFont("Helvetica-Bold", size)
    for i, line in enumerate(lines):
        c.drawString(x + pad, y + box_h - pad - (i + 1) * size * 1.3 + 3, line)
    c.save()
    buf.seek(0)
    return PdfReader(buf)


def stamp_pdf(source: Path, target: Path, lines: list[str]) -> None:
    writer = PdfWriter(clone_from=str(source))
    page = writer.pages[0]
    box = page.mediabox
    page.merge_page(_overlay(float(box.width), float(box.height), lines).pages[0])
    with target.open("wb") as fh:
        writer.write(fh)


def stamp_file(source: Path, content_type: str, lines: list[str]) -> Path:
    target = source.with_name(source.stem + "-paraaf.pdf")
    if content_type == "application/pdf":
        stamp_pdf(source, target, lines)
    else:
        stamp_image(source, target, lines)
    return target
