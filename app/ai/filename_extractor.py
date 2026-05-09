"""Filename metadata extractor AI module — stub for TDD. Implement to make tests pass."""
import anthropic
from typing import Any, Optional


def build_filename_prompt(filename: str) -> str:
    raise NotImplementedError


def parse_filename_response(raw: str) -> dict:
    raise NotImplementedError


def resolve_metadata(extracted: dict, db: Any) -> dict:
    raise NotImplementedError


def extract_metadata(filename: str, db: Any) -> dict:
    raise NotImplementedError
