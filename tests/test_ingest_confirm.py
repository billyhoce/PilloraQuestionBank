"""POST /api/import/jobs/{id}/confirm and /skip, and the payload they build from the proposal."""

import io
import uuid

import fitz
import pytest
from PIL import Image

from app.models.orm import IngestJob, Paper, QuestionPage
from app.services.ingest_confirm import build_confirm_payload, paper_key
from tests.test_ingest_review import make_job, page

W, H = 595.0, 842.0


def source_pdf(pages=3) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        p = doc.new_page(width=W, height=H)
        p.draw_rect(fitz.Rect(50, 50, 500, 300), fill=(0.2, 0.2, 0.2))
    return doc.tobytes()


def r(pg, x0=50.0, y0=50.0, x1=500.0, y1=300.0):
    return {"page": pg, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def q(number, qr, ar=()):
    return {"number": number, "question_rects": list(qr), "answer_rects": list(ar), "flags": []}


def paper(label="q1", answer_label="a1", questions=None, orphans=()):
    return {
        "label": label, "answer_label": answer_label, "answer_template": "table",
        "pages": [page(1, W, H), page(2, W, H), page(3, W, H)],
        "questions": questions if questions is not None else [
            q(1, [r(1), r(2)], [r(3, 10, 10, 200, 60)]),
            q(2, [r(2, 50, 400, 300, 600)]),
        ],
        "orphan_answers": list(orphans), "warnings": [],
    }


def proposal(*papers):
    return {"papers": list(papers) or [paper()], "unrouted": [], "warnings": []}


def size(webp: bytes):
    return Image.open(io.BytesIO(webp)).size


# --- payload building --------------------------------------------------------------------

def test_payload_pages_order_types_and_sizes():
    puts = {}
    payload, keys = build_confirm_payload(
        source_pdf(), paper(), {"year": 2024}, put=lambda k, b: puts.__setitem__(k, b), upload_id="u1"
    )
    assert payload["year"] == 2024
    q1, q2 = payload["questions"]
    assert [(p["page_type"], p["page_order"]) for p in q1["pages"]] == [
        ("question", 1), ("question", 2), ("answer", 1),
    ]
    assert q1["question_number"] == 1 and q2["question_number"] == 2
    assert keys == [f"tmp/u1/page_{n}.webp" for n in range(4)]
    assert [p["temp_key"] for p in q1["pages"] + q2["pages"]] == keys
    for p in q1["pages"] + q2["pages"]:
        assert p["width_px"] <= 1760
        assert size(puts[p["temp_key"]]) == (p["width_px"], p["height_px"])
    # 450 pt wide at 300 dpi is 1875 px, so it is scaled to 1760; the 190 pt answer is kept at 300 dpi.
    assert q1["pages"][0]["width_px"] == 1760
    assert abs(q1["pages"][2]["width_px"] - 190 * 300 / 72) <= 2


def test_payload_deletes_uploaded_images_when_a_crop_fails(monkeypatch):
    deleted = []
    monkeypatch.setattr("app.services.ingest_confirm.delete_object", deleted.append)
    bad = paper(questions=[q(1, [r(1), r(9)])])
    with pytest.raises(Exception):
        build_confirm_payload(source_pdf(), bad, {}, put=lambda k, b: None, upload_id="u2")
    assert deleted == ["tmp/u2/page_0.webp"]


def test_paper_key_falls_back_to_answer_label_then_position():
    assert paper_key({"label": "q1", "answer_label": "a1"}, 0) == "q1"
    assert paper_key({"label": None, "answer_label": "a2"}, 1) == "a2"
    assert paper_key({"label": None, "answer_label": None}, 2) == "paper3"


# --- the endpoints -------------------------------------------------------------------------

@pytest.fixture
def env(db_session, admin_user, fake_object_store, mock_s3, reference_data):
    def setup(prop=None, edited=None, **kw):
        job = make_job(db_session, admin_user, proposal=prop or proposal(), edited=edited, pages=3, **kw)
        fake_object_store.objects[job.source_key] = source_pdf()
        return job

    rd = reference_data
    meta = {
        "subject_id": rd["subject"].id, "stream_id": rd["stream"].id, "level_id": rd["level"].id,
        "school_id": rd["school"].id, "exam_type_id": rd["exam_type"].id,
        "year": 2024, "paper_number": "1", "is_premium": False,
    }
    return setup, meta


def test_confirm_creates_paper_with_cropped_pages(admin_client, db_session, env, fake_object_store, mock_s3):
    setup, meta = env
    job = setup()
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["job_status"] == "confirmed"
    assert [x["question_number"] for x in body["questions"]] == [1, 2]
    assert [(p["page_type"], p["page_order"]) for p in body["questions"][0]["pages"]] == [
        ("answer", 1), ("question", 1), ("question", 2),
    ]
    paper_row = db_session.get(Paper, body["paper_id"])
    assert paper_row.source_job_id == job.id and paper_row.is_premium is False
    db_session.refresh(job)
    assert job.status == "confirmed" and job.confirmed_paper_ids == [paper_row.id]
    assert job.report["review_outcome"] == {"q1": "confirmed"}
    stored = db_session.query(QuestionPage).filter_by(page_type="answer").one()
    assert stored.width_px <= 1760
    # Stored objects are real crops; the temp uploads and the job's prefix are gone.
    keys = [o["Key"] for o in mock_s3.list_objects_v2(Bucket="test-bucket").get("Contents", [])]
    assert sorted(keys) == sorted(
        f"papers/{paper_row.id}/q{n}/{t}_{o}.webp" for n, t, o in
        [(1, "question", 1), (1, "question", 2), (1, "answer", 1), (2, "question", 1)]
    )
    assert fake_object_store.deleted_prefixes == [f"tmp/ingest/{job.id}/"]


def test_edited_rectangles_are_what_gets_cropped(admin_client, db_session, env, mock_s3):
    setup, meta = env
    narrow = paper(questions=[q(1, [r(1, 50, 50, 250, 200)])])  # 200 x 150 pt
    job = setup(prop=proposal(paper(questions=[q(1, [r(1)])])), edited=proposal(narrow))
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    page_row = db_session.query(QuestionPage).one()
    assert abs(page_row.width_px - 200 * 300 / 72) <= 2 and abs(page_row.height_px - 150 * 300 / 72) <= 2


def test_two_paper_booklet_is_confirmed_only_after_both_are_decided(admin_client, db_session, env, mock_s3):
    setup, meta = env
    job = setup(prop=proposal(paper("q1", "a1"), paper("q2", "a2")))
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert resp.status_code == 201 and resp.json()["job_status"] == "review_ready"
    db_session.refresh(job)
    assert job.status == "review_ready"
    # Deciding a paper twice is a conflict, confirm or skip.
    again = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert again.status_code == 409
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q1"}).status_code == 409
    skipped = admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q2"})
    assert skipped.status_code == 200 and skipped.json() == {"job_status": "confirmed"}
    db_session.refresh(job)
    assert job.status == "confirmed" and len(job.confirmed_paper_ids) == 1
    assert job.report["review_outcome"] == {"q1": "confirmed", "q2": "skipped"}
    assert db_session.query(Paper).count() == 1


def test_answer_only_paper_is_identified_by_its_answer_label(admin_client, db_session, env, mock_s3):
    setup, meta = env
    job = setup(prop=proposal(paper(None, "a1")))
    review = admin_client.get(f"/api/import/jobs/{job.id}/review").json()
    assert review["proposal"]["papers"][0]["key"] == "a1"
    assert admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "a1"}).status_code == 201


