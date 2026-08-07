"""Building the filtered, eager-loaded question query.

The single implementation of "narrow a question query by the Browse filters".
Both `GET /api/questions` and `POST /api/generate/select` build their candidate
pool through `apply_filters`, so the two can't drift on what a filter means —
notably `exclusive`, whose subset semantics are easy to get subtly wrong.

This used to live in ``app/routes/questions.py`` as ``_apply_filters``, imported
across module lines by ``routes/generate.py`` and ``routes/papers.py`` despite
the underscore. It is query-building, not routing, so it belongs here.
"""

import re

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app.models.orm import (
    ExamType,
    Level,
    Paper,
    Question,
    QuestionPart,
    QuestionSubtopic,
    QuestionTag,
    QuestionTopic,
    School,
    SchoolLevel,
    Stream,
    Subject,
    Subtopic,
    Tag,
    Topic,
)

# Eager-load options. The list endpoint doesn't serialize parts, but it still has
# to load them — the union of topics is only reachable through them.
PAPER_EAGER = selectinload(Question.paper).options(
    joinedload(Paper.subject),
    joinedload(Paper.stream),
    # The school level behind the level is what the premium gate checks and what
    # names a paper's premium group, so it is loaded with the level itself.
    joinedload(Paper.level).joinedload(Level.school_level),
    joinedload(Paper.school),
    joinedload(Paper.exam_type),
)
PARTS_EAGER = selectinload(Question.parts).options(
    selectinload(QuestionPart.topics).joinedload(QuestionTopic.topic),
    selectinload(QuestionPart.part_subtopics).joinedload(QuestionSubtopic.subtopic),
)
TAG_EAGER = selectinload(Question.tags).options(
    joinedload(QuestionTag.tag),
)


def apply_filters(
    q,
    subject_id,
    stream_id,
    level_id,
    year,
    school_id,
    exam_type_id,
    topic_ids,
    exclusive,
    tag_ids,
    search,
    paper_number=None,
):
    if subject_id is not None:
        q = q.filter(Paper.subject_id == subject_id)
    if stream_id is not None:
        q = q.filter(Paper.stream_id == stream_id)
    if level_id is not None:
        q = q.filter(Paper.level_id == level_id)
    if year is not None:
        q = q.filter(Paper.year == year)
    if school_id is not None:
        q = q.filter(Paper.school_id == school_id)
    if exam_type_id is not None:
        q = q.filter(Paper.exam_type_id == exam_type_id)

    if topic_ids:
        # Topics hang off parts, so both clauses reach through question_part.
        # Semantics are unchanged from when topics were question-level: match
        # if *any* part touches a selected topic, and under `exclusive` require
        # that *no* part carries a topic outside the selection — i.e. the union
        # of the question's topics is a subset of the selection.
        q = q.filter(
            Question.parts.any(
                QuestionPart.topics.any(QuestionTopic.topic_id.in_(topic_ids))
            )
        )
        if exclusive:
            q = q.filter(
                ~Question.parts.any(
                    QuestionPart.topics.any(QuestionTopic.topic_id.notin_(topic_ids))
                )
            )

    if tag_ids:
        q = q.filter(
            Question.tags.any(QuestionTag.tag_id.in_(tag_ids))
        )

    if paper_number:
        pn = paper_number.strip()
        if pn:
            # Exact, case-insensitive match (no wildcards). Paper numbers are short
            # strings that may contain letters, e.g. "1", "2", "a", "b".
            q = q.filter(Paper.paper_number.ilike(pn))

    if search:
        kw = search.strip()
        if kw:
            pattern = f"%{kw}%"
            clauses = [
                Question.parts.any(
                    QuestionPart.topics.any(
                        QuestionTopic.topic.has(Topic.name.ilike(pattern))
                    )
                ),
                Question.parts.any(
                    QuestionPart.part_subtopics.any(
                        QuestionSubtopic.subtopic.has(Subtopic.name.ilike(pattern))
                    )
                ),
                Question.tags.any(
                    QuestionTag.tag.has(Tag.name.ilike(pattern))
                ),
                Paper.school.has(School.name.ilike(pattern)),
                Paper.subject.has(Subject.name.ilike(pattern)),
                Paper.level.has(Level.name.ilike(pattern)),
                Paper.level.has(
                    Level.school_level.has(SchoolLevel.name.ilike(pattern))
                ),
                Paper.stream.has(Stream.name.ilike(pattern)),
                Paper.stream.has(
                    Stream.school_level.has(SchoolLevel.name.ilike(pattern))
                ),
                Paper.exam_type.has(ExamType.name.ilike(pattern)),
            ]
            # A "T{n}" token (e.g. "T10") matches the topic number.
            m = re.fullmatch(r"[Tt]\s*(\d+)", kw)
            if m:
                clauses.append(
                    Question.parts.any(
                        QuestionPart.topics.any(
                            QuestionTopic.topic.has(
                                Topic.topic_number == int(m.group(1))
                            )
                        )
                    )
                )
            if kw.isdigit():
                clauses.append(Paper.year == int(kw))
            q = q.filter(or_(*clauses))

    return q
