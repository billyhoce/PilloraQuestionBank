"""The ``ingest_paper`` record: written with the proposal, updated by metadata edits, confirm and skip."""

import uuid

import pytest

from app.models.orm import IngestPaper
from app.services.ingest_papers import sync_job_papers
from tests.test_ingest_confirm import env, paper, proposal, q, r  # noqa: F401
from tests.test_ingest_review import make_job


def rows(db, job):
    db.expire_all()
    return {x.paper_key: x for x in db.query(IngestPaper).filter_by(job_id=job.id)}


def test_sync_creates_one_row_per_paper_and_is_idempotent(db_session, admin_user):
    answers = {**paper(None, "a2"), "role": "answer_only"}
    job = make_job(db_session, admin_user, proposal=proposal(paper("q1", "a1"), answers))
    job.report = {"paper_metadata": {"q1": {"year": 2024, "paper_number": "1", "school_id": None}}}
    sync_job_papers(db_session, job)
    sync_job_papers(db_session, job)  # a re-run report
    db_session.commit()
    got = rows(db_session, job)
    assert set(got) == {"q1", "a2"}
    assert (got["q1"].role, got["q1"].year, got["q1"].paper_number, got["q1"].metadata_source) == ("question", 2024, "1", "cover")
    assert (got["a2"].role, got["a2"].year, got["a2"].metadata_source) == ("answer_only", None, None)
    assert got["a2"].status == "pending"


def test_old_job_falls_back_to_the_filename_metadata(db_session, admin_user):
    job = make_job(db_session, admin_user)
    job.report = {"filename_metadata": {"year": 2023}}
    sync_job_papers(db_session, job)
    (row,) = rows(db_session, job).values()
    assert (row.year, row.metadata_source) == (2023, "filename")


def test_rerun_keeps_admin_edited_metadata(db_session, admin_user):
    job = make_job(db_session, admin_user)
    job.report = {"paper_metadata": {"q1": {"year": 2024}}}
    (row,) = sync_job_papers(db_session, job)
    row.year, row.metadata_source = 2020, "admin"
    job.report = {"paper_metadata": {"q1": {"year": 2025}}}
    sync_job_papers(db_session, job)
    assert (row.year, row.metadata_source) == (2020, "admin")


def test_metadata_endpoint_updates_the_row(admin_client, db_session, admin_user, reference_data):
    job = make_job(db_session, admin_user)
    job.report = {"paper_metadata": {"q1": {"year": 2024}}}
    sync_job_papers(db_session, job)
    db_session.commit()
    url = f"/api/import/jobs/{job.id}/papers/q1/metadata"
    # unchanged values keep the cover source
    assert admin_client.put(url, json={"year": 2024}).json()["metadata_source"] == "cover"
    resp = admin_client.put(url, json={"year": 2022, "school_id": reference_data["school"].id, "paper_number": "2"})
    assert resp.status_code == 200 and resp.json()["metadata_source"] == "admin"
    row = rows(db_session, job)["q1"]
    assert (row.year, row.school_id, row.paper_number, row.metadata_source) == (2022, reference_data["school"].id, "2", "admin")
    assert admin_client.put(f"/api/import/jobs/{job.id}/papers/nope/metadata", json={}).status_code == 404


def test_metadata_endpoint_creates_rows_lazily_and_refuses_decided_papers(admin_client, db_session, admin_user):
    job = make_job(db_session, admin_user)  # no rows yet (a job from before the table)
    url = f"/api/import/jobs/{job.id}/papers/q1/metadata"
    assert admin_client.put(url, json={"year": 2021}).status_code == 200
    assert rows(db_session, job)["q1"].year == 2021
    assert admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q1"}).status_code == 200
    assert admin_client.put(url, json={"year": 2022}).status_code == 409


def test_non_admin_forbidden(public_client):
    assert public_client.put(f"/api/import/jobs/{uuid.uuid4()}/papers/q1/metadata", json={}).status_code == 403


def test_confirm_records_the_final_metadata_and_the_paper(admin_client, db_session, env):  # noqa: F811
    setup, meta = env
    job = setup()
    job.report = {"paper_metadata": {"q1": {"year": 2020, "paper_number": "1"}}}
    sync_job_papers(db_session, job)
    db_session.commit()
    resp = admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert resp.status_code == 201, resp.text
    row = rows(db_session, job)["q1"]
    assert (row.status, row.paper_id) == ("confirmed", resp.json()["paper_id"])
    assert (row.year, row.school_id, row.metadata_source) == (2024, meta["school_id"], "admin")


def test_confirming_unchanged_metadata_keeps_its_source(admin_client, db_session, env):  # noqa: F811
    setup, meta = env
    job = setup()
    job.report = {"paper_metadata": {"q1": {k: v for k, v in meta.items() if k != "is_premium"}}}
    sync_job_papers(db_session, job)
    db_session.commit()
    admin_client.post(f"/api/import/jobs/{job.id}/confirm", json={**meta, "paper_label": "q1"})
    assert rows(db_session, job)["q1"].metadata_source == "cover"


def test_skip_marks_the_row_skipped(admin_client, db_session, env):  # noqa: F811
    setup, _ = env
    job = setup(prop=proposal(paper("q1", "a1"), paper("q2", "a2")))
    sync_job_papers(db_session, job)
    db_session.commit()
    admin_client.post(f"/api/import/jobs/{job.id}/skip", json={"paper_label": "q2"})
    got = rows(db_session, job)
    assert (got["q1"].status, got["q2"].status) == ("pending", "skipped")
