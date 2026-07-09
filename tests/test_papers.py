"""Tests for the admin "Manage Papers" endpoints (app/routes/papers.py)."""

import io

from PIL import Image

from app.models.orm import Paper, Question, QuestionTag, QuestionTopic, Stream


def _webp(width=2480, height=400):
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=85)
    return buf.getvalue()


def _upload_image(admin_client):
    resp = admin_client.post(
        "/api/papers/upload-image",
        files={"file": ("page.webp", _webp(), "image/webp")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get_detail(admin_client, paper_id):
    resp = admin_client.get(f"/api/papers/{paper_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Listing & access control
# --------------------------------------------------------------------------- #

def test_list_papers_admin(admin_client, sample_paper, mock_s3):
    resp = admin_client.get("/api/papers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == sample_paper.id
    assert item["question_count"] == 3
    assert item["subject_name"] == "Math"


def test_list_papers_requires_admin(public_client, sample_paper):
    assert public_client.get("/api/papers").status_code == 403


def test_papers_years_still_works(admin_client, sample_paper):
    # Route-ordering guard: /api/papers/years must not be shadowed by
    # /api/papers/{paper_id}.
    resp = admin_client.get("/api/papers/years")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Paper detail & metadata
# --------------------------------------------------------------------------- #

def test_get_paper_detail(admin_client, sample_paper, mock_s3):
    detail = _get_detail(admin_client, sample_paper.id)
    assert detail["subject_id"] == sample_paper.subject_id
    assert len(detail["questions"]) == 3
    q2 = next(q for q in detail["questions"] if q["question_number"] == 2)
    types = sorted(p["page_type"] for p in q2["pages"])
    assert types == ["answer", "question"]
    assert all(p["url"] for p in q2["pages"])


def test_update_paper_metadata(admin_client, sample_paper, mock_s3):
    payload = {
        "subject_id": sample_paper.subject_id,
        "stream_id": sample_paper.stream_id,
        "level_id": sample_paper.level_id,
        "school_id": sample_paper.school_id,
        "exam_type_id": sample_paper.exam_type_id,
        "year": 2025,
        "paper_number": "2",
    }
    resp = admin_client.put(f"/api/papers/{sample_paper.id}", json=payload)
    assert resp.status_code == 200, resp.text

    detail = _get_detail(admin_client, sample_paper.id)
    assert detail["year"] == 2025
    assert detail["paper_number"] == "2"


def test_update_paper_stream_change_clears_topics(
    admin_client, db_session, sample_paper, reference_data, mock_s3
):
    # Assign a topic to question 1, then change the paper's stream.
    q1 = next(q for q in sample_paper.questions if q.question_number == 1)
    db_session.add(QuestionTopic(question_id=q1.id, topic_id=reference_data["topic"].id))
    db_session.flush()

    # A different stream (valid FK) to switch to.
    stream2 = Stream(name="G2", school_level_id=reference_data["school_level"].id)
    db_session.add(stream2)
    db_session.flush()

    payload = {
        "subject_id": sample_paper.subject_id,
        "stream_id": stream2.id,
        "level_id": sample_paper.level_id,
        "school_id": sample_paper.school_id,
        "exam_type_id": sample_paper.exam_type_id,
        "year": sample_paper.year,
        "paper_number": sample_paper.paper_number,
    }
    resp = admin_client.put(f"/api/papers/{sample_paper.id}", json=payload)
    assert resp.status_code == 200, resp.text

    remaining = db_session.query(QuestionTopic).filter(QuestionTopic.question_id == q1.id).count()
    assert remaining == 0


# --------------------------------------------------------------------------- #
# Image upload
# --------------------------------------------------------------------------- #

def test_upload_image(admin_client, mock_s3):
    body = _upload_image(admin_client)
    assert body["temp_key"].startswith("tmp/")
    # A 2480px-wide upload is downscaled to the 1760px content width.
    assert body["dimensions"]["width"] == 1760
    assert body["url"]


def test_upload_image_rejects_non_image(admin_client, mock_s3):
    resp = admin_client.post(
        "/api/papers/upload-image",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Questions: add / update / delete
# --------------------------------------------------------------------------- #

def test_add_question(admin_client, sample_paper, reference_data, mock_s3):
    up = _upload_image(admin_client)
    payload = {
        "question_number": 4,
        "marks": 7,
        "topic_assignments": [
            {
                "topic_id": reference_data["topic"].id,
                "subtopics": [{"subtopic_id": reference_data["subtopic"].id}],
            }
        ],
        "pages": [{
            "temp_key": up["temp_key"],
            "page_type": "question",
            "page_order": 1,
            "width_px": up["dimensions"]["width"],
            "height_px": up["dimensions"]["height"],
        }],
    }
    resp = admin_client.post(f"/api/papers/{sample_paper.id}/questions", json=payload)
    assert resp.status_code == 201, resp.text
    q = resp.json()
    assert q["question_number"] == 4
    assert q["marks"] == 7
    assert len(q["pages"]) == 1
    assert len(q["selections"]) == 1
    assert q["selections"][0]["topic_id"] == reference_data["topic"].id
    assert q["selections"][0]["subtopic_id"] == reference_data["subtopic"].id

    detail = _get_detail(admin_client, sample_paper.id)
    assert len(detail["questions"]) == 4


def test_update_question_marks_and_topics(
    admin_client, sample_paper, reference_data, mock_s3
):
    detail = _get_detail(admin_client, sample_paper.id)
    q1 = next(q for q in detail["questions"] if q["question_number"] == 1)
    existing_page = q1["pages"][0]

    payload = {
        "question_number": 1,
        "marks": 9,
        "topic_assignments": [
            {
                "topic_id": reference_data["topic"].id,
                "subtopics": [{"subtopic_id": reference_data["subtopic"].id}],
            }
        ],
        "pages": [{
            "id": existing_page["id"],
            "page_type": existing_page["page_type"],
            "page_order": 1,
        }],
    }
    resp = admin_client.put(f"/api/questions/{q1['id']}", json=payload)
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["marks"] == 9
    assert len(updated["selections"]) == 1
    assert updated["selections"][0]["topic_id"] == reference_data["topic"].id
    assert updated["selections"][0]["subtopic_id"] == reference_data["subtopic"].id
    assert len(updated["pages"]) == 1


def test_update_question_reorder_add_delete(admin_client, sample_paper, mock_s3):
    """Q2 starts with 1 question page + 1 answer page. We add a new question
    page before the existing one (reorder) and delete the answer page."""
    detail = _get_detail(admin_client, sample_paper.id)
    q2 = next(q for q in detail["questions"] if q["question_number"] == 2)
    existing_q_page = next(p for p in q2["pages"] if p["page_type"] == "question")

    up = _upload_image(admin_client)
    payload = {
        "question_number": 2,
        "marks": 3,
        "topic_assignments": [],
        "pages": [
            {  # new page first
                "temp_key": up["temp_key"],
                "page_type": "question",
                "page_order": 1,
                "width_px": up["dimensions"]["width"],
                "height_px": up["dimensions"]["height"],
            },
            {  # existing page second
                "id": existing_q_page["id"],
                "page_type": "question",
                "page_order": 2,
            },
            # answer page omitted -> deleted
        ],
    }
    resp = admin_client.put(f"/api/questions/{q2['id']}", json=payload)
    assert resp.status_code == 200, resp.text
    updated = resp.json()

    q_pages = [p for p in updated["pages"] if p["page_type"] == "question"]
    a_pages = [p for p in updated["pages"] if p["page_type"] == "answer"]
    assert len(q_pages) == 2
    assert len(a_pages) == 0
    # Orders are sequential and the previously-existing page is now second.
    by_order = sorted(q_pages, key=lambda p: p["page_order"])
    assert [p["page_order"] for p in by_order] == [1, 2]
    assert by_order[1]["id"] == existing_q_page["id"]


def test_update_question_duplicate_number_rejected(admin_client, sample_paper, mock_s3):
    detail = _get_detail(admin_client, sample_paper.id)
    q1 = next(q for q in detail["questions"] if q["question_number"] == 1)
    existing_page = q1["pages"][0]

    # Renumber Q1 -> 2, which already exists.
    payload = {
        "question_number": 2,
        "marks": q1["marks"],
        "topic_assignments": [],
        "pages": [{
            "id": existing_page["id"],
            "page_type": existing_page["page_type"],
            "page_order": 1,
        }],
    }
    resp = admin_client.put(f"/api/questions/{q1['id']}", json=payload)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_update_question_same_number_allowed(admin_client, sample_paper, mock_s3):
    # Saving a question without changing its number must not trip the
    # uniqueness check against itself.
    detail = _get_detail(admin_client, sample_paper.id)
    q1 = next(q for q in detail["questions"] if q["question_number"] == 1)
    existing_page = q1["pages"][0]
    payload = {
        "question_number": 1,
        "marks": 8,
        "topic_assignments": [],
        "pages": [{
            "id": existing_page["id"],
            "page_type": existing_page["page_type"],
            "page_order": 1,
        }],
    }
    resp = admin_client.put(f"/api/questions/{q1['id']}", json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["marks"] == 8


def test_add_question_duplicate_number_rejected(admin_client, sample_paper, mock_s3):
    payload = {
        "question_number": 1,  # already exists
        "marks": 1,
        "topic_assignments": [],
        "pages": [],
    }
    resp = admin_client.post(f"/api/papers/{sample_paper.id}/questions", json=payload)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_delete_question(admin_client, sample_paper, mock_s3, db_session):
    q3 = next(q for q in sample_paper.questions if q.question_number == 3)

    resp = admin_client.delete(f"/api/questions/{q3.id}")
    assert resp.status_code == 204

    assert db_session.query(Question).filter(Question.paper_id == sample_paper.id).count() == 2
    assert db_session.get(Question, q3.id) is None


def test_delete_question_missing_returns_404(admin_client, mock_s3):
    assert admin_client.delete("/api/questions/99999").status_code == 404


def test_delete_paper(admin_client, sample_paper, mock_s3, db_session):
    paper_id = sample_paper.id
    resp = admin_client.delete(f"/api/papers/{paper_id}")
    assert resp.status_code == 204
    assert db_session.get(Paper, paper_id) is None


def test_question_endpoints_require_admin(public_client, sample_paper):
    assert public_client.delete(f"/api/papers/{sample_paper.id}").status_code == 403
    assert public_client.get("/api/papers").status_code == 403


# --------------------------------------------------------------------------- #
# Tagging questions
# --------------------------------------------------------------------------- #

def test_add_question_with_tags(admin_client, sample_paper, reference_data, mock_s3):
    up = _upload_image(admin_client)
    payload = {
        "question_number": 4,
        "marks": 7,
        "topic_assignments": [],
        "tag_ids": [reference_data["tag"].id],
        "pages": [{
            "temp_key": up["temp_key"],
            "page_type": "question",
            "page_order": 1,
            "width_px": up["dimensions"]["width"],
            "height_px": up["dimensions"]["height"],
        }],
    }
    resp = admin_client.post(f"/api/papers/{sample_paper.id}/questions", json=payload)
    assert resp.status_code == 201, resp.text
    q = resp.json()
    assert [t["name"] for t in q["tags"]] == ["Challenging"]


def test_update_question_replaces_tags(admin_client, sample_paper, reference_data, mock_s3, db_session):
    from app.models.orm import Tag

    tag2 = Tag(name="Graphing")
    db_session.add(tag2)
    db_session.flush()

    detail = _get_detail(admin_client, sample_paper.id)
    q1 = next(q for q in detail["questions"] if q["question_number"] == 1)
    existing_page = q1["pages"][0]

    def _payload(tag_ids):
        return {
            "question_number": 1,
            "marks": 5,
            "topic_assignments": [],
            "tag_ids": tag_ids,
            "pages": [{
                "id": existing_page["id"],
                "page_type": existing_page["page_type"],
                "page_order": 1,
            }],
        }

    resp = admin_client.put(f"/api/questions/{q1['id']}", json=_payload([reference_data["tag"].id]))
    assert resp.status_code == 200, resp.text
    assert {t["name"] for t in resp.json()["tags"]} == {"Challenging"}

    # Replace with a different tag — the old one is dropped.
    resp = admin_client.put(f"/api/questions/{q1['id']}", json=_payload([tag2.id]))
    assert resp.status_code == 200, resp.text
    assert {t["name"] for t in resp.json()["tags"]} == {"Graphing"}


def test_add_question_invalid_tag_id_returns_422(admin_client, sample_paper, mock_s3):
    payload = {
        "question_number": 4,
        "marks": 1,
        "topic_assignments": [],
        "tag_ids": [99999],
        "pages": [],
    }
    resp = admin_client.post(f"/api/papers/{sample_paper.id}/questions", json=payload)
    assert resp.status_code == 422


def test_set_question_tags_endpoint(admin_client, sample_paper, reference_data, mock_s3, db_session):
    q1 = next(q for q in sample_paper.questions if q.question_number == 1)
    resp = admin_client.put(
        f"/api/questions/{q1.id}/tags", json={"tag_ids": [reference_data["tag"].id]}
    )
    assert resp.status_code == 200, resp.text
    assert {t["name"] for t in resp.json()["tags"]} == {"Challenging"}
    db_session.expire_all()
    assert db_session.query(QuestionTag).filter_by(question_id=q1.id).count() == 1

    # Clearing tags.
    resp = admin_client.put(f"/api/questions/{q1.id}/tags", json={"tag_ids": []})
    assert resp.status_code == 200, resp.text
    assert resp.json()["tags"] == []


def test_set_question_tags_requires_admin(public_client, sample_paper, reference_data):
    q1 = next(q for q in sample_paper.questions if q.question_number == 1)
    resp = public_client.put(
        f"/api/questions/{q1.id}/tags", json={"tag_ids": [reference_data["tag"].id]}
    )
    assert resp.status_code == 403


def test_set_question_tags_invalid_tag_returns_422(admin_client, sample_paper):
    q1 = next(q for q in sample_paper.questions if q.question_number == 1)
    resp = admin_client.put(f"/api/questions/{q1.id}/tags", json={"tag_ids": [99999]})
    assert resp.status_code == 422


def test_set_question_tags_missing_question_returns_404(admin_client, reference_data):
    resp = admin_client.put(
        "/api/questions/99999/tags", json={"tag_ids": [reference_data["tag"].id]}
    )
    assert resp.status_code == 404
