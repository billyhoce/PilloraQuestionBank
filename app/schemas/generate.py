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


# Canonical cover-page defaults. The frontend fetches these via
# GET /api/generate/cover-defaults to pre-fill the editable fields, and they
# double as the schema defaults so the API stays robust when a client omits
# a field.
DEFAULT_COVER_TITLE = "Topical Worksheets"

DEFAULT_COVER_BODY = (
    "Dear students,\n"
    "\n"
    "Did you know that research shows students learn best when they focus on topical practice "
    "first before moving on to full-paper practice? Many students jump straight into full exam "
    "papers as practice without realising that they are losing marks in the SAME few areas every "
    "time.\n"
    "\n"
    "That is why I have compiled and vetted these topical worksheets, making sure they contain "
    "only exam-style questions.\n"
    "\n"
    "I recommend identifying your weaker topics and practising them using these topical worksheets "
    "before moving to timed full papers. If you need help figuring out your weaker areas, or need "
    "to clarify anything about any specific topic, come book a consultation session with me "
    "through my website, without having to sign up for any tuition package.\n"
    "\n"
    "For more resources such as Math and Science notes, topical worksheets, WA1–3/EOY papers, and "
    "textbook/workbook answers, please visit www.pillora.com.sg.\n"
    "\n"
    "You can do it! All the best :)\n"
    "\n"
    "Teacher Jia Xin\n"
    "Founder of Pillora Learning"
)


class GeneratePaperRequest(BaseModel):
    """Render a PDF from a manual selection of questions.

    ``variant='question'`` and ``'answer'`` each render one paper (the frontend
    calls twice for the separate-PDFs mode); ``'combined'`` renders both in a
    single PDF, with the answer paper appended after the question paper.

    The cover fields drive an optional branded cover page (one per section). The
    marks box on the cover shows the paper total, computed server-side from the
    selected questions. ``cover_subtitle1`` is the topic/subject line; the engine
    appends " – Questions" / " – Answers" per variant.
    """

    question_ids: list[int] = Field(min_length=1)  # empty -> 422
    variant: Literal["question", "answer", "combined"] = "question"
    header_text: str = ""
    include_cover: bool = True
    cover_title: str = DEFAULT_COVER_TITLE
    cover_subtitle1: str = ""
    cover_subtitle2: str = ""
    cover_body: str = DEFAULT_COVER_BODY


class CoverDefaultsResponse(BaseModel):
    """Canonical cover-page defaults, served to the frontend so the editable
    fields are pre-filled without hardcoding a second copy of the text."""

    cover_title: str = DEFAULT_COVER_TITLE
    cover_body: str = DEFAULT_COVER_BODY
