""""This is an answer booklet" / "This is a question booklet" (switching a pending paper's role),
learned school aliases, and the job list's ``partner`` / ``suggestion`` per paper."""

from app.models.orm import IngestJob, IngestPaper, SchoolAlias
from app.services.answer_coverage import current_papers
from tests.test_ingest_match import ANSWERS, QUESTION, job_with, row
from tests.test_ingest_review import rect

# A solutions booklet the pipeline read as a question paper: the question paper reprinted with the
# worked answers, so its "question" boxes hold the answers.
SOLUTIONS = {
    **QUESTION,
    "questions": [
        {"number": 1, "question_rects": [rect(3, 300, 400)], "answer_rects": [rect(3, 100, 160)], "flags": []},
        {"number": 2, "question_rects": [rect(2)], "answer_rects": [], "flags": []},
    ],
}
QUESTIONS_2 = {
    **QUESTION,
    "questions": [
        {"number": 1, "question_rects": [rect(2)], "answer_rects": [], "flags": []},
        {"number": 2, "question_rects": [rect(3)], "answer_rects": [], "flags": []},
    ],
}


def _meta(rd, **over):
    return {
        "school_id": rd["school"].id, "year": 2020, "level_id": rd["level"].id, "subject_id": rd["subject"].id,
        "exam_type_id": rd["exam_type"].id, "stream_id": rd["stream"].id, "paper_number": "1", **over,
    }


def _switch(client, job, key, role):
    return client.post(f"/api/import/jobs/{job.id}/papers/{key}/role", json={"role": role})


def test_a_solutions_booklet_becomes_answers_and_pairs_with_its_questions(
    admin_client, db_session, admin_user, reference_data, fake_object_store
):
    meta = _meta(reference_data)
    qjob, _ = job_with(db_session, admin_user, QUESTIONS_2, meta, filename="BPGHS 2020 EM P1 Qns Paper.pdf")
    sjob, _ = job_with(db_session, admin_user, SOLUTIONS, meta, filename="BPGHS 2020 EM P1 Soln.pdf")
    resp = _switch(admin_client, sjob, "q1", "answer_only")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "answer_only"
    assert body["matches"]["job_id"] == str(qjob.id) and body["matches"]["matched_by"] == "auto"
    db_session.expire_all()
    paper = current_papers(db_session.get(IngestJob, sjob.id))["q1"]  # same key: the label stays
    assert paper["role"] == "answer_only"
    q1 = paper["questions"][0]
    assert q1["question_rects"] == [] and [r["y0"] for r in q1["answer_rects"]] == [100, 300]  # source order
    assert row(db_session, sjob, "q1").role == "answer_only"
    review = admin_client.get(f"/api/import/jobs/{sjob.id}/review").json()
    assert review["proposal"]["papers"][0]["role"] == "answer_only"


def test_switching_back_makes_answer_boxes_question_boxes(admin_client, db_session, admin_user):
    ajob, akey = job_with(db_session, admin_user, ANSWERS, {}, filename="a.pdf")
    resp = _switch(admin_client, ajob, akey, "question")
    assert resp.status_code == 200 and resp.json()["role"] == "question"
    db_session.expire_all()
    paper = current_papers(db_session.get(IngestJob, ajob.id))[akey]
    assert paper["questions"][0]["question_rects"] == ANSWERS["questions"][0]["answer_rects"]
    assert paper["questions"][0]["answer_rects"] == []


def test_switching_edits_the_admins_edit_too(admin_client, db_session, admin_user):
    from app.services.ingest_review import save_edited_proposal

    job, key = job_with(db_session, admin_user, SOLUTIONS, {}, filename="s.pdf")
    save_edited_proposal(job, {"papers": [{"questions": QUESTIONS_2["questions"], "orphan_answers": []}]})
    db_session.commit()
    assert _switch(admin_client, job, key, "answer_only").status_code == 200
    db_session.expire_all()
    job = db_session.get(IngestJob, job.id)
    assert job.proposal["papers"][0]["role"] == job.proposal_edited["papers"][0]["role"] == "answer_only"
    assert job.proposal_edited["papers"][0]["questions"][0]["answer_rects"] == [rect(2)]
    # a later edit keeps the new role (it is read from the proposal)
    save_edited_proposal(job, {"papers": [{"questions": [
        {"number": 1, "question_rects": [], "answer_rects": [rect(2)], "flags": []},
    ], "orphan_answers": []}]})


