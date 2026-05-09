"""Import pipeline service — stub for TDD. Implement to make tests pass."""
from typing import Any

from PIL import Image


def pdf_to_images(pdf_bytes: bytes) -> list[Image.Image]:
    raise NotImplementedError


def confirm_import(payload: dict, created_by: Any, db: Any) -> Any:
    raise NotImplementedError
