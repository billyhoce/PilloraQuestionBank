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
    paper_number: Optional[str] = None


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
    """Render a PDF from a manual selection of questions.

    ``variant='question'`` and ``'answer'`` each render one paper (the frontend
    calls twice for the separate-PDFs mode); ``'combined'`` renders both in a
    single PDF, with the answer paper appended after the question paper.
    """

    question_ids: list[int] = Field(min_length=1)  # empty -> 422
    variant: Literal["question", "answer", "combined"] = "question"
    header_text: str = ""
