"""Topic labeler AI module — stub for TDD. Implement to make tests pass."""
import anthropic
from typing import Any


def build_system_prompt(subject: str, stream: str, topics: list[dict]) -> str:
    raise NotImplementedError


def parse_label_response(raw: str, valid_topic_ids: set[int]) -> list[dict]:
    raise NotImplementedError


def label_question(
    question: Any,
    topics: list[dict],
    image_bytes_list: list[bytes],
    db: Any,
) -> None:
    raise NotImplementedError
