import io

from PIL import Image

_TARGET_WIDTH = 1760


def standardize(img: Image.Image) -> Image.Image:
    """Store a page image content-only (no baked margin).

    Downscale to ``_TARGET_WIDTH`` (preserving aspect ratio) only when the image
    is wider than the target; images at or below the target are kept as-is. Page
    margins and the question number are added later, during PDF generation.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    orig_w, orig_h = img.size
    if orig_w > _TARGET_WIDTH:
        new_h = round(orig_h * _TARGET_WIDTH / orig_w)
        img = img.resize((_TARGET_WIDTH, new_h), Image.LANCZOS)
    return img


def to_webp_bytes(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def get_dimensions(img: Image.Image) -> tuple[int, int]:
    return img.size


_AI_MAX_LONG_SIDE = 768
_AI_WEBP_QUALITY = 80


def downscale_for_ai(image_bytes: bytes) -> bytes:
    """Resize a stored WebP page to a small long-side for AI input.
    The on-disk / S3 copy is unaffected — this is only for the model call."""
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    w, h = img.size
    long_side = max(w, h)
    if long_side > _AI_MAX_LONG_SIDE:
        scale = _AI_MAX_LONG_SIDE / long_side
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=_AI_WEBP_QUALITY)
    return buf.getvalue()
