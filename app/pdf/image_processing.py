"""Image processing utilities — stub for TDD. Implement to make tests pass."""
from PIL import Image


def standardize(img: Image.Image) -> Image.Image:
    raise NotImplementedError


def to_webp_bytes(img: Image.Image, quality: int = 85) -> bytes:
    raise NotImplementedError


def get_dimensions(img: Image.Image) -> tuple[int, int]:
    raise NotImplementedError
