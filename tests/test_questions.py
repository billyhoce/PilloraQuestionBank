"""Tests for the questions list/filter and detail endpoints."""
from datetime import datetime, UTC

import pytest

from app.models.orm import (
    Paper,
    Question,
    QuestionPage,
    QuestionPart,
    QuestionSubtopic,
    QuestionTag,
    QuestionTopic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_paper(db_session, rd, admin_user, year=2024, school=None, paper_number="1") -> Paper:
    paper = Paper(
        subject_id=rd["subject"].id,
        stream_id=rd["stream"].id,
        level_id=rd["level"].id,
        school_id=(school or rd["school"]).id,
        exam_type_id=rd["exam_type"].id,
        year=year,
        paper_number=paper_number,
        created_by=admin_user.id,
        created_at=datetime.now(UTC),
    )
    db_session.add(paper)
    db_session.flush()
    return paper


def _add_question(db_session, paper, number=1, marks=5) -> Question:
    q = Question(
        paper_id=paper.id,
        question_number=number,
        created_at=datetime.now(UTC),
    )
    db_session.add(q)
    db_session.flush()
    # Marks and topics live on parts; a question with no printed parts is a
    # single unlabelled one.
    db_session.add(QuestionPart(question_id=q.id, part_order=0, label="", marks=marks))
    db_session.flush()
    _add_page(db_session, q, "question")
    return q


def _label(db_session, question, topic_id, subtopic_id=None, part_order=0):
    """Attach a topic (and optionally a subtopic) to one of a question's parts,
    creating the part if it doesn't exist yet."""
    part = next((p for p in question.parts if p.part_order == part_order), None)
    if part is None:
        # Append rather than db_session.add so the already-loaded collection
        # stays accurate — these tests share one session with the API client,
        # which won't re-read a collection it has already loaded.
        part = QuestionPart(part_order=part_order, label="", marks=None)
        question.parts.append(part)
        db_session.flush()
    db_session.add(QuestionTopic(part_id=part.id, topic_id=topic_id))
    db_session.flush()
    if subtopic_id is not None:
        db_session.add(QuestionSubtopic(
            part_id=part.id, subtopic_id=subtopic_id, topic_id=topic_id
        ))
        db_session.flush()
    return part


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
        created_by=admin_user.id, created_at=datetime.now(UTC),
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

    _label(db_session, q_with_topic, reference_data["topic"].id)

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
    _label(db_session, q_a, rd["topic"].id)
    _label(db_session, q_b, topic_b.id)

    resp = public_client.get(
        f"/api/questions?topic_ids={rd['topic'].id}&topic_ids={topic_b.id}"
    )
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_a.id in ids
    assert q_b.id in ids
    assert q_none.id not in ids


# ---------------------------------------------------------------------------
# Tag filter / search / serialization
# ---------------------------------------------------------------------------


def test_list_questions_filter_by_tag_ids(public_client, db_session, reference_data, admin_user):
    """tag_ids filter matches any question carrying one of the listed tags."""
    paper = _add_paper(db_session, reference_data, admin_user)
    q_with_tag = _add_question(db_session, paper, number=1)
    q_no_tag = _add_question(db_session, paper, number=2)

    db_session.add(QuestionTag(question_id=q_with_tag.id, tag_id=reference_data["tag"].id))
    db_session.flush()

    resp = public_client.get(f"/api/questions?tag_ids={reference_data['tag'].id}")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_with_tag.id in ids
    assert q_no_tag.id not in ids


def test_list_questions_filter_by_tag_ids_union(public_client, db_session, reference_data, admin_user):
    """Multiple tag_ids are OR-combined (inclusive)."""
    from app.models.orm import Tag

    rd = reference_data
    paper = _add_paper(db_session, rd, admin_user)

    tag_b = Tag(name="Graphing")
    db_session.add(tag_b)
    db_session.flush()

    q_a = _add_question(db_session, paper, number=1)
    q_b = _add_question(db_session, paper, number=2)
    q_none = _add_question(db_session, paper, number=3)
    db_session.add_all([
        QuestionTag(question_id=q_a.id, tag_id=rd["tag"].id),
        QuestionTag(question_id=q_b.id, tag_id=tag_b.id),
    ])
    db_session.flush()

    resp = public_client.get(f"/api/questions?tag_ids={rd['tag'].id}&tag_ids={tag_b.id}")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_a.id in ids
    assert q_b.id in ids
    assert q_none.id not in ids


def test_list_questions_search_matches_tag_name(public_client, db_session, reference_data, admin_user):
    paper = _add_paper(db_session, reference_data, admin_user)
    q_tagged = _add_question(db_session, paper, number=1)
    q_plain = _add_question(db_session, paper, number=2)
    db_session.add(QuestionTag(question_id=q_tagged.id, tag_id=reference_data["tag"].id))
    db_session.flush()

    # reference_data tag name is "Challenging"
    resp = public_client.get("/api/questions?search=challeng")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_tagged.id in ids
    assert q_plain.id not in ids


def test_list_questions_includes_tags_in_response(public_client, db_session, reference_data, admin_user):
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper, number=1)
    db_session.add(QuestionTag(question_id=q.id, tag_id=reference_data["tag"].id))
    db_session.flush()

    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    item = next(it for it in resp.json()["items"] if it["id"] == q.id)
    assert [t["name"] for t in item["tags"]] == ["Challenging"]


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
    _label(db_session, q_only_a, rd["topic"].id)
    # Topic A on part 0 and topic B on part 1: `exclusive` is defined over the
    # union of the question's parts, so this question is still excluded.
    _label(db_session, q_a_and_b, rd["topic"].id)
    _label(db_session, q_a_and_b, topic_b.id, part_order=1)

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


