"""The single write path for a question's parts, topics, subtopics and marks.

Both the import topic-review step (``POST /api/import/save-topics``) and the
admin question editor (``POST /api/papers/{id}/questions``, ``PUT
/api/questions/{id}``) replace a question's labelling wholesale, so they share
:func:`set_question_parts` rather than each carrying their own copy.
"""

from typing import Any, Iterable

from fastapi import HTTPException

from app.models.orm import QuestionPart, QuestionSubtopic, QuestionTopic, Subtopic, Topic


def scoped_topic_ids(db: Any, subject_id: int, stream_id: int) -> set[int]:
    """Ids of every topic defined for a (subject, stream) — the only topics a
    question on that paper may be labelled with."""
    return {
        tid for (tid,) in db.query(Topic.id)
        .filter(Topic.subject_id == subject_id, Topic.stream_id == stream_id)
        .all()
    }


def validate_parts(db: Any, parts: Iterable[Any], valid_topic_ids: set[int]) -> None:
    """Raise 422 unless every topic is in scope and every subtopic sits under
    the topic it is nested in. Pure validation — writes nothing — so callers can
    check several questions before touching the database."""
    for part in parts:
        for assignment in part.topic_assignments:
            if assignment.topic_id not in valid_topic_ids:
                raise HTTPException(
                    status_code=422, detail=f"Invalid topic_id {assignment.topic_id}"
                )
            for s in assignment.subtopics:
                subtopic = db.get(Subtopic, s.subtopic_id)
                if subtopic is None or subtopic.topic_id != assignment.topic_id:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"subtopic_id {s.subtopic_id} does not belong to "
                            f"topic_id {assignment.topic_id}"
                        ),
                    )


def set_question_parts(
    db: Any,
    question_id: int,
    parts: Iterable[Any],
    valid_topic_ids: set[int],
) -> None:
    """Replace a question's parts, and their topics/subtopics, wholesale.

    ``parts`` are ``PartIn``-shaped objects (``label``, ``marks``,
    ``topic_assignments``) in the order they appear on the paper; ``part_order``
    is assigned from that order. A question always ends up with at least one
    part, so an empty ``parts`` yields a single blank one.

    Validates before deleting anything, so a 422 leaves the existing labelling
    untouched. Callers that write several questions in one request should call
    :func:`validate_parts` across all of them first.
    """
    parts = list(parts)
    validate_parts(db, parts, valid_topic_ids)

    # Deleting the parts cascades to question_topic and question_subtopic.
    db.query(QuestionPart).filter(
        QuestionPart.question_id == question_id
    ).delete(synchronize_session=False)
    db.flush()

    if not parts:
        db.add(QuestionPart(question_id=question_id, part_order=0, label="", marks=None))
        db.flush()
        return

    for order, part in enumerate(parts):
        row = QuestionPart(
            question_id=question_id,
            part_order=order,
            label=(part.label or "")[:32],
            marks=part.marks,
        )
        db.add(row)
        db.flush()  # need row.id for the topic rows below

        # Both sets are scoped to the part, matching the (part_id, topic_id) and
        # (part_id, subtopic_id) primary keys. A payload may name the same topic
        # in two assignments, so deduping per assignment would still collide.
        inserted_topic_ids: set[int] = set()
        seen_subtopic_ids: set[int] = set()
        for assignment in part.topic_assignments:
            if assignment.topic_id not in inserted_topic_ids:
                db.add(QuestionTopic(part_id=row.id, topic_id=assignment.topic_id))
                # The composite FK on question_subtopic requires this row to exist.
                db.flush()
                inserted_topic_ids.add(assignment.topic_id)

            for s in assignment.subtopics:
                if s.subtopic_id in seen_subtopic_ids:
                    continue
                seen_subtopic_ids.add(s.subtopic_id)
                db.add(QuestionSubtopic(
                    part_id=row.id,
                    subtopic_id=s.subtopic_id,
                    topic_id=assignment.topic_id,
                ))

    db.flush()
