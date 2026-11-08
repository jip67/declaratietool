"""Paraaf: zet de getekende paraaf van de voorzitter op de bon en sla het resultaat op als pdf.

Zonder getekende paraaf (oude goedkeuringen) komt er een tekststempel op, zoals vroeger."""

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

try:  # zet een pdf-pagina om in een afbeelding (voor het voorbeeld met paraaf)
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

try:  # foto's van iPhones
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

STAMP_COLOR = (20, 90, 200)
INK_COLOR = (16, 42, 140)  # donkerblauw, zoals een balpen

# Grenzen voor een getekende paraaf (een PNG uit het tekenvlak in de browser).
SIGNATURE_MAX_BYTES = 1_000_000
SIGNATURE_MAX_SIDE = 4000
SIGNATURE_STORE_SIZE = (900, 450)


class SignatureError(ValueError):
    """De paraaf is leeg of geen bruikbare afbeelding."""


def normalize_signature(data: bytes) -> bytes:
    """Maak van een getekende paraaf een nette PNG: bijgesneden, transparant, in inktkleur.

    Accepteert een PNG met transparante achtergrond (het tekenvlak) of een afbeelding met
    donkere lijnen op een lichte achtergrond. Gooit SignatureError als er niets op staat."""
    if not data or len(data) > SIGNATURE_MAX_BYTES:
        raise SignatureError("size")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if max(img.size) > SIGNATURE_MAX_SIDE:
                raise SignatureError("size")
            img = img.convert("RGBA")
    except SignatureError:
        raise
    except Exception as exc:
        raise SignatureError("format") from exc
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] == 255:
        # Geen transparantie: de donkere pixels zijn de lijnen.
        alpha = ImageOps.invert(img.convert("L"))
    alpha = alpha.point(lambda v: 0 if v < 24 else v)
    box = alpha.getbbox()
    if box is None or (box[2] - box[0]) * (box[3] - box[1]) < 100 or sum(alpha.histogram()[24:]) < 30:
        raise SignatureError("empty")
    pad = 4
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad))
    alpha = alpha.crop(box)
    out = Image.new("RGBA", alpha.size, INK_COLOR + (0,))
    out.putalpha(alpha)
    out.thumbnail(SIGNATURE_STORE_SIZE)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def stamp_lines(title: str, name: str, when: datetime, reference: str) -> list[str]:
    return [title, name, when.strftime("%d-%m-%Y %H:%M"), reference]


def signature_caption(lines: list[str]) -> list[str]:
    """Onder een getekende paraaf: naam, en tijdstip met kenmerk (zonder het woord 'goedgekeurd')."""
    _title, name, when, reference = lines
    return [line for line in (name, f"{when} · {reference}") if line.strip(" ·")]


