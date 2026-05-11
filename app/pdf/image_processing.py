import io

from PIL import Image

_TARGET_WIDTH = 2480
_MARGIN_PX = 180


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