def test_search_by_subtopic_name(public_client, db_session, reference_data, admin_user):
    from app.models.orm import Subtopic
    paper = _add_paper(db_session, reference_data, admin_user)
    q_match = _add_question(db_session, paper, number=1)
    q_other = _add_question(db_session, paper, number=2)

    other_sub = Subtopic(topic_id=reference_data["topic"].id, name="Quadratic Equations")
    db_session.add(other_sub)
    db_session.flush()

    _label(db_session, q_match, reference_data["topic"].id, reference_data["subtopic"].id)
    _label(db_session, q_other, reference_data["topic"].id, other_sub.id)

    resp = public_client.get("/api/questions?search=linear")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_match.id in ids
    assert q_other.id not in ids


def test_search_by_topic_name(public_client, db_session, reference_data, admin_user):
    """The search keyword matches assigned topic names (case-insensitive)."""
    paper = _add_paper(db_session, reference_data, admin_user)
    q_algebra = _add_question(db_session, paper, number=1)
    q_no_topic = _add_question(db_session, paper, number=2)

    _label(db_session, q_algebra, reference_data["topic"].id)

    resp = public_client.get("/api/questions?search=algebra")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_algebra.id in ids
    assert q_no_topic.id not in ids


def test_search_by_school_name(public_client, db_session, reference_data, admin_user):
    from app.models.orm import School
    school2 = School(name="Anglo-Chinese School")
    db_session.add(school2)
    db_session.flush()

    paper_ri = _add_paper(db_session, reference_data, admin_user)
    paper_acs = _add_paper(db_session, reference_data, admin_user, school=school2)
    q_ri = _add_question(db_session, paper_ri)
    q_acs = _add_question(db_session, paper_acs)

    resp = public_client.get("/api/questions?search=raffles")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_ri.id in ids
    assert q_acs.id not in ids


def test_search_by_paper_metadata_names(public_client, db_session, reference_data, admin_user):
    """Subject, level, stream and exam type names are all searchable."""
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper)

    for kw in ("math", "sec 3", "g3", "eoy"):
        resp = public_client.get(f"/api/questions?search={kw}")
        assert resp.status_code == 200, kw
        ids = [item["id"] for item in resp.json()["items"]]
        assert q.id in ids, f"search={kw!r} should match via paper metadata"


def test_search_by_year(public_client, db_session, reference_data, admin_user):
    paper_2019 = _add_paper(db_session, reference_data, admin_user, year=2019)
    paper_2024 = _add_paper(db_session, reference_data, admin_user, year=2024)
    q_2019 = _add_question(db_session, paper_2019)
    q_2024 = _add_question(db_session, paper_2024)

    resp = public_client.get("/api/questions?search=2019")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["items"]]
    assert q_2019.id in ids
    assert q_2024.id not in ids


def test_search_by_school_level_tier(public_client, db_session, reference_data, admin_user):
    """The school-level tier name (e.g. 'Secondary') is searchable.

    The fixture level is 'Sec 3' and its school-level tier is 'Secondary'; the
    keyword 'secondary' matches only via the tier, not the level name.
    """
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper)

    resp = public_client.get("/api/questions?search=secondary")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert q.id in ids


