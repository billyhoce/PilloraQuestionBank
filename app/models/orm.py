import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class SiteConfig(Base):
    """Singleton row (id=1) of site-wide settings that are neither reference data
    nor generation presets.

    Kept separate from ``GenerationConfig`` on purpose: that table is scoped to
    paper-generation presets and its endpoint requires authentication, while both
    fields here have to reach **signed-out** visitors — the About page is public
    and the image-protection flag is read by the public Browse page.

    ``about_content`` is rich-text HTML rendered straight into the browser, so it
    is sanitized on write (``app/services/site_config.py``) rather than at render
    time; the PDF sanitizer in ``app/pdf/rich_text.py`` is a different, narrower
    subset and is not used here.
    """

    __tablename__ = "site_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_site_config_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    about_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Client-side deterrent against casual image copying. Off by default.
    protect_images: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


class User(Base):
    """An account. ``role`` says whether it is an admin; premium access is *not*
    stored here — it is the set of school levels in ``premium_school_levels``,
    so "is this user premium" can never disagree with what they can actually
    open. See ``app/services/premium.py``."""

    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint("role IN ('admin', 'public')", name="ck_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Always stored lower-cased — see ``normalize_email`` in app/services/auth.py.
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
    # Stamped on every successful sign-in, both paths — see _set_session_cookie
    # in app/routes/auth.py. Null until the account has ever signed in, which is
    # also true of every admin-created invite.
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Running count of PDFs generated, incremented by POST /api/generate/paper.
    # A counter rather than a log table: nothing needs per-generation history yet.
    papers_generated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    @property
    def is_invited(self) -> bool:
        """An account an admin pre-created that nobody has claimed yet: no
        password and no Google link, so there is no way to sign into it.

        Derived rather than stored, like premium access — a stored flag could
        disagree with the credentials actually on the row. Registering or
        signing in with Google on this address claims the row, keeping its role
        and its premium school levels."""
        return not self.password_hash and not self.google_sub

    # Eagerly loaded: every user row the API returns carries its entitlements,
    # so lazy loading would mean a query per user on /api/users.
    premium_school_levels: Mapped[list[SchoolLevel]] = relationship(
        secondary="user_premium_school_level",
        order_by="SchoolLevel.id",
        lazy="selectin",
    )


class UserPremiumSchoolLevel(Base):
    """One school level a user has premium access to.

    Premium is sold per school level, so entitlement is a set rather than a role
    value — a user may hold several. Both sides cascade: deleting an account or a
    school level takes its grants with it.
    """

    __tablename__ = "user_premium_school_level"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    school_level_id: Mapped[int] = mapped_column(
        ForeignKey("school_level.id", ondelete="CASCADE"), primary_key=True
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
    # Provenance: the auto-import job this paper came from (NULL for manual imports).
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_job.id", ondelete="SET NULL"), nullable=True
    )

    questions: Mapped[list["Question"]] = relationship(back_populates="paper", cascade="all, delete-orphan")

    subject:   Mapped["Subject"]   = relationship()
    stream:    Mapped["Stream"]    = relationship()
    level:     Mapped["Level"]     = relationship()
    school:    Mapped["School"]    = relationship()
    exam_type: Mapped["ExamType"]  = relationship()


_JSON = JSON().with_variant(JSONB(), "postgresql")


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
    # Provenance, written by an auto-import confirm; null for manual imports.
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_question_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # Provenance, written by an auto-import confirm; null for manual imports. The booklet page
    # and the rectangle (PDF points: {"x0","y0","x1","y1"}) this image was cropped from.
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_rect: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

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


# ---------------------------------------------------------------------------
# Auto-import jobs
#
# JSONB / INT[] are Postgres types; the unit tests build the schema on SQLite,
# so each is a portable JSON type with a Postgres variant (as the migration
# creates them).
# ---------------------------------------------------------------------------

_INT_ARRAY = JSON().with_variant(ARRAY(Integer()), "postgresql")

INGEST_JOB_STATUSES = (
    "queued", "running", "review_ready", "failed", "confirmed", "cancelled", "expired",
)
INGEST_TASK_STATUSES = (
    "pending", "ready", "running", "done", "skipped", "failed", "blocked",
)


class IngestJob(Base):
    """One automatic import of a source PDF. See docs/features/ingestion.md."""

    __tablename__ = "ingest_job"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # Unknown until the worker's ``register`` task reads the PDF (null before, and forever for a
    # PDF that failed validation).
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*INGEST_JOB_STATUSES, name="ingest_job_status"),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    proposal: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    proposal_edited: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    # Run report; the worker's ``register`` task stores ``filename_metadata`` here.
    report: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    # Debug bundle copied at report time, once the scratch folder is gone: {"segments": <segments.json>,
    # "ingest": <ingest.json>}. The only trace of the pipeline's artefacts a settled job keeps.
    debug: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    confirmed_paper_ids: Mapped[list[int] | None] = mapped_column(_INT_ARRAY, nullable=True)

    tasks: Mapped[list["IngestTask"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="IngestTask.id",
    )


class IngestEvent(Base):
    """Append-only audit trail of an ingest job (created, claimed, finished, retried, ...).

    Task rows are overwritten on claim and reopen; the history lives here and is kept forever.
    ``kind`` is a free string (see ``app/services/ingest_events.py``); ``data`` holds its details."""

    __tablename__ = "ingest_event"
    __table_args__ = (Index("ix_ingest_event_job_id_id", "job_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL only for reconciler findings about something with no job row (see app/worker/reconcile.py).
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_job.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingest_task.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    data: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict, server_default=text("'{}'"))


class IngestTask(Base):
    """One unit of work in a job; ``section`` is NULL for job-level stages."""

    __tablename__ = "ingest_task"
    __table_args__ = (
        UniqueConstraint("job_id", "section", "stage", name="uq_ingest_task_job_section_stage"),
        # A UNIQUE over a NULL ``section`` never conflicts in Postgres, so
        # job-level tasks (section NULL) get their own partial unique index.
        Index(
            "uq_ingest_task_job_stage_jobwide",
            "job_id",
            "stage",
            unique=True,
            postgresql_where=text("section IS NULL"),
            sqlite_where=text("section IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingest_job.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str | None] = mapped_column(String(8), nullable=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*INGEST_TASK_STATUSES, name="ingest_task_status"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The last ~4 KB of the traceback of the exception a failed stage raised (shown on the job detail).
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(
        _JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    job: Mapped[IngestJob] = relationship(back_populates="tasks")


class WorkerHeartbeat(Base):
    """Single row (``id = 1``) the ingest worker touches so the API can tell it is alive."""

    __tablename__ = "worker_heartbeat"
    __table_args__ = (CheckConstraint("id = 1", name="ck_worker_heartbeat_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingest_job.id", ondelete="SET NULL"), nullable=True
    )
    # When the daily expiry sweep last ran (claimed atomically by the worker).
    last_sweep_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
