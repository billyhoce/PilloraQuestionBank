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
    # What the target counts: "marks" (a marks total) or "count" (a number of
    # questions). ``target_value`` is interpreted accordingly.
    target_type: Literal["marks", "count"] = "marks"
    target_value: int
    exclude_question_ids: list[int] = []
    # Picking algorithm: "random" (randomized-restart greedy / random sample) or
    # "in-order" (deterministic pass from the top of the pool).
    algorithm: Literal["random", "in-order"] = "random"


class SelectResponse(BaseModel):
    items: list[QuestionListItem]
    total_marks: int
    count: int
    exact: bool
    warning: Optional[str] = None


class GeneratePaperRequest(BaseModel):
    """Render a PDF from a manual selection of questions.

    ``variant='question'`` and ``'answer'`` each render one paper (the frontend
    calls twice for the separate-PDFs mode); ``'combined'`` renders both in a
    single PDF, with the answer paper appended after the question paper.

    The cover fields drive an optional branded cover page (one per section). The
    marks box on the cover shows the paper total, computed server-side from the
    selected questions. ``cover_subtitle1`` is the topic/subject line; the engine
    appends " – Questions" / " – Answers" per variant. ``cover_body`` is
    rich-text HTML (or legacy plain text), sanitized to the supported subset by
    ``app/pdf/cover_body.py`` before rendering. ``footer_text`` is drawn
    verbatim under the footer rule of every page.

    Only admins control all of these: for non-admin users the server forces
    ``include_cover=True`` and replaces ``cover_body``/``header_text``/
    ``footer_text`` with the admin-set generation config, and ``cover_title``
    must be one of the configured cover titles (see app/routes/generate.py).
    """

    question_ids: list[int] = Field(min_length=1)  # empty -> 422
    variant: Literal["question", "answer", "combined"] = "question"
    header_text: str = ""
    footer_text: str = ""
    include_cover: bool = True
    cover_title: str = ""
    cover_subtitle1: str = ""
    cover_subtitle2: str = ""
    cover_body: str = ""
