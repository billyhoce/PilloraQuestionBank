"""Tests for the import pipeline: image processing, confirm service, and routes."""
import io
from datetime import datetime
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.ai.topic_labeler import TruncatedResponseError
from app.models.orm import Paper, Question, QuestionPage, QuestionPart, QuestionTopic
from app.pdf.image_processing import standardize, to_webp_bytes
from app.services.ingest import confirm_import, pdf_to_images


# ---------------------------------------------------------------------------
# Image standardization (pure functions tested separately in test_image_processing)
# Re-tested here in import-pipeline context for integration confidence
# ---------------------------------------------------------------------------


def test_standardize_image_downscales_wide_to_1760():
    img = Image.new("RGB", (2480, 500), color=(100, 150, 200))
    result = standardize(img)
    assert result.width == 1760


def test_standardize_image_keeps_narrow_unchanged():
    img = Image.new("RGB", (1000, 500), color=(0, 100, 0))
    result = standardize(img)
    assert result.size == (1000, 500)


def test_standardize_image_content_only_no_left_margin():
    img = Image.new("RGB", (2480, 300), color=(0, 100, 0))
    result = standardize(img)
    # No white margin baked in — top-left is content.
    assert result.getpixel((0, 0))[:3] == (0, 100, 0)


def test_standardize_image_returns_webp_bytes():
    img = Image.new("RGB", (2480, 400))
    data = to_webp_bytes(img, quality=85)
    reopened = Image.open(io.BytesIO(data))
    assert reopened.format == "WEBP"


def _make_fitz_doc(num_pages=1, width=200, height=300):
    samples = bytes([255] * (width * height * 3))
    mock_pix = MagicMock()
    mock_pix.width = width
    mock_pix.height = height
    mock_pix.samples = samples

    mock_page = MagicMock()
    mock_page.get_pixmap.return_value = mock_pix

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page] * num_pages))
    # pdf_to_images uses `with fitz.open(...) as doc`; real Documents return
    # themselves from __enter__.
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=False)
    return mock_doc


def test_pdf_to_images_calls_fitz_open(minimal_pdf_bytes):
    mock_doc = _make_fitz_doc(num_pages=1)

    with patch("app.services.ingest.fitz.open", return_value=mock_doc) as mock_open:
        result = pdf_to_images(minimal_pdf_bytes)
        mock_open.assert_called_once()
    assert len(result) == 1
    assert isinstance(result[0], Image.Image)


# ---------------------------------------------------------------------------
# Confirm import service
# ---------------------------------------------------------------------------


def _make_confirm_payload(reference_data, admin_user, questions):
    """Build a ConfirmImportPayload dict for the confirm_import service."""
    rd = reference_data
    return {
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "level_id": rd["level"].id,
        "school_id": rd["school"].id,
        "exam_type_id": rd["exam_type"].id,
        "year": 2024,
        "paper_number": "1",
        "questions": questions,
    }


def test_confirm_creates_paper_row(db_session, mock_s3, reference_data, admin_user):
    payload = _make_confirm_payload(
        reference_data,
        admin_user,
        questions=[
            {
                "question_number": 1,
                "pages": [
                    {
                        "temp_key": "tmp/upload-abc/page_0.webp",
                        "page_type": "question",
                        "page_order": 0,
                        "width_px": 2480,
                        "height_px": 800,
                    }
                ],
            }
        ],
    )
    # Pre-populate S3 temp key
    mock_s3.put_object(Bucket="test-bucket", Key="tmp/upload-abc/page_0.webp", Body=b"fake")

    confirm_import(payload=payload, created_by=admin_user, db=db_session)

    assert db_session.query(Paper).count() == 1