def test_search_by_topic_number_token(public_client, db_session, reference_data, admin_user):
    """A 'T{n}' token (e.g. 'T1') matches questions tagged that topic number."""
    paper = _add_paper(db_session, reference_data, admin_user)
    q_topic1 = _add_question(db_session, paper, number=1)
    q_no_topic = _add_question(db_session, paper, number=2)

    # reference_data topic 'Algebra' has topic_number=1
    _label(db_session, q_topic1, reference_data["topic"].id)

    resp = public_client.get("/api/questions?search=T1")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert q_topic1.id in ids
    assert q_no_topic.id not in ids


def test_filter_by_paper_number_exact_case_insensitive(public_client, db_session, reference_data, admin_user):
    """paper_number filters by exact, case-insensitive match; letters supported."""
    paper_1 = _add_paper(db_session, reference_data, admin_user, paper_number="1")
    paper_a = _add_paper(db_session, reference_data, admin_user, paper_number="a")
    q_1 = _add_question(db_session, paper_1, number=1)
    q_a = _add_question(db_session, paper_a, number=2)

    resp = public_client.get("/api/questions?paper_number=1")
    ids = [item["id"] for item in resp.json()["items"]]
    assert q_1.id in ids
    assert q_a.id not in ids

    # Letters, case-insensitive: "A" matches paper "a".
    resp = public_client.get("/api/questions?paper_number=A")
    ids = [item["id"] for item in resp.json()["items"]]
    assert q_a.id in ids
    assert q_1.id not in ids


def test_search_no_match_returns_zero(public_client, db_session, reference_data, admin_user):
    paper = _add_paper(db_session, reference_data, admin_user)
    _add_question(db_session, paper)

    resp = public_client.get("/api/questions?search=zzz-no-such-thing")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


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


def test_get_question_returns_all_pages(public_client, sample_paper, db_session, fake_presign):
    # Q2 in sample_paper has 1 question page + 1 answer page
    from app.models.orm import Question
    q2 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=2).one()

    resp = public_client.get(f"/api/questions/{q2.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["question_pages"]) == 1
    assert len(body["answer_pages"]) == 1


def test_get_question_pages_include_presigned_urls(public_client, sample_paper, db_session, fake_presign):
    from app.models.orm import Question

    q1 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=1).one()

    resp = public_client.get(f"/api/questions/{q1.id}")

    assert resp.status_code == 200
    urls = [p["url"] for p in resp.json()["question_pages"]]
    assert all(url.startswith("https://") for url in urls)


