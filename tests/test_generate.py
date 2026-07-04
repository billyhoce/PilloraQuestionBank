"""Tests for knapsack selection, PDF layout engine, and generation routes."""
from typing import Optional
from unittest.mock import MagicMock, patch

from app.models.orm import Question
from app.pdf.layout_engine import Block, LayoutEngine, LayoutPlan
from app.services.generate import knapsack_select

# The knapsack function, /api/generate/select, and the PDF layout engine +
# /api/generate/paper route are all implemented — every test here runs for real.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_question(id: int, marks: Optional[int], question_number: int = 1) -> MagicMock:
    q = MagicMock(spec=Question)
    q.id = id
    q.marks = marks
    q.question_number = question_number
    return q


def _make_block(
    label: str,
    page_heights: list[int],
    source_label: str = "School 2024 Sec 3 EOY Q1",
    page_index: int = 0,
) -> Block:
    pages = [
        MagicMock(image_key=f"k_{label}_{i}.webp", height_px=h, width_px=2480, page_order=i)
        for i, h in enumerate(page_heights)
    ]
    return Block(label=label, source_label=source_label, pages=pages, page_index=page_index)


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


def test_knapsack_no_exact_match_returns_closest():
    # No subset of [5, 7, 3] sums to 6; closest either way is 5 or 7 (distance 1).
    questions = [_make_question(1, 5), _make_question(2, 7), _make_question(3, 3)]
    result = knapsack_select(questions, target_marks=6)
    total = sum(q.marks for q in result)
    assert abs(total - 6) <= 1


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


def test_knapsack_randomized_produces_variety():
    # A pool with many exact-8 combinations should not always return the same one.
    questions = [_make_question(i, m) for i, m in enumerate([1, 2, 3, 4, 5, 6, 7], start=1)]
    seen = set()
    for _ in range(20):
        result = knapsack_select(questions, target_marks=8)
        assert sum(q.marks for q in result) == 8
        seen.add(frozenset(q.id for q in result))
    assert len(seen) > 1


# ---------------------------------------------------------------------------
# Layout engine — compute_layout packing (page_capacity_px in px)
# ---------------------------------------------------------------------------


def _engine(capacity_px=1000, fit_width=False) -> LayoutEngine:
    # Packing tests use fit_width=False so block heights map 1:1 (no image
    # scaling), keeping the capacity/height arithmetic easy to reason about.
    return LayoutEngine(page_capacity_px=capacity_px, fit_width=fit_width)


def test_layout_single_block_one_page():
    plan = _engine().compute_layout([_make_block("1", [600])])
    assert plan.page_count == 1
    assert plan.blocks[0].page_index == 0


def test_layout_consecutive_blocks_share_a_page():
    # capacity=2000, two 400px blocks → both on page 0.
    plan = _engine(capacity_px=2000).compute_layout([_make_block("1", [400]), _make_block("2", [400])])
    assert plan.page_count == 1
    assert plan.blocks[0].page_index == plan.blocks[1].page_index == 0


def test_layout_new_page_when_space_insufficient():
    # capacity=700, Q1=600px, Q2=400px → Q2 doesn't fit after Q1.
    plan = _engine(capacity_px=700).compute_layout([_make_block("1", [600]), _make_block("2", [400])])
    assert plan.page_count >= 2
    assert plan.blocks[1].page_index > plan.blocks[0].page_index


def test_layout_packs_by_running_total():
    # The worked example: capacity=600, heights 200/300/200 → [Q1,Q2] then [Q3].
    plan = _engine(capacity_px=600).compute_layout(
        [_make_block("1", [200]), _make_block("2", [300]), _make_block("3", [200])]
    )
    assert [b.page_index for b in plan.blocks] == [0, 0, 1]
    assert plan.page_count == 2


def test_layout_tall_block_starts_fresh():
    # A block taller than a page still starts on its own page (page_index 0 here).
    plan = _engine(capacity_px=500).compute_layout([_make_block("1", [800])])
    assert plan.page_count >= 1
    assert plan.blocks[0].page_index == 0


