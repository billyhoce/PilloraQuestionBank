"""Tests for the questions list/filter and detail endpoints."""
from datetime import datetime

import pytest

from app.models.orm import Paper, Question, QuestionPage, QuestionSubtopic, QuestionTopic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_paper(db_session, rd, admin_user, year=2024, school=None) -> Paper:
    paper = Paper(
        subject_id=rd["subject"].id,
        stream_id=rd["stream"].id,
        level_id=rd["level"].id,
        school_id=(school or rd["school"]).id,
        exam_type_id=rd["exam_type"].id,
        year=year,
        paper_number="1",
        created_by=admin_user.id,
        created_at=datetime.now(datetime.timezone.utc),
    )
    db_session.add(paper)
    db_session.flush()
    return paper


def _add_question(db_session, paper, number=1, marks=5) -> Question:
    q = Question(
        paper_id=paper.id,
        question_number=number,
        marks=marks,
        created_at=datetime.now(datetime.timezone.utc),
    )
    db_session.add(q)
    db_session.flush()
    _add_page(db_session, q, "question")
    return q


def _add_page(db_session, question, page_type="question") -> QuestionPage:
    page = QuestionPage(
        question_id=question.id,
        page_order=0,
        image_key=f"papers/{question.paper_id}/q{question.question_number}/{page_type}_0.webp",
        page_type=page_type,
        width_px=2480,
        height_px=600,
    )
    db_session.add(page)
    db_session.flush()
    return page


# ---------------------------------------------------------------------------
# Public access (no auth required)
# ---------------------------------------------------------------------------


def test_list_questions_is_public(client):
    resp = client.get("/api/questions")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------


def test_list_questions_no_filters_returns_all(public_client, sample_paper):
    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3