def test_paper_without_questions_can_only_be_skipped(admin_client, db_session, env, mock_s3):
    setup, meta = env
    job = setup(prop=proposal(paper(questions=[], orphans=[r(3)])))
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert resp.status_code == 422 and "skip" in resp.json()["detail"]
    assert db_session.query(Paper).count() == 0
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q1"}).json()["job_status"] == "confirmed"
    db_session.refresh(job)
    assert job.confirmed_paper_ids is None


def test_confirm_rejections(admin_client, db_session, env, mock_s3, reference_data):
    setup, meta = env
    job = setup()
    url = f"/api/import/jobs/{job.id}/confirm"
    assert admin_client.post(url, json={**meta, "paper_label": "nope"}).status_code == 404
    assert admin_client.post(f"/api/import/jobs/{uuid.uuid4()}/confirm", json={**meta, "paper_label": "q1"}).status_code == 404
    wrong_stream = {**meta, "stream_id": reference_data["other_stream"].id}  # another school level
    assert admin_client.post(url, json={**wrong_stream, "paper_label": "q1"}).status_code == 422
    job.status = "cancelled"
    db_session.commit()
    assert admin_client.post(url, json={**meta, "paper_label": "q1"}).status_code == 409
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q1"}).status_code == 409


def test_non_admin_forbidden(public_client, fake_object_store):
    jid = uuid.uuid4()
    assert public_client.post(f"/api/import/jobs/{jid}/confirm", json={"paper_label": "q1"}).status_code == 403
    assert public_client.post(f"/api/import/jobs/{jid}/skip", json={"paper_label": "q1"}).status_code == 403
