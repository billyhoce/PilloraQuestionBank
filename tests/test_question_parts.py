"""Tests for the shared question-parts write service.

``set_question_parts`` is the single write path behind /api/import/save-topics,
POST /api/papers/{id}/questions and PUT /api/questions/{id}, so it is worth
testing directly rather than only through those routes.
"""
import pytest
from fastapi import HTTPException

from app.models.orm import Question, QuestionPart, QuestionSubtopic, QuestionTopic, Subtopic
from app.services.question_parts import (
    scoped_topic_ids,
    set_question_parts,
    validate_parts,
)


class _Assignment:
    def __init__(self, topic_id, subtopic_ids=()):
        self.topic_id = topic_id
        self.subtopics = [_Subtopic(sid) for sid in subtopic_ids]


class _Subtopic:
    def __init__(self, subtopic_id):
        self.subtopic_id = subtopic_id


class _Part:
    """Stands in for the PartIn pydantic model."""

    def __init__(self, label="", marks=None, topic_assignments=()):
        self.label = label
        self.marks = marks
        self.topic_assignments = list(topic_assignments)


@pytest.fixture
def valid_topic_ids(db_session, sample_paper):
    return scoped_topic_ids(db_session, sample_paper.subject_id, sample_paper.stream_id)


def _parts_of(db_session, question_id):
    return (
        db_session.query(QuestionPart)
        .filter(QuestionPart.question_id == question_id)
        .order_by(QuestionPart.part_order)
        .all()
    )


def test_assigns_part_order_from_list_order(db_session, sample_paper, valid_topic_ids):
    q = sample_paper.questions[0]
    set_question_parts(db_session, q.id, [
        _Part(label="(a)(i)", marks=2),
        _Part(label="(a)(ii)", marks=3),
        _Part(label="(b)", marks=5),
    ], valid_topic_ids)

    parts = _parts_of(db_session, q.id)
    assert [(p.part_order, p.label, p.marks) for p in parts] == [
        (0, "(a)(i)", 2), (1, "(a)(ii)", 3), (2, "(b)", 5),
    ]


def test_derives_the_question_total_from_the_parts(db_session, sample_paper, valid_topic_ids):
    q = sample_paper.questions[0]
    set_question_parts(db_session, q.id, [
        _Part(marks=2), _Part(marks=3), _Part(marks=5),
    ], valid_topic_ids)

    db_session.expire_all()
    assert db_session.get(Question, q.id).total_marks == 10


def test_total_is_null_when_no_part_carries_marks(db_session, sample_paper, valid_topic_ids):
    q = sample_paper.questions[0]
    set_question_parts(db_session, q.id, [_Part(), _Part()], valid_topic_ids)

    db_session.expire_all()
    assert db_session.get(Question, q.id).total_marks is None


def test_empty_parts_yields_one_blank_part(db_session, sample_paper, valid_topic_ids):
    """Every question has at least one part."""
    q = sample_paper.questions[0]
    set_question_parts(db_session, q.id, [], valid_topic_ids)

    parts = _parts_of(db_session, q.id)
    assert len(parts) == 1
    assert (parts[0].part_order, parts[0].label, parts[0].marks) == (0, "", None)


def test_replaces_previous_parts_wholesale(db_session, sample_paper, valid_topic_ids):
    q = sample_paper.questions[0]
    assert len(_parts_of(db_session, q.id)) == 2  # the fixture's (a) and (b)

    set_question_parts(db_session, q.id, [_Part(label="only", marks=1)], valid_topic_ids)

    parts = _parts_of(db_session, q.id)
    assert [p.label for p in parts] == ["only"]


def test_deleting_parts_cascades_to_topics(db_session, sample_paper, reference_data, valid_topic_ids):
    q = sample_paper.questions[0]
    rd = reference_data
    set_question_parts(db_session, q.id, [
        _Part(label="(a)", topic_assignments=[_Assignment(rd["topic"].id, [rd["subtopic"].id])]),
    ], valid_topic_ids)
    assert db_session.query(QuestionTopic).count() == 1
    assert db_session.query(QuestionSubtopic).count() == 1

    set_question_parts(db_session, q.id, [_Part(label="(a)")], valid_topic_ids)

    assert db_session.query(QuestionTopic).count() == 0
    assert db_session.query(QuestionSubtopic).count() == 0