def test_layout_multipage_block_flows():
    # Two 400px pages within one block, capacity 500: the block still starts on
    # page 0; render flows the second page. compute_layout counts the start page.
    plan = _engine(capacity_px=500).compute_layout([_make_block("1", [400, 400])])
    assert plan.blocks[0].page_index == 0


def test_layout_preserves_labels_and_order():
    plan = _engine(capacity_px=5000).compute_layout(
        [_make_block("1", [200]), _make_block("2", [200]), _make_block("3", [200])]
    )
    assert [b.label for b in plan.blocks] == ["1", "2", "3"]


def test_layout_header_text_in_plan():
    plan = _engine().compute_layout([], header_text="Attempt all questions.")
    assert plan.header_text == "Attempt all questions."


def test_layout_empty_block_list_produces_at_least_one_page():
    plan = _engine().compute_layout([], header_text="Instructions.")
    assert plan.page_count >= 1
    assert plan.blocks == []


def test_layout_render_returns_pdf_bytes(minimal_webp_bytes):
    # End-to-end render with real ReportLab + a real WebP image.
    plan = _engine().compute_layout([_make_block("1", [800])], header_text="Header")
    pdf = _engine().render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 0


def test_question_variant_scales_image_down():
    # fit_width=True scales a full-width (2480px) page to 1760px content width,
    # which lowers its height proportionally.
    block = _make_block("1", [800])  # width_px=2480, height_px=800
    q_engine = LayoutEngine(fit_width=True)
    a_engine = LayoutEngine(fit_width=False)
    assert q_engine._block_height_px(block) < 800  # scaled to 1760px content width
    assert a_engine._block_height_px(block) == 800  # native size preserved


def test_answer_variant_renders_native(minimal_webp_bytes):
    plan = LayoutEngine(fit_width=False).compute_layout([_make_block("1", [800])])
    pdf = LayoutEngine(fit_width=False).render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"


def test_answer_variant_adds_gap_between_blocks():
    # capacity 810: two 400px answer blocks total 800px, which would otherwise
    # fit — but the 100px inter-question gap pushes the second block to a new page.
    engine = LayoutEngine(page_capacity_px=810, fit_width=False)
    assert engine.block_gap_px == 100
    plan = engine.compute_layout([_make_block("1", [400]), _make_block("2", [400])])
    assert [b.page_index for b in plan.blocks] == [0, 1]


def test_question_variant_has_no_block_gap():
    engine = LayoutEngine(fit_width=True)
    assert engine.block_gap_px == 0
    # Without a gap the two 400px (scaled) blocks comfortably share a page.
    plan = engine.compute_layout([_make_block("1", [400]), _make_block("2", [400])])
    assert plan.blocks[0].page_index == plan.blocks[1].page_index == 0


# ---------------------------------------------------------------------------
# Routes — /api/generate/select (implemented)
# ---------------------------------------------------------------------------


def test_generate_select_requires_auth(client):
    resp = client.post("/api/generate/select", json={"filters": {}, "target_marks": 10})
    assert resp.status_code == 401