def test_list_questions_filter_by_subject_id(public_client, db_session, reference_data, admin_user):
    rd = reference_data

    # Second subject
    from app.models.orm import Subject, Stream, SchoolLevel
    sl = SchoolLevel(name="Tertiary")
    db_session.add(sl)
    db_session.flush()
    subj2 = Subject(name="History")
    db_session.add(subj2)
    db_session.flush()
    stream2 = Stream(name="Arts", school_level_id=sl.id)
    db_session.add(stream2)
    db_session.flush()
    from app.models.orm import Level, School, ExamType
    level2 = Level(name="Year 1", sort_order=1, school_level_id=sl.id)
    db_session.add(level2)
    db_session.flush()
    school2 = School(name="Anglo-Chinese School")
    db_session.add(school2)
    db_session.flush()
    et2 = ExamType(name="WA1")
    db_session.add(et2)
    db_session.flush()

    paper1 = _add_paper(db_session, rd, admin_user)
    _add_question(db_session, paper1)

    paper2 = Paper(
        subject_id=subj2.id, stream_id=stream2.id, level_id=level2.id,
        school_id=school2.id, exam_type_id=et2.id,
        year=2024, paper_number="1",
        created_by=admin_user.id, created_at=datetime.now(datetime.timezone.utc),
    )
    db_session.add(paper2)
    db_session.flush()
    _add_question(db_session, paper2)

    resp = public_client.get(f"/api/questions?subject_id={rd['subject'].id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_questions_filter_by_year(public_client, db_session, reference_data, admin_user):
    paper_2023 = _add_paper(db_session, reference_data, admin_user, year=2023)
    paper_2024 = _add_paper(db_session, reference_data, admin_user, year=2024)
    _add_question(db_session, paper_2023)
    _add_question(db_session, paper_2024)

    resp = public_client.get("/api/questions?year=2024")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_questions_filter_by_topic_ids(public_client, db_session, reference_data, admin_user):
    """topic_ids filter matches any question assigned to one of the listed topics."""
    paper = _add_paper(db_session, reference_data, admin_user)
    q_with_topic = _add_question(db_session, paper, number=1)
    q_no_topic = _add_question(db_session, paper, number=2)

    qt = QuestionTopic(question_id=q_with_topic.id, topic_id=reference_data["topic"].id)
    db_session.add(qt)
    db_session.flush()

    resp = public_client.get(f"/api/questions?topic_ids={reference_data['topic'].id}")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_with_topic.id in ids
    assert q_no_topic.id not in ids


def test_list_questions_filter_by_topic_ids_inclusive_union(public_client, db_session, reference_data, admin_user):
    """Multiple topic_ids should be OR-combined (inclusive) by default."""
    from app.models.orm import Topic, Subtopic
    rd = reference_data
    paper = _add_paper(db_session, rd, admin_user)

    topic_b = Topic(subject_id=rd["subject"].id, stream_id=rd["stream"].id, name="Geometry", topic_number=2)
    db_session.add(topic_b)
    db_session.flush()
    sub_b = Subtopic(topic_id=topic_b.id, name="Circles")
    db_session.add(sub_b)
    db_session.flush()

    q_a = _add_question(db_session, paper, number=1)
    q_b = _add_question(db_session, paper, number=2)
    q_none = _add_question(db_session, paper, number=3)
    db_session.add_all([
        QuestionTopic(question_id=q_a.id, topic_id=rd["topic"].id),
        QuestionTopic(question_id=q_b.id, topic_id=topic_b.id),
    ])
    db_session.flush()

    resp = public_client.get(
        f"/api/questions?topic_ids={rd['topic'].id}&topic_ids={topic_b.id}"
    )
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_a.id in ids
    assert q_b.id in ids
    assert q_none.id not in ids


def test_list_questions_exclusive_topic_filter(public_client, db_session, reference_data, admin_user):
    """exclusive=true keeps only questions whose topic set is a subset of the selection."""
    from app.models.orm import Topic, Subtopic
    rd = reference_data
    paper = _add_paper(db_session, rd, admin_user)

    topic_b = Topic(subject_id=rd["subject"].id, stream_id=rd["stream"].id, name="Geometry", topic_number=2)
    db_session.add(topic_b)
    db_session.flush()
    sub_b = Subtopic(topic_id=topic_b.id, name="Circles")
    db_session.add(sub_b)
    db_session.flush()

    q_only_a = _add_question(db_session, paper, number=1)
    q_a_and_b = _add_question(db_session, paper, number=2)
    db_session.add_all([
        QuestionTopic(question_id=q_only_a.id, topic_id=rd["topic"].id),
        QuestionTopic(question_id=q_a_and_b.id, topic_id=rd["topic"].id),
        QuestionTopic(question_id=q_a_and_b.id, topic_id=topic_b.id),
    ])
    db_session.flush()

    # Inclusive (default): both questions match topic A
    resp = public_client.get(f"/api/questions?topic_ids={rd['topic'].id}")
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_only_a.id in ids
    assert q_a_and_b.id in ids

    # Exclusive: only the question whose topics are entirely within {A}
    resp = public_client.get(f"/api/questions?topic_ids={rd['topic'].id}&exclusive=true")
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_only_a.id in ids
    assert q_a_and_b.id not in ids


def test_list_questions_subtopic_keyword(public_client, db_session, reference_data, admin_user):
    from app.models.orm import Subtopic
    paper = _add_paper(db_session, reference_data, admin_user)
    q_match = _add_question(db_session, paper, number=1)
    q_other = _add_question(db_session, paper, number=2)

    other_sub = Subtopic(topic_id=reference_data["topic"].id, name="Quadratic Equations")
    db_session.add(other_sub)
    db_session.flush()

    db_session.add(QuestionTopic(question_id=q_match.id, topic_id=reference_data["topic"].id))
    db_session.flush()
    db_session.add(QuestionSubtopic(
        question_id=q_match.id,
        subtopic_id=reference_data["subtopic"].id,
        topic_id=reference_data["topic"].id,
    ))
    db_session.add(QuestionTopic(question_id=q_other.id, topic_id=reference_data["topic"].id))
    db_session.flush()
    db_session.add(QuestionSubtopic(
        question_id=q_other.id,
        subtopic_id=other_sub.id,
        topic_id=reference_data["topic"].id,
    ))
    db_session.flush()

    resp = public_client.get("/api/questions?subtopic_keyword=linear")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_match.id in ids
    assert q_other.id not in ids


def test_list_questions_multi_filter_conjunction(public_client, db_session, reference_data, admin_user):
    paper_2024 = _add_paper(db_session, reference_data, admin_user, year=2024)
    paper_2023 = _add_paper(db_session, reference_data, admin_user, year=2023)
    q_2024 = _add_question(db_session, paper_2024)
    q_2023 = _add_question(db_session, paper_2023)

    resp = public_client.get(f"/api/questions?subject_id={reference_data['subject'].id}&year=2024")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_2024.id in ids
    assert q_2023.id not in ids


def test_list_questions_pagination_page2(public_client, db_session, reference_data, admin_user):
    paper = _add_paper(db_session, reference_data, admin_user)
    for i in range(1, 16):  # 15 questions
        _add_question(db_session, paper, number=i)

    resp = public_client.get("/api/questions?page=2&page_size=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 15
    assert len(body["items"]) == 5  # 15 - 10 = 5 on page 2


def test_list_questions_response_shape(public_client, sample_paper, reference_data):
    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert "id" in item
    assert "question_number" in item
    assert "marks" in item
    assert "paper_info" in item
    assert "topics" in item
    assert "first_page_url" in item


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


def test_get_question_returns_all_pages(public_client, sample_paper, db_session):
    # Q2 in sample_paper has 1 question page + 1 answer page
    from app.models.orm import Question
    q2 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=2).one()

    from unittest.mock import patch
    with patch("app.routes.questions.get_presigned_url", return_value="https://fake.url"):
        resp = public_client.get(f"/api/questions/{q2.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["question_pages"]) == 1
    assert len(body["answer_pages"]) == 1


def test_get_question_pages_include_presigned_urls(public_client, sample_paper, db_session):
    from app.models.orm import Question
    from unittest.mock import patch

    q1 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=1).one()

    with patch("app.routes.questions.get_presigned_url", return_value="https://example.com/signed"):
        resp = public_client.get(f"/api/questions/{q1.id}")

    assert resp.status_code == 200
    urls = [p["url"] for p in resp.json()["question_pages"]]
    assert all(url.startswith("https://") for url in urls)


def test_get_question_not_found_returns_404(public_client):
    resp = public_client.get("/api/questions/99999")
    assert resp.status_code == 404


def test_get_question_includes_topic_chips(public_client, db_session, reference_data, admin_user):
    from unittest.mock import patch

    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper)
    db_session.add(QuestionTopic(question_id=q.id, topic_id=reference_data["topic"].id))
    db_session.flush()
    db_session.add(QuestionSubtopic(
        question_id=q.id,
        subtopic_id=reference_data["subtopic"].id,
        topic_id=reference_data["topic"].id,
    ))
    db_session.flush()

    with patch("app.routes.questions.get_presigned_url", return_value="https://fake.url"):
        resp = public_client.get(f"/api/questions/{q.id}")

    assert resp.status_code == 200
    topics = resp.json()["topics"]
    assert len(topics) >= 1
    assert topics[0]["topic_name"] == "Algebra"
    assert "Linear Equations" in topics[0]["subtopic_names"]
