import io

from PIL import Image

_TARGET_WIDTH = 2480
_MARGIN_PX = 90


def standardize(img: Image.Image) -> Image.Image:
    orig_w, orig_h = img.size
    canvas = Image.new("RGB", (_TARGET_WIDTH, orig_h), color=(255, 255, 255))
    content_w = min(orig_w, _TARGET_WIDTH - _MARGIN_PX)
    canvas.paste(img.crop((0, 0, content_w, orig_h)), (_MARGIN_PX, 0))
    return canvas


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