def test_generate_select_returns_selection(public_client, sample_paper, reference_data):
    resp = public_client.post("/api/generate/select", json={
        "filters": {"subject_id": reference_data["subject"].id},
        "target_marks": 10,  # 5 + 3 + 2 = 10, exact
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_marks"] == 10
    assert data["target_marks"] == 10
    assert data["exact"] is True
    assert data["warning"] is None
    assert len(data["items"]) == 3


def test_generate_select_excludes_ids(public_client, sample_paper, db_session, reference_data):
    qs = db_session.query(Question).filter_by(paper_id=sample_paper.id).all()
    excluded = [q.id for q in qs if q.marks == 5]  # the 5-mark question
    resp = public_client.post("/api/generate/select", json={
        "filters": {"subject_id": reference_data["subject"].id},
        "target_marks": 5,  # remaining pool is 3 + 2 = 5
        "exclude_question_ids": excluded,
    })
    assert resp.status_code == 200
    data = resp.json()
    ids = [it["id"] for it in data["items"]]
    assert excluded[0] not in ids
    assert data["total_marks"] == 5
    assert data["exact"] is True


def test_generate_select_no_match_returns_warning(public_client):
    resp = public_client.post("/api/generate/select", json={
        "filters": {"subject_id": 99999},  # no such subject
        "target_marks": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["warning"] is not None


def test_generate_select_inexact_returns_warning(public_client, sample_paper, reference_data):
    resp = public_client.post("/api/generate/select", json={
        "filters": {"subject_id": reference_data["subject"].id},
        "target_marks": 100,  # unreachable; best is all questions = 10
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["exact"] is False
    assert data["warning"] is not None
    assert data["total_marks"] == 10


# ---------------------------------------------------------------------------
# Routes — /api/generate/paper PDF export (deferred: PDF phase)
# ---------------------------------------------------------------------------


def _question_ids(db_session, paper) -> list[int]:
    qs = (
        db_session.query(Question)
        .filter_by(paper_id=paper.id)
        .order_by(Question.question_number)
        .all()
    )
    return [q.id for q in qs]


def test_generate_paper_returns_pdf(public_client, sample_paper, db_session, reference_data):
    ids = _question_ids(db_session, sample_paper)
    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.LayoutEngine.render", return_value=b"%PDF-1.4 fake pdf bytes"),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids,
            "variant": "question",
            "header_text": "Test paper",
        })
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 0


def test_generate_paper_empty_question_ids_returns_422(public_client):
    resp = public_client.post("/api/generate/paper", json={"question_ids": [], "variant": "question"})
    assert resp.status_code == 422


def test_generate_paper_requires_auth(client):
    resp = client.post("/api/generate/paper", json={"question_ids": [1], "variant": "question"})
    assert resp.status_code == 401


def test_generate_paper_renumbers_in_selection_order(public_client, sample_paper, db_session, reference_data):
    # Reverse the natural order; blocks must be labeled 1..N in the given order.
    ids = list(reversed(_question_ids(db_session, sample_paper)))
    captured = {}

    def spy_compute(self, blocks, header_text=""):
        captured["blocks"] = blocks
        captured["fit_width"] = self.fit_width
        return LayoutPlan(page_count=1, blocks=blocks, header_text=header_text)

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch.object(LayoutEngine, "compute_layout", spy_compute),
        patch.object(LayoutEngine, "render", return_value=b"%PDF fake"),
    ):
        resp = public_client.post("/api/generate/paper", json={"question_ids": ids, "variant": "question"})

    assert resp.status_code == 200
    blocks = captured["blocks"]
    assert [b.label for b in blocks] == ["1", "2", "3"]
    # First selected id maps to label "1".
    assert blocks[0].pages[0].image_key.endswith("question_0.webp")
    # Question variant scales images to a fixed 1760px content width.
    assert captured["fit_width"] is True


def test_generate_paper_answer_variant_skips_questions_without_answers(
    public_client, sample_paper, db_session, reference_data
):
    # In sample_paper only Q2 has an answer page. Answer variant → 1 block, kept
    # at its selection number ("2").
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_compute(self, blocks, header_text=""):
        captured["blocks"] = blocks
        captured["fit_width"] = self.fit_width
        return LayoutPlan(page_count=1, blocks=blocks, header_text=header_text)

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch.object(LayoutEngine, "compute_layout", spy_compute),
        patch.object(LayoutEngine, "render", return_value=b"%PDF fake"),
    ):
        resp = public_client.post("/api/generate/paper", json={"question_ids": ids, "variant": "answer"})

    assert resp.status_code == 200
    blocks = captured["blocks"]
    assert len(blocks) == 1
    assert blocks[0].label == "2"
    assert all(p.page_type == "answer" for p in blocks[0].pages)
    # Answer variant keeps native image size (flush-left, no centering).
    assert captured["fit_width"] is False
