from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    select,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.db import Base


class Subject(Base):
    __tablename__ = "subject"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class SchoolLevel(Base):
    __tablename__ = "school_level"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)


class Stream(Base):
    __tablename__ = "stream"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    school_level_id: Mapped[int] = mapped_column(
        ForeignKey("school_level.id", ondelete="RESTRICT"), nullable=False
    )

    school_level: Mapped[SchoolLevel] = relationship()


class Level(Base):
    __tablename__ = "level"
    __table_args__ = (UniqueConstraint("name", "school_level_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    school_level_id: Mapped[int] = mapped_column(
        ForeignKey("school_level.id", ondelete="RESTRICT"), nullable=False
    )

    school_level: Mapped[SchoolLevel] = relationship()


class School(Base):
    __tablename__ = "school"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)


class ExamType(Base):
    __tablename__ = "exam_type"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)


class Topic(Base):
    __tablename__ = "topic"
    __table_args__ = (
        UniqueConstraint("subject_id", "stream_id", "name", name="uq_topic_subject_stream_name"),
        UniqueConstraint("subject_id", "stream_id", "topic_number", name="uq_topic_subject_stream_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id", ondelete="RESTRICT"), nullable=False)
    stream_id: Mapped[int] = mapped_column(ForeignKey("stream.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    topic_number: Mapped[int] = mapped_column(Integer, nullable=False)

    subject: Mapped[Subject] = relationship()
    stream: Mapped[Stream] = relationship()
    subtopics: Mapped[list["Subtopic"]] = relationship(back_populates="topic", cascade="all, delete-orphan")


class Subtopic(Base):
    __tablename__ = "subtopic"
    __table_args__ = (UniqueConstraint("topic_id", "name", name="uq_subtopic_topic_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topic.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)

    topic: Mapped[Topic] = relationship(back_populates="subtopics")


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class CoverTitle(Base):
    """Admin-curated cover titles. Non-admin users must pick their generated
    paper's cover title from this list (admins may type free text)."""

    __tablename__ = "cover_title"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class GenerationConfig(Base):
    """Singleton row (id=1) of admin-set paper-generation presets. Non-admin
    generations always use the cover body / header / additional instructions /
    footer stored here; the subtitle placeholders are the grey hint text shown
    in the Generate form. ``header_text`` is the branding drawn right-aligned on
    the top rule of every page; ``additional_instructions`` is the exam
    instructions drawn below the top rule on the first page.

    Those four text fields are **rich text** — the paragraph/bold/italic/
    underline/link HTML subset the editor produces and ``app/pdf/rich_text.py``
    sanitizes — so all of them are ``Text``, not short strings. Plain text stored
    before they became rich text still renders (and is converted to HTML by the
    a1b2c3d4e5f7 migration)."""

    __tablename__ = "generation_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_generation_config_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subtitle1_placeholder: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subtitle2_placeholder: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    cover_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    header_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    additional_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    footer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class User(Base):
    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint("role IN ('admin', 'public', 'premium')", name="ck_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    # Null for accounts created via Google — they have no password to verify.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Google's stable subject id. Set once an account signs in with Google; we key
    # off this rather than email, which a Google account can change.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="public")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Paper(Base):
    __tablename__ = "paper"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id", ondelete="RESTRICT"), nullable=False)
    stream_id: Mapped[int] = mapped_column(ForeignKey("stream.id", ondelete="RESTRICT"), nullable=False)
    level_id: Mapped[int] = mapped_column(ForeignKey("level.id", ondelete="RESTRICT"), nullable=False)
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id", ondelete="RESTRICT"), nullable=False)
    exam_type_id: Mapped[int] = mapped_column(ForeignKey("exam_type.id", ondelete="RESTRICT"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    paper_number: Mapped[str] = mapped_column(String(8), nullable=False)
    is_premium: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    questions: Mapped[list["Question"]] = relationship(back_populates="paper", cascade="all, delete-orphan")

    subject:   Mapped["Subject"]   = relationship()
    stream:    Mapped["Stream"]    = relationship()
    level:     Mapped["Level"]     = relationship()
    school:    Mapped["School"]    = relationship()
    exam_type: Mapped["ExamType"]  = relationship()


class Question(Base):
    """One exam question, imported as a single set of page images.

    Topics, subtopics and marks belong to the question's *parts* — (a), (b),
    (a)(i) … — not to the question itself. A question always has at least one
    part; a question with no printed parts is modelled as a single part whose
    ``label`` is ``""``. The question's marks total is derived (``total_marks``)
    rather than stored, so it can never disagree with its parts.
    """

    __tablename__ = "question"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper.id", ondelete="CASCADE"), nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    paper: Mapped[Paper] = relationship(back_populates="questions")
    pages: Mapped[list["QuestionPage"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    parts: Mapped[list["QuestionPart"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionPart.part_order",
    )
    tags: Mapped[list["QuestionTag"]] = relationship(back_populates="question", cascade="all, delete-orphan")


class QuestionPage(Base):
    __tablename__ = "question_page"
    __table_args__ = (
        UniqueConstraint("question_id", "page_type", "page_order", name="uq_qpage_q_type_order"),
        CheckConstraint("width_px > 0 AND height_px > 0", name="ck_qpage_positive_dims"),
        CheckConstraint("page_type IN ('question', 'answer')", name="ck_qpage_page_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"), nullable=False)
    page_order: Mapped[int] = mapped_column(Integer, nullable=False)
    image_key: Mapped[str] = mapped_column(String(512), nullable=False)
    page_type: Mapped[str] = mapped_column(String(16), nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)

    question: Mapped[Question] = relationship(back_populates="pages")


class QuestionPart(Base):
    """One part of a question — "(a)", "(a)(i)", "(b)" — carrying its own
    topics/subtopics and its own marks.

    ``label`` is the part's designation exactly as printed on the paper, so an
    admin reviewing the question image can match a part to what they see. Note
    that "(a)(i)" and "(a)(ii)" are two independent parts, which is why the
    label cannot be derived from ``part_order``. A question with no printed
    parts has a single part whose label is ``""``.
    """

    __tablename__ = "question_part"
    __table_args__ = (
        UniqueConstraint("question_id", "part_order", name="uq_qpart_question_order"),
        CheckConstraint("part_order >= 0", name="ck_qpart_order_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), nullable=False
    )
    part_order: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    marks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    question: Mapped["Question"] = relationship(back_populates="parts")
    topics: Mapped[list["QuestionTopic"]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )
    part_subtopics: Mapped[list["QuestionSubtopic"]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )


class QuestionTopic(Base):
    __tablename__ = "question_topic"

    part_id: Mapped[int] = mapped_column(
        ForeignKey("question_part.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id", ondelete="RESTRICT"), primary_key=True
    )

    part: Mapped["QuestionPart"] = relationship(back_populates="topics")
    topic: Mapped["Topic"] = relationship()


class QuestionSubtopic(Base):
    __tablename__ = "question_subtopic"
    __table_args__ = (
        # Composite FK enforces that a subtopic can only be assigned when the
        # matching topic is already recorded in question_topic for this part.
        # ON DELETE CASCADE propagates when the topic assignment is removed.
        ForeignKeyConstraint(
            ["part_id", "topic_id"],
            ["question_topic.part_id", "question_topic.topic_id"],
            name="fk_qsubtopic_question_topic",
            ondelete="CASCADE",
        ),
    )

    part_id: Mapped[int] = mapped_column(
        ForeignKey("question_part.id", ondelete="CASCADE"), primary_key=True
    )
    subtopic_id: Mapped[int] = mapped_column(
        ForeignKey("subtopic.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False)

    part: Mapped["QuestionPart"] = relationship(back_populates="part_subtopics")
    subtopic: Mapped["Subtopic"] = relationship()


class QuestionTag(Base):
    __tablename__ = "question_tag"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )

    question: Mapped["Question"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship()


# A question's marks total is the sum of its parts' marks, never a stored
# column, so the two can't drift. Declared here rather than inline on Question
# because it references QuestionPart. NULL when no part carries marks, which is
# what the generation selectors already treat as "unmarked".
Question.total_marks = column_property(
    select(func.sum(QuestionPart.marks))
    .where(QuestionPart.question_id == Question.id)
    .correlate_except(QuestionPart)
    .scalar_subquery()
)
