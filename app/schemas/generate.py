from typing import Optional

from pydantic import BaseModel

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
    subtopic_keyword: Optional[str] = None


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
