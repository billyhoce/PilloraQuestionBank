"""Tests for image standardization and WebP encoding."""
import io

import pytest
from PIL import Image

from app.pdf.image_processing import downscale_for_ai, get_dimensions, standardize, to_webp_bytes

_TARGET_WIDTH = 2480
_MARGIN_PX = 90


def _make_image(width: int, height: int, color=(200, 100, 50)) -> Image.Image:
    return Image.new("RGB", (width, height), color=color)


def test_standardize_narrow_image_width_becomes_2480():
    img = _make_image(600, 400)
    result = standardize(img)
    assert result.width == _TARGET_WIDTH


def test_standardize_adds_exactly_90px_left_margin():
    # Fill with a distinctive non-white color
    img = _make_image(_TARGET_WIDTH, 500, color=(200, 0, 0))
    result = standardize(img)
    # Left margin pixels should be white
    assert result.getpixel((0, 0))[:3] == (255, 255, 255)
    assert result.getpixel((_MARGIN_PX - 1, 0))[:3] == (255, 255, 255)
    # Content starts at MARGIN_PX
    assert result.getpixel((_MARGIN_PX, 0))[:3] == (200, 0, 0)


def test_standardize_preserves_height():
    img = _make_image(_TARGET_WIDTH, 1234)
    result = standardize(img)
    assert result.height == 1234


def test_standardize_narrow_image_right_side_is_white():
    # 300-wide image → padded to 2480; content occupies [180:480], rest is white
    img = _make_image(300, 100, color=(0, 128, 0))
    result = standardize(img)
    # Right side beyond margin + content should be white
    assert result.getpixel((_TARGET_WIDTH - 1, 0))[:3] == (255, 255, 255)


def test_standardize_wide_image_content_not_cropped():
    # Input exactly at target width: content should start at MARGIN_PX, not be shifted beyond
    img = _make_image(_TARGET_WIDTH, 300, color=(0, 0, 200))
    result = standardize(img)
    assert result.width == _TARGET_WIDTH
    assert result.getpixel((_MARGIN_PX, 0))[:3] == (0, 0, 200)


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