def _font_regular(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _signature_on_image(img: Image.Image, signature: bytes, lines: list[str]) -> None:
    width, height = img.size
    with Image.open(io.BytesIO(signature)) as sig:
        sig = sig.convert("RGBA")
    target_w = max(120, width // 4)
    scale = min(target_w / sig.width, (height / 6) / sig.height)
    sig = sig.resize((max(1, int(sig.width * scale)), max(1, int(sig.height * scale))), Image.LANCZOS)
    caption = signature_caption(lines)
    size = max(11, width // 70)
    font = _font_regular(size)
    draw = ImageDraw.Draw(img, "RGBA")
    pad = size // 2
    text_w = max((draw.textlength(line, font=font) for line in caption), default=0)
    box_w = int(max(sig.width, text_w) + 2 * pad)
    box_h = int(sig.height + len(caption) * size * 1.3 + 2 * pad)
    x1, y1 = width - box_w - pad * 2, height - box_h - pad * 2
    draw.rectangle([x1, y1, x1 + box_w, y1 + box_h], fill=(255, 255, 255, 170))
    img.paste(sig, (x1 + pad + (box_w - 2 * pad - sig.width) // 2, y1 + pad), sig)
    for i, line in enumerate(caption):
        draw.text((x1 + pad, y1 + pad + sig.height + i * size * 1.3), line, fill=INK_COLOR, font=font)


def stamp_image(source: Path, target: Path, lines: list[str], signature: bytes | None = None) -> None:
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
    if signature:
        _signature_on_image(img, signature, lines)
        img.save(target, "PDF", resolution=150)
        return
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


def _signature_overlay(width: float, height: float, signature: bytes, lines: list[str]) -> PdfReader:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    reader = ImageReader(io.BytesIO(signature))
    sig_w, sig_h = reader.getSize()
    scale = min(150 / sig_w, 70 / sig_h)
    w, h = sig_w * scale, sig_h * scale
    caption = signature_caption(lines)
    size, pad = 7, 5
    text_w = max((c.stringWidth(line, "Helvetica", size) for line in caption), default=0)
    box_w = max(w, text_w) + 2 * pad
    box_h = h + len(caption) * size * 1.3 + 2 * pad
    x, y = width - box_w - 20, 20
    c.setFillColor(Color(1, 1, 1, alpha=0.7))
    c.rect(x, y, box_w, box_h, fill=1, stroke=0)
    c.drawImage(reader, x + (box_w - w) / 2, y + box_h - pad - h, width=w, height=h, mask="auto")
    c.setFillColor(Color(*(v / 255 for v in INK_COLOR)))
    c.setFont("Helvetica", size)
    for i, line in enumerate(caption):
        c.drawString(x + pad, y + box_h - pad - h - (i + 1) * size * 1.3 + 2, line)
    c.save()
    buf.seek(0)
    return PdfReader(buf)


def stamp_pdf(source: Path, target: Path, lines: list[str], signature: bytes | None = None) -> None:
    writer = PdfWriter(clone_from=str(source))
    page = writer.pages[0]
    box = page.mediabox
    width, height = float(box.width), float(box.height)
    overlay = _signature_overlay(width, height, signature, lines) if signature else _overlay(width, height, lines)
    page.merge_page(overlay.pages[0])
    with target.open("wb") as fh:
        writer.write(fh)


def stamp_file(source: Path, content_type: str, lines: list[str], signature: bytes | None = None) -> Path:
    target = source.with_name(source.stem + "-paraaf.pdf")
    if content_type == "application/pdf":
        stamp_pdf(source, target, lines, signature)
    else:
        stamp_image(source, target, lines, signature)
    try:
        render_preview(target)
    except Exception:  # het voorbeeld is handig, niet nodig; zonder wordt het later opnieuw geprobeerd
        pass
    return target


# Breedte van het voorbeeld met paraaf: scherp genoeg om op een telefoon in te zoomen.
PREVIEW_WIDTH = 1400


def preview_path(stamped: Path) -> Path:
    """Het voorbeeld (PNG van pagina 1) staat naast de pdf met paraaf."""
    return stamped.with_suffix(".png")


def render_preview(stamped: Path) -> Path:
    """Maak een afbeelding van de eerste pagina van de pdf met paraaf, zodat je op een telefoon
    in één oogopslag de hele pagina met de paraaf ziet. Bestaat hij al, dan wordt hij hergebruikt."""
    target = preview_path(stamped)
    if target.exists() and target.stat().st_mtime >= stamped.stat().st_mtime:
        return target
    if pdfium is None:
        raise RuntimeError("pypdfium2 ontbreekt")
    pdf = pdfium.PdfDocument(str(stamped))
    try:
        page = pdf[0]
        width = page.get_width() or 1
        img = page.render(scale=PREVIEW_WIDTH / width).to_pil().convert("RGB")
        page.close()
    finally:
        pdf.close()
    tmp = target.with_name(target.name + ".tmp")
    img.save(tmp, "PNG", optimize=True)
    tmp.replace(target)
    return target