def _single_question_payload(reference_data, admin_user, mock_s3, temp_key):
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"fake")
    return _make_confirm_payload(
        reference_data,
        admin_user,
        questions=[
            {
                "question_number": 1,
                "pages": [
                    {"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800}
                ],
            }
        ],
    )


def test_confirm_defaults_paper_to_premium(db_session, mock_s3, reference_data, admin_user):
    payload = _single_question_payload(reference_data, admin_user, mock_s3, "tmp/prem/page_0.webp")
    # _make_confirm_payload omits is_premium — the import default (True) must apply.
    paper = confirm_import(payload=payload, created_by=admin_user, db=db_session)
    assert paper.is_premium is True


def test_confirm_respects_is_premium_false(db_session, mock_s3, reference_data, admin_user):
    payload = _single_question_payload(reference_data, admin_user, mock_s3, "tmp/free/page_0.webp")
    payload["is_premium"] = False
    paper = confirm_import(payload=payload, created_by=admin_user, db=db_session)
    assert paper.is_premium is False


def test_confirm_route_defaults_to_premium(admin_client, mock_s3, reference_data, admin_user):
    rd = reference_data
    temp_key = "tmp/route-prem/page_0.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"fake")
    payload = {
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "level_id": rd["level"].id,
        "school_id": rd["school"].id,
        "exam_type_id": rd["exam_type"].id,
        "year": 2024,
        "paper_number": "3",
        "questions": [
            {"question_number": 1, "pages": [{"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800}]},
        ],
    }
    resp = admin_client.post("/api/import/confirm", json=payload)
    assert resp.status_code == 201
    paper = db_session_from_client_paper(admin_client, resp.json()["paper_id"])
    assert paper["is_premium"] is True


def test_confirm_route_rejects_level_stream_school_level_mismatch(
    admin_client, mock_s3, reference_data
):
    rd = reference_data
    temp_key = "tmp/route-mismatch/page_0.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"fake")
    payload = {
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,          # Secondary
        "level_id": rd["other_level"].id,      # Primary
        "school_id": rd["school"].id,
        "exam_type_id": rd["exam_type"].id,
        "year": 2024,
        "paper_number": "4",
        "questions": [
            {"question_number": 1, "pages": [{"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800}]},
        ],
    }
    resp = admin_client.post("/api/import/confirm", json=payload)
    assert resp.status_code == 422
    assert "school level" in resp.json()["detail"]


def db_session_from_client_paper(client, paper_id):
    """Fetch a paper's detail via the API (the editor endpoint exposes is_premium)."""
    r = client.get(f"/api/papers/{paper_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_confirm_creates_correct_question_count(db_session, mock_s3, reference_data, admin_user):
    questions = [
        {
            "question_number": i,
            "pages": [
                {
                    "temp_key": f"tmp/upload-abc/page_{i}.webp",
                    "page_type": "question",
                    "page_order": 0,
                    "width_px": 2480,
                    "height_px": 600,
                }
            ],
        }
        for i in range(1, 4)
    ]
    for q in questions:
        mock_s3.put_object(Bucket="test-bucket", Key=q["pages"][0]["temp_key"], Body=b"fake")

    payload = _make_confirm_payload(reference_data, admin_user, questions)
    confirm_import(payload=payload, created_by=admin_user, db=db_session)

    assert db_session.query(Question).count() == 3


def test_confirm_creates_question_pages(db_session, mock_s3, reference_data, admin_user):
    questions = [
        {
            "question_number": 1,
            "pages": [
                {"temp_key": "tmp/x/question_0.webp", "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800},
                {"temp_key": "tmp/x/answer_0.webp", "page_type": "answer", "page_order": 0, "width_px": 2480, "height_px": 400},
            ],
        }
    ]
    for q in questions:
        for p in q["pages"]:
            mock_s3.put_object(Bucket="test-bucket", Key=p["temp_key"], Body=b"fake")

    payload = _make_confirm_payload(reference_data, admin_user, questions)
    confirm_import(payload=payload, created_by=admin_user, db=db_session)

    q = db_session.query(Question).one()
    assert db_session.query(QuestionPage).filter_by(question_id=q.id).count() == 2


def test_confirm_moves_images_to_canonical_s3_key(db_session, mock_s3, reference_data, admin_user):
    temp_key = "tmp/upload-def/page_0.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"image-data")

    payload = _make_confirm_payload(
        reference_data,
        admin_user,
        questions=[
            {
                "question_number": 1,
                "pages": [{"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800}],
            }
        ],
    )
    confirm_import(payload=payload, created_by=admin_user, db=db_session)

    paper = db_session.query(Paper).one()
    expected_key = f"papers/{paper.id}/q1/question_0.webp"
    # Canonical key must exist
    mock_s3.head_object(Bucket="test-bucket", Key=expected_key)
    # Temp source is deleted once the DB commit makes the canonical copy durable.
    with pytest.raises(mock_s3.exceptions.ClientError):
        mock_s3.head_object(Bucket="test-bucket", Key=temp_key)


def test_confirm_stores_width_and_height_on_question_page(db_session, mock_s3, reference_data, admin_user):
    temp_key = "tmp/upload-ghi/page_0.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"fake")

    payload = _make_confirm_payload(
        reference_data,
        admin_user,
        questions=[
            {
                "question_number": 1,
                "pages": [{"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 720}],
            }
        ],
    )
    confirm_import(payload=payload, created_by=admin_user, db=db_session)

    page = db_session.query(QuestionPage).one()
    assert page.width_px == 2480
    assert page.height_px == 720


def test_confirm_rollback_on_s3_failure(db_session, mock_s3, reference_data, admin_user):
    temp_key = "tmp/upload-zzz/page_0.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"fake")

    payload = _make_confirm_payload(
        reference_data,
        admin_user,
        questions=[
            {
                "question_number": 1,
                "pages": [{"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800}],
            }
        ],
    )

    with patch("app.services.ingest.copy_only", side_effect=Exception("S3 error")):
        with pytest.raises(Exception):
            confirm_import(payload=payload, created_by=admin_user, db=db_session)

    assert db_session.query(Paper).count() == 0
    # The temp source must survive a failed import so it can be retried.
    mock_s3.head_object(Bucket="test-bucket", Key=temp_key)


def test_confirm_cleans_up_canonical_copies_on_partial_failure(db_session, mock_s3, reference_data, admin_user):
    from app.storage.s3_client import copy_only as real_copy_only

    temp0 = "tmp/upload-multi/page_0.webp"
    temp1 = "tmp/upload-multi/page_1.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp0, Body=b"fake0")
    mock_s3.put_object(Bucket="test-bucket", Key=temp1, Body=b"fake1")

    payload = _make_confirm_payload(
        reference_data,
        admin_user,
        questions=[
            {
                "question_number": 1,
                "pages": [
                    {"temp_key": temp0, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800},
                    {"temp_key": temp1, "page_type": "answer", "page_order": 0, "width_px": 2480, "height_px": 400},
                ],
            }
        ],
    )

    calls = {"n": 0}

    def flaky_copy(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            real_copy_only(src, dst)  # first copy really lands in S3
        else:
            raise Exception("S3 error")  # second fails mid-way

    with patch("app.services.ingest.copy_only", side_effect=flaky_copy):
        with pytest.raises(Exception):
            confirm_import(payload=payload, created_by=admin_user, db=db_session)

    assert db_session.query(Paper).count() == 0
    # Both temp sources survive, so the import stays retryable.
    mock_s3.head_object(Bucket="test-bucket", Key=temp0)
    mock_s3.head_object(Bucket="test-bucket", Key=temp1)
    # The canonical copy written before the failure must be cleaned up (no orphan).
    listing = mock_s3.list_objects_v2(Bucket="test-bucket").get("Contents", [])
    assert [o["Key"] for o in listing if o["Key"].startswith("papers/")] == []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_upload_pdf_admin_only(public_client, minimal_pdf_bytes):
    resp = public_client.post(
        "/api/import/upload-pdf",
        files={"file": ("test.pdf", minimal_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 403


def test_upload_pdf_returns_page_image_data(admin_client, mock_s3, minimal_pdf_bytes):
    with (
        patch("app.services.ingest.fitz.open", return_value=_make_fitz_doc(num_pages=2)),
        patch("app.services.ingest.put_image"),
    ):
        resp = admin_client.post(
            "/api/import/upload-pdf",
            files={"file": ("test.pdf", minimal_pdf_bytes, "application/pdf")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "pages" in body
    assert len(body["pages"]) == 2
    assert "temp_key" in body["pages"][0]
    assert "dimensions" in body["pages"][0]


def test_upload_pdf_includes_ai_filename_suggestion(admin_client, mock_s3, minimal_pdf_bytes, db_session):
    with (
        patch("app.services.ingest.fitz.open", return_value=_make_fitz_doc(num_pages=1)),
        patch("app.services.ingest.put_image"),
        patch(
            "app.services.ingest.extract_metadata",
            return_value={"school_id": 1, "year": 2024, "subject_id": 1, "level_id": None, "exam_type_id": None, "paper_number": "1"},
        ),
    ):
        resp = admin_client.post(
            "/api/import/upload-pdf",
            files={"file": ("RI_2024_Math_Sec3_EOY_P1.pdf", minimal_pdf_bytes, "application/pdf")},
        )

    assert resp.status_code == 200
    assert "suggested_metadata" in resp.json()


def test_upload_pdf_non_pdf_returns_422(admin_client):
    resp = admin_client.post(
        "/api/import/upload-pdf",
        files={"file": ("test.txt", b"not a pdf", "text/plain")},
    )
    assert resp.status_code == 422


def test_confirm_route_creates_paper_returns_paper_id_and_questions(admin_client, mock_s3, reference_data, admin_user):
    rd = reference_data
    temp_key = "tmp/route-test/page_0.webp"
    mock_s3.put_object(Bucket="test-bucket", Key=temp_key, Body=b"fake")

    payload = {
        "subject_id": rd["subject"].id,
        "stream_id": rd["stream"].id,
        "level_id": rd["level"].id,
        "school_id": rd["school"].id,
        "exam_type_id": rd["exam_type"].id,
        "year": 2024,
        "paper_number": "2",
        "questions": [
            {
                "question_number": 1,
                "pages": [{"temp_key": temp_key, "page_type": "question", "page_order": 0, "width_px": 2480, "height_px": 800}],
            }
        ],
    }
    resp = admin_client.post("/api/import/confirm", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert "paper_id" in body
    assert "questions" in body
    assert len(body["questions"]) == 1
    q = body["questions"][0]
    assert q["question_number"] == 1
    assert "id" in q
    assert len(q["pages"]) == 1
    assert "url" in q["pages"][0]


def test_ai_topics_admin_only(public_client, sample_paper):
    q = sample_paper.questions[0]
    resp = public_client.post("/api/import/ai-topics", json={"question_id": q.id})
    assert resp.status_code == 403


def test_ai_topics_returns_suggested_parts(
    admin_client, sample_paper, db_session, reference_data,
    fake_image_bytes, stub_labeller,
):
    q = sample_paper.questions[0]
    rd = reference_data
    selections = [{"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}]
    parts = [
        {"label": "(a)", "marks": 2, "selections": selections},
        {"label": "(b)", "marks": 3, "selections": []},
    ]
    stub_labeller.result = {"parts": parts}

    with patch("app.routes.ingest.downscale_for_ai", side_effect=lambda b: b):
        resp = admin_client.post("/api/import/ai-topics", json={"question_id": q.id})

    assert resp.status_code == 200
    assert resp.json()["parts"] == parts
    assert len(stub_labeller.calls) == 1


def test_ai_topics_missing_question_returns_404(admin_client, mock_s3):
    resp = admin_client.post("/api/import/ai-topics", json={"question_id": 99999})
    assert resp.status_code == 404


def test_ai_topics_does_not_persist(
    admin_client, sample_paper, db_session, reference_data,
    fake_image_bytes, stub_labeller,
):
    q = sample_paper.questions[0]
    rd = reference_data
    stub_labeller.result = {"parts": [{
        "label": "(a)",
        "marks": None,
        "selections": [{"topic_id": rd["topic"].id, "subtopic_id": rd["subtopic"].id}],
    }]}

    with patch("app.routes.ingest.downscale_for_ai", side_effect=lambda b: b):
        admin_client.post("/api/import/ai-topics", json={"question_id": q.id})

    assert db_session.query(QuestionTopic).count() == 0


def test_ai_topics_includes_topics_without_subtopics(
    admin_client, sample_paper, db_session, reference_data,
    fake_image_bytes, stub_labeller,
):
    """Topics without subtopics appear as bare selectable options in the flat list."""
    from app.models.orm import Topic
    rd = reference_data
    bare = Topic(subject_id=rd["subject"].id, stream_id=rd["stream"].id, name="Bare Topic", topic_number=999)
    db_session.add(bare)
    db_session.flush()

    q = sample_paper.questions[0]
    stub_labeller.result = {"parts": [{"label": "", "marks": None, "selections": []}]}

    with patch("app.routes.ingest.downscale_for_ai", side_effect=lambda b: b):
        admin_client.post("/api/import/ai-topics", json={"question_id": q.id})

    _question, topics, _images = stub_labeller.calls[0]
    sent_ids = {t["id"] for t in topics}
    assert bare.id in sent_ids
    assert rd["topic"].id in sent_ids


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return anthropic.RateLimitError("rate limited", response=response, body=None)


def _api_connection_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=request)


def test_ai_topics_rate_limit_returns_429(
    admin_client, sample_paper, db_session, reference_data,
    fake_image_bytes, stub_labeller,
):
    q = sample_paper.questions[0]
    stub_labeller.error = _rate_limit_error()
    with (
        patch("app.routes.ingest.downscale_for_ai", side_effect=lambda b: b),
        patch("app.routes.ingest.log") as mock_log,
    ):
        resp = admin_client.post("/api/import/ai-topics", json={"question_id": q.id})

    assert resp.status_code == 429
    assert mock_log.error.called


def test_ai_topics_truncated_response_returns_502(
    admin_client, sample_paper, db_session, reference_data,
    fake_image_bytes, stub_labeller,
):
    """A cut-off tool call is surfaced for retry, never passed off as a blank part."""
    q = sample_paper.questions[0]
    stub_labeller.error = TruncatedResponseError("hit max_tokens")
    with (
        patch("app.routes.ingest.downscale_for_ai", side_effect=lambda b: b),
        patch("app.routes.ingest.log") as mock_log,
    ):
        resp = admin_client.post("/api/import/ai-topics", json={"question_id": q.id})

    assert resp.status_code == 502
    assert "cut off" in resp.json()["detail"]
    assert mock_log.error.called


def test_ai_topics_api_error_returns_503(
    admin_client, sample_paper, db_session, reference_data,
    fake_image_bytes, stub_labeller,
):
    q = sample_paper.questions[0]
    stub_labeller.error = _api_connection_error()
    with (
        patch("app.routes.ingest.downscale_for_ai", side_effect=lambda b: b),
        patch("app.routes.ingest.log") as mock_log,
    ):
        resp = admin_client.post("/api/import/ai-topics", json={"question_id": q.id})

    assert resp.status_code == 503
    assert mock_log.error.called


# ---------------------------------------------------------------------------
# /save-topics route
# ---------------------------------------------------------------------------


def _one_part(rd, label="", marks=None, with_subtopic=True):
    return {
        "label": label,
        "marks": marks,
        "topic_assignments": [{
            "topic_id": rd["topic"].id,
            "subtopics": [{"subtopic_id": rd["subtopic"].id}] if with_subtopic else [],
        }],
    }


def _parts_of(db_session, question_id):
    return (
        db_session.query(QuestionPart)
        .filter(QuestionPart.question_id == question_id)
        .order_by(QuestionPart.part_order)
        .all()
    )


def test_save_topics_admin_only(public_client, sample_paper):
    resp = public_client.post(
        "/api/import/save-topics",
        json={"paper_id": sample_paper.id, "questions": []},
    )
    assert resp.status_code == 403


def test_save_topics_persists_question_topics(admin_client, sample_paper, db_session, reference_data):
    rd = reference_data
    payload = {
        "paper_id": sample_paper.id,
        "questions": [
            {"question_id": q.id, "parts": [_one_part(rd)]}
            for q in sample_paper.questions
        ],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 201
    assert db_session.query(QuestionTopic).count() == 3


def test_save_topics_persists_per_part_labels_and_marks(admin_client, sample_paper, db_session, reference_data):
    rd = reference_data
    q = sample_paper.questions[0]
    payload = {
        "paper_id": sample_paper.id,
        "questions": [{
            "question_id": q.id,
            "parts": [
                _one_part(rd, label="(a)(i)", marks=2),
                _one_part(rd, label="(a)(ii)", marks=3, with_subtopic=False),
                _one_part(rd, label="(b)", marks=5, with_subtopic=False),
            ],
        }],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 201

    db_session.expire_all()
    parts = _parts_of(db_session, q.id)
    assert [(p.part_order, p.label, p.marks) for p in parts] == [
        (0, "(a)(i)", 2), (1, "(a)(ii)", 3), (2, "(b)", 5),
    ]
    # The question's marks total is derived from the parts, never stored.
    assert db_session.get(Question, q.id).total_marks == 10


def test_save_topics_with_no_parts_leaves_one_blank_part(admin_client, sample_paper, db_session, reference_data):
    q = sample_paper.questions[0]
    resp = admin_client.post("/api/import/save-topics", json={
        "paper_id": sample_paper.id,
        "questions": [{"question_id": q.id, "parts": []}],
    })
    assert resp.status_code == 201

    db_session.expire_all()
    parts = _parts_of(db_session, q.id)
    assert len(parts) == 1
    assert (parts[0].label, parts[0].marks) == ("", None)


def test_save_topics_rejects_a_label_wider_than_the_column(admin_client, sample_paper, db_session, reference_data):
    """An over-long label is a 422, not a silently truncated row."""
    rd = reference_data
    q = sample_paper.questions[0]
    resp = admin_client.post("/api/import/save-topics", json={
        "paper_id": sample_paper.id,
        "questions": [{"question_id": q.id, "parts": [_one_part(rd, label="x" * 33)]}],
    })
    assert resp.status_code == 422

    db_session.expire_all()
    assert db_session.query(QuestionTopic).count() == 0


def test_save_topics_rejects_question_not_in_paper(admin_client, sample_paper, db_session, reference_data):
    rd = reference_data
    payload = {
        "paper_id": sample_paper.id,
        "questions": [{"question_id": 99999, "parts": [_one_part(rd, with_subtopic=False)]}],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 422
    assert db_session.query(QuestionTopic).count() == 0


def test_save_topics_rejects_invalid_subtopic_id(admin_client, sample_paper, db_session, reference_data):
    rd = reference_data
    payload = {
        "paper_id": sample_paper.id,
        "questions": [{
            "question_id": sample_paper.questions[0].id,
            "parts": [{
                "label": "",
                "marks": None,
                "topic_assignments": [
                    {"topic_id": rd["topic"].id, "subtopics": [{"subtopic_id": 99999}]}
                ],
            }],
        }],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 422
    assert db_session.query(QuestionTopic).count() == 0


def test_save_topics_rejects_before_writing_any_question(admin_client, sample_paper, db_session, reference_data):
    """A bad second question must not leave the first one rewritten."""
    rd = reference_data
    q_ok, q_bad = sample_paper.questions[0], sample_paper.questions[1]
    payload = {
        "paper_id": sample_paper.id,
        "questions": [
            {"question_id": q_ok.id, "parts": [_one_part(rd, label="(a)", marks=9)]},
            {"question_id": q_bad.id, "parts": [{
                "label": "",
                "marks": None,
                "topic_assignments": [{"topic_id": 99999, "subtopics": []}],
            }]},
        ],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 422

    db_session.expire_all()
    # The fixture's original two parts for Q1 survive untouched.
    assert [(p.label, p.marks) for p in _parts_of(db_session, q_ok.id)] == [("(a)", 2), ("(b)", 3)]


def test_save_topics_replaces_existing_parts(admin_client, sample_paper, db_session, reference_data):
    rd = reference_data
    q = sample_paper.questions[0]
    assert len(_parts_of(db_session, q.id)) == 2  # fixture gives Q1 two parts

    payload = {
        "paper_id": sample_paper.id,
        "questions": [{"question_id": q.id, "parts": [_one_part(rd, label="(a)", marks=4)]}],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 201

    db_session.expire_all()
    parts = _parts_of(db_session, q.id)
    assert len(parts) == 1
    rows = db_session.query(QuestionTopic).filter(QuestionTopic.part_id == parts[0].id).all()
    assert len(rows) == 1
    assert rows[0].topic_id == rd["topic"].id


def test_save_topics_allows_the_same_subtopic_on_two_parts(admin_client, sample_paper, db_session, reference_data):
    """Two parts of one question can legitimately test the same subtopic."""
    from app.models.orm import QuestionSubtopic
    rd = reference_data
    q = sample_paper.questions[0]
    payload = {
        "paper_id": sample_paper.id,
        "questions": [{
            "question_id": q.id,
            "parts": [_one_part(rd, label="(a)", marks=2), _one_part(rd, label="(b)", marks=3)],
        }],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 201

    db_session.expire_all()
    part_ids = [p.id for p in _parts_of(db_session, q.id)]
    assert len(part_ids) == 2
    for pid in part_ids:
        rows = db_session.query(QuestionSubtopic).filter(QuestionSubtopic.part_id == pid).all()
        assert [r.subtopic_id for r in rows] == [rd["subtopic"].id]


def test_save_topics_allows_multiple_subtopics_under_same_topic(admin_client, sample_paper, db_session, reference_data):
    """A single part can have multiple subtopics belonging to the same parent topic."""
    from app.models.orm import QuestionSubtopic, Subtopic
    rd = reference_data
    sub2 = Subtopic(topic_id=rd["topic"].id, name="Quadratic Equations")
    db_session.add(sub2)
    db_session.flush()
    sub2_id = sub2.id

    q = sample_paper.questions[0]
    payload = {
        "paper_id": sample_paper.id,
        "questions": [{
            "question_id": q.id,
            "parts": [{
                "label": "",
                "marks": None,
                "topic_assignments": [{
                    "topic_id": rd["topic"].id,
                    "subtopics": [
                        {"subtopic_id": rd["subtopic"].id},
                        {"subtopic_id": sub2_id},
                    ],
                }],
            }],
        }],
    }
    resp = admin_client.post("/api/import/save-topics", json=payload)
    assert resp.status_code == 201

    db_session.expire_all()
    part = _parts_of(db_session, q.id)[0]
    assert db_session.query(QuestionTopic).filter(QuestionTopic.part_id == part.id).count() == 1
    qs_rows = db_session.query(QuestionSubtopic).filter(QuestionSubtopic.part_id == part.id).all()
    assert {r.subtopic_id for r in qs_rows} == {rd["subtopic"].id, sub2_id}


# ---------------------------------------------------------------------------
# DELETE /papers/{id}
# ---------------------------------------------------------------------------


def test_delete_paper_admin_only(public_client, sample_paper):
    resp = public_client.delete(f"/api/import/papers/{sample_paper.id}")
    assert resp.status_code == 403


def test_delete_paper_removes_rows_and_s3(admin_client, sample_paper, db_session):
    paper_id = sample_paper.id
    page_keys = [p.image_key for q in sample_paper.questions for p in q.pages]

    with patch("app.routes.ingest.delete_object") as mock_del:
        resp = admin_client.delete(f"/api/import/papers/{paper_id}")

    assert resp.status_code == 204
    assert db_session.query(Paper).filter(Paper.id == paper_id).count() == 0
    assert db_session.query(Question).filter(Question.paper_id == paper_id).count() == 0
    called_keys = {call.args[0] for call in mock_del.call_args_list}
    for k in page_keys:
        assert k in called_keys


def test_delete_paper_missing_returns_204(admin_client):
    resp = admin_client.delete("/api/import/papers/99999")
    assert resp.status_code == 204