def test_switching_releases_a_link_without_rejecting_it(admin_client, db_session, admin_user):
    qjob, qkey = job_with(db_session, admin_user, QUESTION, filename="q.pdf")
    ajob, akey = job_with(db_session, admin_user, ANSWERS, filename="a.pdf")
    admin_client.post(f"/api/import/jobs/{ajob.id}/papers/{akey}/match", json={"ingest_paper_id": row(db_session, qjob, qkey).id})
    assert _switch(admin_client, ajob, akey, "question").status_code == 200
    assert row(db_session, qjob, qkey).matched_ingest_paper_id is None
    from app.models.orm import IngestMatchRejection
    assert db_session.query(IngestMatchRejection).count() == 0


def test_switching_is_refused_on_a_decided_paper_or_a_job_not_under_review(admin_client, db_session, admin_user):
    job, key = job_with(db_session, admin_user, QUESTION, filename="q.pdf")
    assert _switch(admin_client, job, key, "both").status_code == 422
    r = row(db_session, job, key)
    r.status = "skipped"
    db_session.commit()
    assert _switch(admin_client, job, key, "answer_only").status_code == 409
    done, dkey = job_with(db_session, admin_user, QUESTION, filename="d.pdf", status="confirmed")
    assert _switch(admin_client, done, dkey, "answer_only").status_code == 409


def test_job_list_names_each_papers_partner_and_suggestion(admin_client, db_session, admin_user, reference_data):
    meta = _meta(reference_data)
    qjob, qkey = job_with(db_session, admin_user, QUESTION, meta, filename="q.pdf")
    ajob, akey = job_with(db_session, admin_user, ANSWERS, meta, filename="a.pdf")
    from app.services.ingest_matching import match_job
    match_job(db_session, ajob)
    db_session.commit()
    data = {j["id"]: j for j in admin_client.get("/api/import/jobs?status=review_ready").json()["data"]}
    apaper = data[str(ajob.id)]["papers"][0]
    qpaper = data[str(qjob.id)]["papers"][0]
    assert apaper["partner"] == {
        "ingest_paper_id": row(db_session, qjob, qkey).id, "job_id": str(qjob.id), "filename": "q.pdf", "paper_key": "q1",
    }
    assert qpaper["partner"]["job_id"] == str(ajob.id) and qpaper["id"] == row(db_session, qjob, qkey).id
    assert apaper["suggestion"] is None


def test_confirming_a_paper_learns_its_cover_school_as_an_alias(db_session, admin_user, reference_data):
    from app.ai.filename_extractor import resolve_metadata
    from app.services.ingest_papers import learn_school_alias

    school = reference_data["school"]
    job, key = job_with(db_session, admin_user, QUESTION, {"extracted": {"school": " BPGHS "}}, filename="q.pdf")
    other, okey = job_with(db_session, admin_user, ANSWERS, {"extracted": {"school": "bpghs"}}, filename="a.pdf")
    assert row(db_session, job, key).cover_school_name == "BPGHS"
    learn_school_alias(db_session, job, key, school.id)
    db_session.commit()
    assert [(a.alias, a.school_id) for a in db_session.query(SchoolAlias)] == [("bpghs", school.id)]
    assert row(db_session, other, okey).school_id == school.id  # the other pending paper gets it too
    ref = {"schools": [school], "school_aliases": {"bpghs": school.id}, "subjects": [], "levels": [], "exam_types": []}
    assert resolve_metadata({"school": "BPGHS"}, ref)["school_id"] == school.id
    learn_school_alias(db_session, job, key, school.id)  # once only
    assert db_session.query(SchoolAlias).count() == 1


def test_a_resolved_cover_school_is_not_kept(db_session, admin_user, reference_data):
    job, key = job_with(
        db_session, admin_user, QUESTION, {"school_id": reference_data["school"].id, "extracted": {"school": "X"}},
    )
    assert db_session.query(IngestPaper).filter_by(job_id=job.id).one().cover_school_name is None