def test_get_question_not_found_returns_404(public_client):
    resp = public_client.get("/api/questions/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Premium paywall
# ---------------------------------------------------------------------------


def _make_premium(db_session, paper):
    paper.is_premium = True
    db_session.flush()


def test_list_premium_paper_locked_for_public(public_client, sample_paper, db_session):
    _make_premium(db_session, sample_paper)
    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items  # tiles are still visible
    for item in items:
        assert item["paper_info"]["is_premium"] is True
        assert item["locked"] is True
        assert item["first_page_url"] is None


def test_list_premium_paper_locked_for_anonymous(client, sample_paper, db_session):
    _make_premium(db_session, sample_paper)
    resp = client.get("/api/questions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert all(i["locked"] and i["first_page_url"] is None for i in items)


def test_list_premium_paper_unlocked_for_premium(premium_client, sample_paper, db_session, fake_presign):
    _make_premium(db_session, sample_paper)
    resp = premium_client.get("/api/questions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(not i["locked"] and i["first_page_url"] == fake_presign for i in items)


def test_list_premium_paper_locked_for_other_school_level(
    other_premium_client, sample_paper, db_session
):
    """Premium for Primary buys nothing on a Secondary paper."""
    _make_premium(db_session, sample_paper)
    resp = other_premium_client.get("/api/questions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items  # tiles are still visible, as they are for a Normal user
    assert all(i["locked"] and i["first_page_url"] is None for i in items)


def test_list_premium_paper_unlocked_for_admin(admin_client, sample_paper, db_session):
    _make_premium(db_session, sample_paper)
    resp = admin_client.get("/api/questions")
    assert resp.status_code == 200
    assert all(not i["locked"] for i in resp.json()["items"])


def test_list_reports_school_level_name(public_client, sample_paper):
    """The UI names a locked paper's premium group from this — level names alone
    can't, since "1" is both Primary 1 and Secondary 1."""
    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    assert all(
        i["paper_info"]["school_level_name"] == "Secondary" for i in resp.json()["items"]
    )


def test_non_premium_paper_not_locked(public_client, sample_paper):
    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    assert all(not i["locked"] for i in resp.json()["items"])


def test_get_question_detail_locked_for_public(public_client, sample_paper, db_session):
    _make_premium(db_session, sample_paper)
    q1 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=1).one()
    resp = public_client.get(f"/api/questions/{q1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["locked"] is True
    assert all(p["url"] is None for p in body["question_pages"])


def test_get_question_detail_unlocked_for_premium(premium_client, sample_paper, db_session, fake_presign):
    _make_premium(db_session, sample_paper)
    q1 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=1).one()
    resp = premium_client.get(f"/api/questions/{q1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["locked"] is False
    assert all(p["url"] == fake_presign for p in body["question_pages"])


def test_get_question_detail_locked_for_other_school_level(
    other_premium_client, sample_paper, db_session
):
    _make_premium(db_session, sample_paper)
    q1 = db_session.query(Question).filter_by(paper_id=sample_paper.id, question_number=1).one()
    resp = other_premium_client.get(f"/api/questions/{q1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["locked"] is True
    assert all(p["url"] is None for p in body["question_pages"])


def test_get_question_includes_topic_chips(public_client, db_session, reference_data, admin_user, fake_presign):

    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper)
    _label(db_session, q, reference_data["topic"].id, reference_data["subtopic"].id)

    resp = public_client.get(f"/api/questions/{q.id}")

    assert resp.status_code == 200
    topics = resp.json()["topics"]
    assert len(topics) >= 1
    assert topics[0]["topic_name"] == "Algebra"
    assert topics[0]["topic_number"] == 1
    assert "Linear Equations" in topics[0]["subtopic_names"]


def test_list_questions_topics_include_topic_number(public_client, db_session, reference_data, admin_user):
    """The list payload carries topic_number so the UI can render 'T1 Algebra'."""
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper)
    _label(db_session, q, reference_data["topic"].id)

    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    item = next(it for it in resp.json()["items"] if it["id"] == q.id)
    assert item["topics"][0]["topic_name"] == "Algebra"
    assert item["topics"][0]["topic_number"] == 1


# ---------------------------------------------------------------------------
# Per-part detail
# ---------------------------------------------------------------------------


def test_get_question_returns_the_per_part_breakdown(public_client, db_session, reference_data, admin_user, fake_presign):
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper, marks=None)
    q.parts[0].label = "(a)"
    q.parts[0].marks = 2
    db_session.flush()
    _label(db_session, q, reference_data["topic"].id, reference_data["subtopic"].id)

    q.parts.append(QuestionPart(part_order=1, label="(b)", marks=5))
    db_session.flush()

    resp = public_client.get(f"/api/questions/{q.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["marks"] == 7  # summed across the parts
    assert [(p["part_order"], p["label"], p["marks"]) for p in body["parts"]] == [
        (0, "(a)", 2), (1, "(b)", 5),
    ]
    assert body["parts"][0]["topics"][0]["topic_name"] == "Algebra"
    assert body["parts"][1]["topics"] == []


def test_list_topics_are_the_union_across_parts(public_client, db_session, reference_data, admin_user):
    """Two parts sharing a topic collapse to one chip with merged subtopics."""
    from app.models.orm import Subtopic

    rd = reference_data
    sub2 = Subtopic(topic_id=rd["topic"].id, name="Quadratic Equations")
    db_session.add(sub2)
    db_session.flush()

    paper = _add_paper(db_session, rd, admin_user)
    q = _add_question(db_session, paper)
    _label(db_session, q, rd["topic"].id, rd["subtopic"].id, part_order=0)
    _label(db_session, q, rd["topic"].id, sub2.id, part_order=1)

    resp = public_client.get("/api/questions")
    assert resp.status_code == 200
    item = next(it for it in resp.json()["items"] if it["id"] == q.id)
    assert len(item["topics"]) == 1
    assert set(item["topics"][0]["subtopic_names"]) == {"Linear Equations", "Quadratic Equations"}


def test_list_marks_are_summed_across_parts(public_client, db_session, reference_data, admin_user):
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper, marks=2)
    q.parts.append(QuestionPart(part_order=1, label="(b)", marks=6))
    db_session.flush()

    resp = public_client.get("/api/questions")
    item = next(it for it in resp.json()["items"] if it["id"] == q.id)
    assert item["marks"] == 8


def test_list_marks_null_when_no_part_is_marked(public_client, db_session, reference_data, admin_user):
    paper = _add_paper(db_session, reference_data, admin_user)
    q = _add_question(db_session, paper, marks=None)

    resp = public_client.get("/api/questions")
    item = next(it for it in resp.json()["items"] if it["id"] == q.id)
    assert item["marks"] is None
