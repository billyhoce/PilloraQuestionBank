from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.questions import QuestionListItem


class GenerateFilters(BaseModel):
    """Mirror of the Browse filter params, used to build the autofill pool."""

    subject_id: Optional[int] = None
    stream_id: Optional[int] = None
    level_id: Optional[int] = None
    year: Optional[int] = None
    school_id: Optional[int] = None
    exam_type_id: Optional[int] = None
    topic_ids: list[int] = []
    exclusive: bool = False
    tag_ids: list[int] = []
    search: Optional[str] = None


class SelectRequest(BaseModel):
    filters: GenerateFilters = GenerateFilters()
    target_marks: int
    exclude_question_ids: list[int] = []


class SelectResponse(BaseModel):
    items: list[QuestionListItem]
    total_marks: int
    target_marks: int
    exact: bool
    warning: Optional[str] = None


class GeneratePaperRequest(BaseModel):
    """Render one PDF variant from a manual selection of questions.

    The frontend calls this twice (``variant='question'`` then ``'answer'``) to
    produce the separate question and answer papers.
    """

    question_ids: list[int] = Field(min_length=1)  # empty -> 422
    variant: Literal["question", "answer"] = "question"
    header_text: str = ""
