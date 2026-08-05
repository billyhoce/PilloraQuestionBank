from typing import Optional

from pydantic import BaseModel


class PaperInfoSchema(BaseModel):
    id: int
    year: int
    paper_number: str
    is_premium: bool = False
    subject_name: str
    stream_name: str
    level_name: str
    school_name: str
    exam_type_name: str


class QuestionTopicInfo(BaseModel):
    topic_name: str
    topic_number: int
    subtopic_names: list[str]


class QuestionTagInfo(BaseModel):
    id: int
    name: str


class QuestionListItem(BaseModel):
    id: int
    question_number: int
    # Sum of the question's parts' marks. Named ``marks`` (not ``total_marks``)
    # because it is the question's marks as far as any consumer is concerned.
    marks: Optional[int] = None
    paper_info: PaperInfoSchema
    # Union of every part's topics; per-part detail is on the detail endpoint.
    topics: list[QuestionTopicInfo] = []
    tags: list[QuestionTagInfo] = []
    first_page_url: Optional[str] = None
    # True when this question's paper is premium and the viewer isn't entitled;
    # the image URL is withheld and the frontend renders a locked placeholder.
    locked: bool = False


class QuestionListResponse(BaseModel):
    total: int
    items: list[QuestionListItem]


class QuestionPageSchema(BaseModel):
    id: int
    page_order: int
    page_type: str
    width_px: int
    height_px: int
    url: Optional[str] = None


class QuestionPartInfo(BaseModel):
    part_order: int
    # The part's designation as printed, e.g. "(a)(i)". Empty for a question
    # with no lettered parts.
    label: str
    marks: Optional[int] = None
    topics: list[QuestionTopicInfo] = []


class QuestionDetailResponse(BaseModel):
    id: int
    question_number: int
    # Sum of the parts' marks; null when no part carries any.
    marks: Optional[int] = None
    question_pages: list[QuestionPageSchema]
    answer_pages: list[QuestionPageSchema]
    # De-duplicated union of every part's topics — the same shape the list
    # endpoint returns, so the topic chips render identically.
    topics: list[QuestionTopicInfo] = []
    parts: list[QuestionPartInfo] = []
    tags: list[QuestionTagInfo] = []
    # True when the paper is premium and the viewer isn't entitled; page URLs
    # are withheld.
    locked: bool = False
