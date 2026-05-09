"""Tests for reference data CRUD endpoints."""
import pytest


# ---------------------------------------------------------------------------
# Subjects — full CRUD coverage
# ---------------------------------------------------------------------------


def test_list_subjects_empty(client):
    resp = client.get("/api/subjects")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_list_subjects_returns_seeded_data(client, reference_data):
    resp = client.get("/api/subjects")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["data"]]
    assert "Math" in names


def test_create_subject_admin_only(admin_client):
    resp = admin_client.post("/api/subjects", json={"name": "Physics"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Physics"
    assert "id" in body


def test_create_subject_public_returns_403(public_client):
    resp = public_client.post("/api/subjects", json={"name": "Physics"})
    assert resp.status_code == 403


def test_create_subject_duplicate_returns_409(admin_client):
    admin_client.post("/api/subjects", json={"name": "Chemistry"})
    resp = admin_client.post("/api/subjects", json={"name": "Chemistry"})
    assert resp.status_code == 409


def test_get_subject_by_id(admin_client):
    create_resp = admin_client.post("/api/subjects", json={"name": "Biology"})
    subject_id = create_resp.json()["id"]
    resp = admin_client.get(f"/api/subjects/{subject_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Biology"


def test_get_subject_not_found(client):
    resp = client.get("/api/subjects/99999")
    assert resp.status_code == 404


def test_update_subject(admin_client):
    create_resp = admin_client.post("/api/subjects", json={"name": "Old Name"})
    subject_id = create_resp.json()["id"]
    resp = admin_client.put(f"/api/subjects/{subject_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_delete_subject(admin_client):
    create_resp = admin_client.post("/api/subjects", json={"name": "To Delete"})
    subject_id = create_resp.json()["id"]
    del_resp = admin_client.delete(f"/api/subjects/{subject_id}")
    assert del_resp.status_code == 204
    get_resp = admin_client.get(f"/api/subjects/{subject_id}")
    assert get_resp.status_code == 404


def test_delete_subject_with_dependent_topic_returns_409(admin_client, reference_data):
    subject_id = reference_data["subject"].id
    stream_id = reference_data["stream"].id
    # Create a topic that references this subject
    admin_client.post("/api/topics", json={
        "subject_id": subject_id,
        "stream_id": stream_id,
        "name": "Calculus",
        "topic_number": 99,
    })
    resp = admin_client.delete(f"/api/subjects/{subject_id}")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Topics — extra scoping tests
# ---------------------------------------------------------------------------


def test_list_topics_filtered_by_subject_and_stream(admin_client, reference_data):
    rd = reference_data
    # Add a second stream and subject
    sl_resp = admin_client.post("/api/school-levels", json={"name": "Primary"})
    sl_id = sl_resp.json()["id"]
    stream2_resp = admin_client.post("/api/streams", json={"name": "Foundation", "school_level_id": sl_id})
    stream2_id = stream2_resp.json()["id"]
    subj2_resp = admin_client.post("/api/subjects", json={"name": "Science"})
    subj2_id = subj2_resp.json()["id"]

    # Topic under Math/G3
    admin_client.post("/api/topics", json={
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "name": "Statistics",
        "topic_number": 2,
    })
    # Topic under Science/Foundation
    admin_client.post("/api/topics", json={
        "subject_id": subj2_id,
        "stream_id": stream2_id,
        "name": "Forces",
        "topic_number": 1,
    })

    resp = admin_client.get(f"/api/topics?subject_id={rd['subject'].id}&stream_id={rd['stream'].id}")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()["data"]]
    assert "Algebra" in names  # from reference_data
    assert "Statistics" in names
    assert "Forces" not in names


def test_create_topic_duplicate_name_same_subject_stream_returns_409(admin_client, reference_data):
    rd = reference_data
    admin_client.post("/api/topics", json={
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "name": "Trigonometry",
        "topic_number": 3,
    })
    resp = admin_client.post("/api/topics", json={
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "name": "Trigonometry",
        "topic_number": 4,
    })
    assert resp.status_code == 409


def test_create_topic_same_name_different_stream_succeeds(admin_client, reference_data):
    rd = reference_data
    sl_resp = admin_client.post("/api/school-levels", json={"name": "University"})
    sl_id = sl_resp.json()["id"]
    stream2_resp = admin_client.post("/api/streams", json={"name": "G4", "school_level_id": sl_id})
    stream2_id = stream2_resp.json()["id"]

    admin_client.post("/api/topics", json={
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "name": "Vectors",
        "topic_number": 5,
    })
    resp = admin_client.post("/api/topics", json={
        "subject_id": rd["subject"].id,
        "stream_id": stream2_id,
        "name": "Vectors",
        "topic_number": 1,
    })
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Subtopics
# ---------------------------------------------------------------------------


def test_list_subtopics_filtered_by_topic(admin_client, reference_data):
    rd = reference_data
    topic_id = rd["topic"].id

    # Add a second topic with its own subtopic
    t2_resp = admin_client.post("/api/topics", json={
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "name": "Geometry",
        "topic_number": 10,
    })
    t2_id = t2_resp.json()["id"]
    admin_client.post("/api/subtopics", json={"topic_id": t2_id, "name": "Circles"})

    resp = admin_client.get(f"/api/subtopics?topic_id={topic_id}")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["data"]]
    assert "Linear Equations" in names  # from reference_data
    assert "Circles" not in names


def test_create_subtopic_duplicate_same_topic_returns_409(admin_client, reference_data):
    topic_id = reference_data["topic"].id
    admin_client.post("/api/subtopics", json={"topic_id": topic_id, "name": "Quadratic Equations"})
    resp = admin_client.post("/api/subtopics", json={"topic_id": topic_id, "name": "Quadratic Equations"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Parametrized smoke tests — all list endpoints return 200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("resource", [
    "school-levels",
    "subjects",
    "streams",
    "levels",
    "schools",
    "exam-types",
])
def test_list_resource_returns_200(resource, client):
    resp = client.get(f"/api/{resource}")
    assert resp.status_code == 200
    assert "data" in resp.json()
