"""GET /api/import/jobs/{id}/review and POST .../manual-pages over a fake object store."""

import uuid
from unittest.mock import patch

import fitz
import pytest

from app.models.orm import IngestJob
from app.services.ingest_review import REVIEW_ZOOM


def page(n, w=595.3, h=841.9):
    return {
        "page": n, "image": f"pages/p{n:02d}.webp", "width_pt": w, "height_pt": h,
        "needs_review": False, "review_reason": None,
    }


def rect(n, y0=100.0, y1=160.0):
    return {"page": n, "x0": 72.0, "y0": y0, "x1": 523.0, "y1": y1}


PROPOSAL = {
    "papers": [
        {
            "label": "q1", "answer_label": "a1", "answer_template": "table",
            "pages": [page(2), page(3, 420.0, 595.0)],
            "questions": [{"number": 1, "question_rects": [rect(2)], "answer_rects": [], "flags": ["pixel_ink"]}],
            "orphan_answers": [], "warnings": [],
        }
    ],
    "unrouted": [
        {"label": "q2", "status": "not_routed", "first_page": 2, "last_page": 3,
         "reason": "no page carries extractable text (a scanned paper needs OCR)"}
    ],
    "warnings": [],
}


def make_job(db, admin, proposal=PROPOSAL, edited=None, status="review_ready", pages=4, filename="x.pdf"):
    job = IngestJob(
        id=uuid.uuid4(), created_by=admin.id, filename=filename, source_key="k",
        sha256="0" * 64, page_count=pages, status=status, proposal=proposal, proposal_edited=edited,
    )
    job.source_key = f"tmp/ingest/{job.id}/source.pdf"
    db.add(job)
    db.commit()
    return job


def test_non_admin_forbidden(public_client, fake_object_store):
    jid = uuid.uuid4()
    assert public_client.get(f"/api/import/jobs/{jid}/review").status_code == 403
    assert public_client.post(
        f"/api/import/jobs/{jid}/manual-pages", json={"first_page": 1, "last_page": 1}
    ).status_code == 403


def test_review_has_presigned_urls_and_pixel_sizes(admin_client, db_session, admin_user, fake_object_store):
    job = make_job(db_session, admin_user)
    body = admin_client.get(f"/api/import/jobs/{job.id}/review").json()
    assert body["edited"] is False
    p1, p2 = body["proposal"]["papers"][0]["pages"]
    assert p1["url"] == f"https://fake.url/tmp/ingest/{job.id}/pages/p02.webp"
    assert (p1["width_px"], p1["height_px"]) == (round(595.3 * REVIEW_ZOOM), round(841.9 * REVIEW_ZOOM))
    assert (p2["width_px"], p2["height_px"]) == (round(420.0 * REVIEW_ZOOM), round(595.0 * REVIEW_ZOOM))
    assert body["proposal"]["unrouted"][0]["label"] == "q2"
    assert body["proposal"]["papers"][0]["questions"][0]["flags"] == ["pixel_ink"]


def test_review_prefers_edited_proposal(admin_client, db_session, admin_user, fake_object_store):
    edited = {**PROPOSAL, "papers": [{**PROPOSAL["papers"][0], "label": "edited"}]}
    job = make_job(db_session, admin_user, edited=edited)
    body = admin_client.get(f"/api/import/jobs/{job.id}/review").json()
    assert body["edited"] is True
    assert body["proposal"]["papers"][0]["label"] == "edited"


def test_review_page_without_image_has_no_url(admin_client, db_session, admin_user, fake_object_store):
    bad = {**PROPOSAL, "papers": [{**PROPOSAL["papers"][0], "pages": [{**page(2), "image": None}]}]}
    job = make_job(db_session, admin_user, proposal=bad)
    [p] = admin_client.get(f"/api/import/jobs/{job.id}/review").json()["proposal"]["papers"][0]["pages"]
    assert p["url"] is None


def test_review_without_proposal_is_409_and_unknown_job_404(admin_client, db_session, admin_user, fake_object_store):
    job = make_job(db_session, admin_user, proposal=None, status="running")
    assert admin_client.get(f"/api/import/jobs/{job.id}/review").status_code == 409
    assert admin_client.get(f"/api/import/jobs/{uuid.uuid4()}/review").status_code == 404


def test_manual_pages_extracts_range_from_source(admin_client, db_session, admin_user, fake_object_store):
    doc = fitz.open()
    for _ in range(4):
        doc.new_page()
    job = make_job(db_session, admin_user)
    fake_object_store.objects[job.source_key] = doc.tobytes()
    seen = {}

    def spy_upload(pdf, filename, db, suggested_metadata=None):
        with fitz.open(stream=pdf, filetype="pdf") as d:
            seen["pages"] = d.page_count
        seen["filename"] = filename
        return {"pages": [], "suggested_metadata": {}}

    with patch("app.routes.ingest.upload_pages", side_effect=spy_upload):
        resp = admin_client.post(f"/api/import/jobs/{job.id}/manual-pages", json={"first_page": 2, "last_page": 3})
    assert resp.status_code == 200
    assert seen == {"pages": 2, "filename": "x.pdf"}


@pytest.mark.parametrize("first,last", [(0, 2), (3, 2), (1, 9)])
def test_manual_pages_rejects_bad_range(admin_client, db_session, admin_user, fake_object_store, first, last):
    doc = fitz.open()
    for _ in range(4):
        doc.new_page()
    job = make_job(db_session, admin_user)
    fake_object_store.objects[job.source_key] = doc.tobytes()
    resp = admin_client.post(f"/api/import/jobs/{job.id}/manual-pages", json={"first_page": first, "last_page": last})
    assert resp.status_code == 422
