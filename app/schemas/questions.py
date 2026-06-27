from typing import Optional

from pydantic import BaseModel


class PaperInfoSchema(BaseModel):
    id: int
    year: int
    paper_number: str
    subject_name: str
    stream_name: str
    level_name: str
    school_name: str
    exam_type_name: str


class QuestionTopicInfo(BaseModel):
    topic_name: str
    subtopic_names: list[str]


class QuestionListItem(BaseModel):
    id: int
    question_number: int
    marks: Optional[int] = None
    paper_info: PaperInfoSchema
    topics: list[QuestionTopicInfo] = []
    first_page_url: Optional[str] = None


class QuestionListResponse(BaseModel):
    total: int
    items: list[QuestionListItem]


class QuestionPageSchema(BaseModel):
    id: int
    page_order: int
    page_type: str
    width_px: int
    height_px: int
    url: str


class QuestionDetailResponse(BaseModel):
    id: int
    question_number: int
    marks: Optional[int] = None
    question_pages: list[QuestionPageSchema]
    answer_pages: list[QuestionPageSchema]
    topics: list[QuestionTopicInfo] = []
