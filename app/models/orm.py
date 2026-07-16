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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    generations always use the cover body / header / footer stored here; the
    subtitle placeholders are the grey hint text shown in the Generate form."""

    __tablename__ = "generation_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_generation_config_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subtitle1_placeholder: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subtitle2_placeholder: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    cover_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    header_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    footer_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class User(Base):
    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint("role IN ('admin', 'public', 'premium')", name="ck_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
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
    __tablename__ = "question"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper.id", ondelete="CASCADE"), nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    paper: Mapped[Paper] = relationship(back_populates="questions")
    pages: Mapped[list["QuestionPage"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    topics: Mapped[list["QuestionTopic"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    question_subtopics: Mapped[list["QuestionSubtopic"]] = relationship(back_populates="question", cascade="all, delete-orphan")
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


class QuestionTopic(Base):
    __tablename__ = "question_topic"

    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id", ondelete="RESTRICT"), primary_key=True
    )

    question: Mapped["Question"] = relationship(back_populates="topics")
    topic: Mapped["Topic"] = relationship()


class QuestionSubtopic(Base):
    __tablename__ = "question_subtopic"
    __table_args__ = (
        # Composite FK enforces that a subtopic can only be assigned when the
        # matching topic is already recorded in question_topic for this question.
        # ON DELETE CASCADE propagates when the topic assignment is removed.
        ForeignKeyConstraint(
            ["question_id", "topic_id"],
            ["question_topic.question_id", "question_topic.topic_id"],
            name="fk_qsubtopic_question_topic",
            ondelete="CASCADE",
        ),
    )

    question_id: Mapped[int] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), primary_key=True
    )
    subtopic_id: Mapped[int] = mapped_column(
        ForeignKey("subtopic.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(Integer, nullable=False)

    question: Mapped["Question"] = relationship(back_populates="question_subtopics")
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
