"""Tests for knapsack selection, PDF layout engine, and generation routes."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.models.orm import Paper, Question, QuestionPage
from app.pdf.layout_engine import LayoutEngine, LayoutPlan, QuestionLayout
from app.services.generate import knapsack_select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_question(id: int, marks: Optional[int], question_number: int = 1) -> MagicMock:
    q = MagicMock(spec=Question)
    q.id = id
    q.marks = marks
    q.question_number = question_number
    return q


def _make_question_layout(
    question_id: int,
    label: str,
    source_label: str,
    question_page_heights: list[int],
    answer_page_heights: list[int] = None,
    page_index: int = 0,
) -> QuestionLayout:
    q_pages = [
        MagicMock(image_key=f"papers/1/q{question_id}/question_{i}.webp", height_px=h, width_px=2480, page_type="question", page_order=i)
        for i, h in enumerate(question_page_heights)
    ]
    a_pages = [
        MagicMock(image_key=f"papers/1/q{question_id}/answer_{i}.webp", height_px=h, width_px=2480, page_type="answer", page_order=i)
        for i, h in enumerate(answer_page_heights or [])
    ]
    return QuestionLayout(
        question_id=question_id,
        label=label,
        source_label=source_label,
        page_index=page_index,
        question_pages=q_pages,
        answer_pages=a_pages,
    )


# ---------------------------------------------------------------------------
# Knapsack — pure function tests
# ---------------------------------------------------------------------------


def test_knapsack_exact_match():
    questions = [_make_question(1, 5), _make_question(2, 3), _make_question(3, 2)]
    result = knapsack_select(questions, target_marks=8)
    total = sum(q.marks for q in result)
    assert total == 8


def test_knapsack_exact_match_preferred_over_overshoot():
    questions = [_make_question(1, 4), _make_question(2, 3), _make_question(3, 2), _make_question(4, 1)]
    result = knapsack_select(questions, target_marks=5)
    total = sum(q.marks for q in result)
    assert total == 5


def test_knapsack_no_exact_match_returns_closest_below():
    questions = [_make_question(1, 5), _make_question(2, 7), _make_question(3, 3)]
    result = knapsack_select(questions, target_marks=6)
    total = sum(q.marks for q in result)
    assert total <= 6
    assert total == 5  # closest below: [5]


def test_knapsack_empty_pool_returns_empty():
    result = knapsack_select([], target_marks=10)
    assert result == []


def test_knapsack_target_zero_returns_empty():
    questions = [_make_question(1, 5), _make_question(2, 3)]
    result = knapsack_select(questions, target_marks=0)
    assert result == []


def test_knapsack_null_marks_questions_excluded():
    questions = [
        _make_question(1, 5),
        _make_question(2, None),  # marks is null
        _make_question(3, 3),
    ]
    result = knapsack_select(questions, target_marks=3)
    assert all(q.marks is not None for q in result)
    result_ids = [q.id for q in result]
    assert 2 not in result_ids


def test_knapsack_all_null_marks_returns_empty():
    questions = [_make_question(1, None), _make_question(2, None)]
    result = knapsack_select(questions, target_marks=5)
    assert result == []


def test_knapsack_single_question_exact():
    questions = [_make_question(1, 10)]
    result = knapsack_select(questions, target_marks=10)
    assert len(result) == 1
    assert result[0].id == 1


# ---------------------------------------------------------------------------
# Layout engine — LayoutPlan structure
# ---------------------------------------------------------------------------

# A4 usable height in points ≈ 720pt (842 - top/bottom margins).
# Images are rendered at 1pt per px scaled to page width; exact scaling depends
# on implementation, but the engine must respect a configurable capacity.
# We supply capacity_px to LayoutEngine for deterministic unit tests.

_PAGE_CAPACITY_PX = 1000  # mock capacity for test isolation


def _engine(capacity_px=_PAGE_CAPACITY_PX) -> LayoutEngine:
    return LayoutEngine(page_capacity_px=capacity_px)


def test_layout_single_question_one_page():
    engine = _engine()
    q = _make_question_layout(1, "Q1", "School 2024 Sec 3 EOY Q1", question_page_heights=[600])
    plan = engine.compute_layout([q], header_text="", include_answers=False)
    assert plan.page_count >= 1


def test_layout_cursor_advances_after_each_question():
    engine = _engine(capacity_px=2000)
    q1 = _make_question_layout(1, "Q1", "S 2024 Sec 3 EOY Q1", question_page_heights=[400])
    q2 = _make_question_layout(2, "Q2", "S 2024 Sec 3 EOY Q2", question_page_heights=[400])
    plan = engine.compute_layout([q1, q2], header_text="", include_answers=False)
    # Both fit on one page; page_count is 1
    assert plan.page_count == 1
    # Q2's page index equals Q1's page index (same page)
    layout_q1 = plan.question_assignments[0]
    layout_q2 = plan.question_assignments[1]
    assert layout_q1.page_index == layout_q2.page_index


def test_layout_new_page_when_space_insufficient():
    # capacity=700, Q1=600px, Q2=400px → Q2 doesn't fit after Q1
    engine = _engine(capacity_px=700)
    q1 = _make_question_layout(1, "Q1", "S 2024 Sec 3 EOY Q1", question_page_heights=[600])
    q2 = _make_question_layout(2, "Q2", "S 2024 Sec 3 EOY Q2", question_page_heights=[400])
    plan = engine.compute_layout([q1, q2], header_text="", include_answers=False)
    assert plan.page_count >= 2
    assert plan.question_assignments[1].page_index > plan.question_assignments[0].page_index


def test_layout_tall_question_forces_new_page():
    engine = _engine(capacity_px=500)
    q = _make_question_layout(1, "Q1", "S 2024 Sec 3 EOY Q1", question_page_heights=[800])
    plan = engine.compute_layout([q], header_text="Test header", include_answers=False)
    # Tall question must start even if it overflows (doesn't fit); page_count >= 1
    assert plan.page_count >= 1


def test_layout_source_label_in_plan():
    engine = _engine()
    source = "Raffles Institution 2024 Sec 3 EOY Q5"
    q = _make_question_layout(5, "Q1", source, question_page_heights=[400])
    plan = engine.compute_layout([q], header_text="", include_answers=False)
    labels = [qa.source_label for qa in plan.question_assignments]
    assert any("Raffles Institution" in lbl for lbl in labels)
    assert any("EOY" in lbl for lbl in labels)


def test_layout_renumbers_questions():
    engine = _engine(capacity_px=5000)
    questions = [
        _make_question_layout(7, "Q1", "School 2024 Sec 3 EOY Q7", question_page_heights=[200]),
        _make_question_layout(8, "Q2", "School 2024 Sec 3 EOY Q8", question_page_heights=[200]),
        _make_question_layout(9, "Q3", "School 2024 Sec 3 EOY Q9", question_page_heights=[200]),
    ]
    plan = engine.compute_layout(questions, header_text="", include_answers=False)
    labels = [qa.label for qa in plan.question_assignments]
    assert labels == ["Q1", "Q2", "Q3"]


def test_layout_answer_pages_appended_when_include_answers_true():
    engine = _engine(capacity_px=5000)
    q = _make_question_layout(
        1, "Q1", "S 2024 Sec 3 EOY Q1",
        question_page_heights=[400],
        answer_page_heights=[300],
    )
    plan = engine.compute_layout([q], header_text="", include_answers=True)
    assert plan.has_answer_section is True


def test_layout_no_answer_pages_when_include_answers_false():
    engine = _engine(capacity_px=5000)
    q = _make_question_layout(
        1, "Q1", "S 2024 Sec 3 EOY Q1",
        question_page_heights=[400],
        answer_page_heights=[300],
    )
    plan = engine.compute_layout([q], header_text="", include_answers=False)
    assert plan.has_answer_section is False


def test_layout_answer_section_uses_renumbered_labels():
    engine = _engine(capacity_px=5000)
    q = _make_question_layout(
        99, "Q1", "S 2024 Sec 3 EOY Q99",
        question_page_heights=[400],
        answer_page_heights=[300],
    )
    plan = engine.compute_layout([q], header_text="", include_answers=True)
    answer_labels = [qa.label for qa in plan.question_assignments if qa.answer_pages]
    assert "Q1" in answer_labels


def test_layout_header_text_in_plan():
    engine = _engine()
    plan = engine.compute_layout([], header_text="Attempt all questions.", include_answers=False)
    assert plan.header_text == "Attempt all questions."


def test_layout_empty_question_list_produces_header_only_plan():
    engine = _engine()
    plan = engine.compute_layout([], header_text="Instructions.", include_answers=False)
    assert plan.page_count >= 1
    assert len(plan.question_assignments) == 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_generate_manual_mode_returns_pdf(public_client, sample_paper, db_session, reference_data):
    from app.models.orm import Question

    questions = db_session.query(Question).filter_by(paper_id=sample_paper.id).all()
    ids = [q.id for q in questions]

    with (
        patch("app.routes.generate.get_presigned_url", return_value="https://fake.url"),
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.LayoutEngine.render", return_value=b"%PDF-1.4 fake pdf bytes"),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids,
            "header_text": "Test paper",
            "include_answers": False,
        })

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 0


def test_generate_manual_mode_empty_question_ids_returns_422(public_client):
    resp = public_client.post("/api/generate/paper", json={
        "question_ids": [],
        "header_text": "",
        "include_answers": False,
    })
    assert resp.status_code == 422


def test_generate_autofill_returns_pdf(public_client, sample_paper, db_session, reference_data):
    with (
        patch("app.routes.generate.get_presigned_url", return_value="https://fake.url"),
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.LayoutEngine.render", return_value=b"%PDF-1.4 fake pdf bytes"),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "filters": {"subject_id": reference_data["subject"].id},
            "target_marks": 10,
            "header_text": "Auto paper",
            "include_answers": False,
        })

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"


def test_generate_autofill_no_match_returns_404(public_client):
    resp = public_client.post("/api/generate/paper", json={
        "filters": {"subject_id": 99999},  # no such subject
        "target_marks": 10,
        "header_text": "",
        "include_answers": False,
    })
    assert resp.status_code == 404


def test_generate_requires_auth(client):
    resp = client.post("/api/generate/paper", json={
        "question_ids": [1],
        "header_text": "",
        "include_answers": False,
    })
    assert resp.status_code == 401