def test_same_subtopic_may_appear_on_two_parts(db_session, sample_paper, reference_data, valid_topic_ids):
    q = sample_paper.questions[0]
    rd = reference_data
    assignment = [_Assignment(rd["topic"].id, [rd["subtopic"].id])]
    set_question_parts(db_session, q.id, [
        _Part(label="(a)", marks=2, topic_assignments=assignment),
        _Part(label="(b)", marks=3, topic_assignments=[_Assignment(rd["topic"].id, [rd["subtopic"].id])]),
    ], valid_topic_ids)

    parts = _parts_of(db_session, q.id)
    for part in parts:
        rows = db_session.query(QuestionSubtopic).filter(QuestionSubtopic.part_id == part.id).all()
        assert [r.subtopic_id for r in rows] == [rd["subtopic"].id]


def test_dedupes_a_repeated_topic_within_one_part(db_session, sample_paper, reference_data, valid_topic_ids):
    q = sample_paper.questions[0]
    rd = reference_data
    set_question_parts(db_session, q.id, [
        _Part(topic_assignments=[
            _Assignment(rd["topic"].id, [rd["subtopic"].id]),
            _Assignment(rd["topic"].id, [rd["subtopic"].id]),
        ]),
    ], valid_topic_ids)

    part = _parts_of(db_session, q.id)[0]
    assert db_session.query(QuestionTopic).filter(QuestionTopic.part_id == part.id).count() == 1
    assert db_session.query(QuestionSubtopic).filter(QuestionSubtopic.part_id == part.id).count() == 1


def test_stores_a_label_at_the_column_width_verbatim(db_session, sample_paper, valid_topic_ids):
    """Over-long labels are rejected by PartIn, so the service stores what it is
    given without truncating it — see test_ingest for the 422."""
    q = sample_paper.questions[0]
    set_question_parts(db_session, q.id, [_Part(label="x" * 32)], valid_topic_ids)

    assert _parts_of(db_session, q.id)[0].label == "x" * 32


def test_rejects_a_topic_outside_the_papers_subject_and_stream(db_session, sample_paper, valid_topic_ids):
    q = sample_paper.questions[0]
    with pytest.raises(HTTPException) as exc:
        set_question_parts(db_session, q.id, [
            _Part(topic_assignments=[_Assignment(99999)]),
        ], valid_topic_ids)
    assert exc.value.status_code == 422


def test_rejects_a_subtopic_that_belongs_to_another_topic(db_session, sample_paper, reference_data, valid_topic_ids):
    """The composite FK enforces this at the DB level too, but a 422 is a much
    better error than an IntegrityError."""
    rd = reference_data
    other_topic_sub = Subtopic(topic_id=rd["topic"].id, name="Quadratics")
    db_session.add(other_topic_sub)
    db_session.flush()

    q = sample_paper.questions[0]
    with pytest.raises(HTTPException) as exc:
        set_question_parts(db_session, q.id, [
            _Part(topic_assignments=[_Assignment(rd["topic"].id, [99999])]),
        ], valid_topic_ids)
    assert exc.value.status_code == 422


def test_validation_failure_leaves_the_existing_parts_untouched(db_session, sample_paper, valid_topic_ids):
    """Validate-before-delete: a 422 must not wipe the question's labelling."""
    q = sample_paper.questions[0]
    before = [(p.part_order, p.label, p.marks) for p in _parts_of(db_session, q.id)]

    with pytest.raises(HTTPException):
        set_question_parts(db_session, q.id, [
            _Part(label="(a)", marks=1),
            _Part(topic_assignments=[_Assignment(99999)]),
        ], valid_topic_ids)

    assert [(p.part_order, p.label, p.marks) for p in _parts_of(db_session, q.id)] == before


def test_validate_parts_writes_nothing(db_session, sample_paper, reference_data, valid_topic_ids):
    """Callers validate several questions before writing any of them."""
    rd = reference_data
    validate_parts(db_session, [
        _Part(topic_assignments=[_Assignment(rd["topic"].id, [rd["subtopic"].id])]),
    ], valid_topic_ids)

    assert db_session.query(QuestionTopic).count() == 0


def test_scoped_topic_ids_only_returns_in_scope_topics(db_session, sample_paper, reference_data):
    from app.models.orm import Stream, Topic

    rd = reference_data
    other_stream = Stream(name="G1", school_level_id=rd["school_level"].id)
    db_session.add(other_stream)
    db_session.flush()
    out_of_scope = Topic(
        subject_id=rd["subject"].id, stream_id=other_stream.id, name="Algebra", topic_number=1
    )
    db_session.add(out_of_scope)
    db_session.flush()

    ids = scoped_topic_ids(db_session, sample_paper.subject_id, sample_paper.stream_id)
    assert rd["topic"].id in ids
    assert out_of_scope.id not in ids
