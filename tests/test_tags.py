"""Tests for tag CRUD endpoints (app/routes/reference.py).

Tags are global, flat labels (id + unique name). Unlike other reference data,
deleting a tag is not blocked when it's in use — the delete cascades and strips
the tag from every question that carried it.
"""


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_tags_empty(client):
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_list_tags_returns_seeded_data(client, reference_data):
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()["data"]]
    assert "Challenging" in names


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_tag_admin_only(admin_client):
    resp = admin_client.post("/api/tags", json={"name": "Graphing"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Graphing"
    assert "id" in body


def test_create_tag_public_returns_403(public_client):
    resp = public_client.post("/api/tags", json={"name": "Graphing"})
    assert resp.status_code == 403


def test_create_tag_duplicate_returns_409(admin_client):
    admin_client.post("/api/tags", json={"name": "Hard"})
    resp = admin_client.post("/api/tags", json={"name": "Hard"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_tag_by_id(admin_client):
    create_resp = admin_client.post("/api/tags", json={"name": "Exam-Favourite"})
    tag_id = create_resp.json()["id"]
    resp = admin_client.get(f"/api/tags/{tag_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Exam-Favourite"


def test_get_tag_not_found(client):
    resp = client.get("/api/tags/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_tag(admin_client):
    create_resp = admin_client.post("/api/tags", json={"name": "Old Tag"})
    tag_id = create_resp.json()["id"]
    resp = admin_client.put(f"/api/tags/{tag_id}", json={"name": "New Tag"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Tag"


def test_update_tag_duplicate_returns_409(admin_client):
    admin_client.post("/api/tags", json={"name": "Alpha"})
    beta_id = admin_client.post("/api/tags", json={"name": "Beta"}).json()["id"]
    resp = admin_client.put(f"/api/tags/{beta_id}", json={"name": "Alpha"})
    assert resp.status_code == 409


def test_update_tag_requires_admin(public_client, reference_data):
    tag_id = reference_data["tag"].id
    resp = public_client.put(f"/api/tags/{tag_id}", json={"name": "Nope"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_tag(admin_client):
    create_resp = admin_client.post("/api/tags", json={"name": "To Delete"})
    tag_id = create_resp.json()["id"]
    del_resp = admin_client.delete(f"/api/tags/{tag_id}")
    assert del_resp.status_code == 204
    assert admin_client.get(f"/api/tags/{tag_id}").status_code == 404


def test_delete_tag_missing_returns_404(admin_client):
    assert admin_client.delete("/api/tags/99999").status_code == 404


def test_delete_tag_requires_admin(public_client, reference_data):
    tag_id = reference_data["tag"].id
    assert public_client.delete(f"/api/tags/{tag_id}").status_code == 403


def test_delete_tag_in_use_cascades(admin_client, reference_data, sample_paper, db_session):
    """Deleting a tag that's applied to a question succeeds (204) and strips the
    association — the question itself is kept. This deliberately differs from
    other reference data, which is protected by a 409 FK guard."""
    from app.models.orm import Question, QuestionTag

    tag_id = reference_data["tag"].id
    question = db_session.query(Question).filter_by(paper_id=sample_paper.id).first()
    db_session.add(QuestionTag(question_id=question.id, tag_id=tag_id))
    db_session.flush()
    assert db_session.query(QuestionTag).filter_by(tag_id=tag_id).count() == 1

    resp = admin_client.delete(f"/api/tags/{tag_id}")
    assert resp.status_code == 204

    db_session.expire_all()
    assert db_session.query(QuestionTag).filter_by(tag_id=tag_id).count() == 0
    assert db_session.query(Question).filter_by(id=question.id).first() is not None


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_list_tags_returns_200(client):
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert "data" in resp.json()
