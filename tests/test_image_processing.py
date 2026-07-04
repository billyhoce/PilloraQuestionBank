"""Tests for image standardization and WebP encoding."""
import io

import pytest
from PIL import Image

from app.pdf.image_processing import downscale_for_ai, get_dimensions, standardize, to_webp_bytes

_TARGET_WIDTH = 1760


def _make_image(width: int, height: int, color=(200, 100, 50)) -> Image.Image:
    return Image.new("RGB", (width, height), color=color)


def test_standardize_wide_image_downscaled_to_target_width():
    img = _make_image(2480, 3508)
    result = standardize(img)
    assert result.width == _TARGET_WIDTH


def test_standardize_downscale_preserves_aspect_ratio():
    # 2480x1240 (2:1) → 1760x880, aspect kept
    img = _make_image(2480, 1240)
    result = standardize(img)
    assert result.size == (_TARGET_WIDTH, 880)


def test_standardize_narrow_image_kept_unchanged():
    # At or below the target width, the image is returned as-is (no upscaling).
    img = _make_image(600, 400)
    result = standardize(img)
    assert result.size == (600, 400)


def test_standardize_image_at_target_width_unchanged():
    img = _make_image(_TARGET_WIDTH, 500)
    result = standardize(img)
    assert result.size == (_TARGET_WIDTH, 500)


def test_standardize_no_left_margin_content_flush_at_zero():
    # Content-only: the top-left pixel is the image content, not white padding.
    img = _make_image(2480, 500, color=(200, 0, 0))
    result = standardize(img)
    assert result.getpixel((0, 0))[:3] == (200, 0, 0)


def test_standardize_returns_rgb():
    img = Image.new("RGBA", (600, 400), color=(0, 128, 0, 255))
    result = standardize(img)
    assert result.mode == "RGB"


def test_to_webp_bytes_returns_webp_format():
    img = _make_image(100, 100)
    data = to_webp_bytes(img, quality=85)
    reopened = Image.open(io.BytesIO(data))
    assert reopened.format == "WEBP"


def test_to_webp_bytes_non_empty():
    img = _make_image(100, 100)
    data = to_webp_bytes(img, quality=85)
    assert len(data) > 0


def test_get_dimensions_returns_width_and_height():
    img = _make_image(2480, 600)
    w, h = get_dimensions(img)
    assert w == 2480
    assert h == 600


def _webp_bytes(width: int, height: int) -> bytes:
    img = _make_image(width, height, color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=85)
    return buf.getvalue()


def test_downscale_for_ai_shrinks_large_image_long_side_to_768():
    raw = _webp_bytes(2480, 3508)
    out = downscale_for_ai(raw)
    img = Image.open(io.BytesIO(out))
    assert max(img.size) <= 768
    assert img.size[1] > img.size[0]  # portrait aspect preserved


def test_downscale_for_ai_leaves_small_image_dimensions_unchanged():
    raw = _webp_bytes(400, 600)
    out = downscale_for_ai(raw)
    img = Image.open(io.BytesIO(out))
    assert img.size == (400, 600)


def test_downscale_for_ai_returns_webp_bytes():
    raw = _webp_bytes(2000, 1000)
    out = downscale_for_ai(raw)
    img = Image.open(io.BytesIO(out))
    assert img.format == "WEBP"
