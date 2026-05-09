"""PDF layout engine — stub for TDD. Implement to make tests pass."""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QuestionLayout:
    question_id: int
    label: str
    source_label: str
    page_index: int
    question_pages: list
    answer_pages: list = field(default_factory=list)


@dataclass
class LayoutPlan:
    page_count: int
    question_assignments: list[QuestionLayout]
    header_text: str
    has_answer_section: bool


class LayoutEngine:
    def __init__(self, page_capacity_px: int = 2400):
        self.page_capacity_px = page_capacity_px

    def compute_layout(
        self,
        questions: list[QuestionLayout],
        header_text: str,
        include_answers: bool,
    ) -> LayoutPlan:
        raise NotImplementedError

    def render(self, plan: LayoutPlan) -> bytes:
        raise NotImplementedError
