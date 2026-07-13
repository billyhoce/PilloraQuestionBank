"""Tests for knapsack selection, PDF layout engine, and generation routes."""
import io
from typing import Optional
from unittest.mock import MagicMock, patch

from pypdf import PdfReader

from app.models.orm import Question
from app.pdf.layout_engine import Block, LayoutEngine, LayoutPlan, render_combined
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


def test_credit_reserves_extra_block_height():
    # show_credit adds a fixed band above each block, so the same block is taller
    # under a credit-enabled engine than one without.
    from app.pdf.layout_engine import _CREDIT_BAND_PX

    block = _make_block("1", [800])
    plain = LayoutEngine(fit_width=False, show_credit=False)
    credited = LayoutEngine(fit_width=False, show_credit=True)
    assert credited._block_height_px(block) == plain._block_height_px(block) + _CREDIT_BAND_PX


def test_credit_skipped_when_source_label_empty():
    block = _make_block("1", [800], source_label="")
    credited = LayoutEngine(fit_width=False, show_credit=True)
    assert credited._block_height_px(block) == 800  # no band reserved


def test_credit_variant_renders_pdf(minimal_webp_bytes):
    engine = LayoutEngine(fit_width=True, show_credit=True)
    plan = engine.compute_layout([_make_block("1", [800])])
    pdf = engine.render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Layout engine — page chrome (header/footer)
# ---------------------------------------------------------------------------


def test_chrome_renders_without_logo(minimal_webp_bytes, monkeypatch):
    # Missing logo asset must not raise — chrome renders without it.
    from app.pdf import layout_engine

    layout_engine._load_logo.cache_clear()
    monkeypatch.setattr(layout_engine, "LOGO_PATH", "/no/such/logo.png")
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([_make_block("1", [800])])
    plan.footer_label = "Questions"
    pdf = engine.render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"
    layout_engine._load_logo.cache_clear()


def test_chrome_renders_with_logo(minimal_webp_bytes, tmp_path, monkeypatch):
    # A present logo exercises the drawImage(logo) path.
    from PIL import Image as PILImage

    from app.pdf import layout_engine

    logo = tmp_path / "pillora_logo.png"
    PILImage.new("RGBA", (500, 200), (134, 59, 255, 255)).save(logo)
    layout_engine._load_logo.cache_clear()
    monkeypatch.setattr(layout_engine, "LOGO_PATH", str(logo))
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([_make_block("1", [800])])
    pdf = engine.render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"
    layout_engine._load_logo.cache_clear()


def test_chrome_does_not_change_page_count(minimal_webp_bytes):
    # Chrome is drawn on every page but never adds pages.
    engine = _engine(capacity_px=1000)
    plan = engine.compute_layout([_make_block("1", [800]), _make_block("2", [800])])
    plan.footer_label = "Questions"
    pdf = engine.render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert _page_count(pdf) == 2


def test_layout_plan_footer_label_defaults_empty():
    plan = LayoutEngine().compute_layout([])
    assert plan.footer_label == ""


# ---------------------------------------------------------------------------
# Layout engine — cover page
# ---------------------------------------------------------------------------


def _cover(total_marks=42, is_questions=True):
    from app.pdf.layout_engine import CoverSpec

    return CoverSpec(
        title="Topical Worksheets",
        subtitle1="Secondary 3 Mathematics",
        subtitle2="2024 Prelim",
        body="Dear students,\n\nWork hard.\n\nTeacher Jia Xin",
        total_marks=total_marks,
        is_questions=is_questions,
    )


def test_cover_adds_one_page(minimal_webp_bytes):
    engine = LayoutEngine(fit_width=True)
    blocks = [_make_block("1", [800])]
    no_cover = engine.compute_layout(blocks)
    with_cover = engine.compute_layout([_make_block("1", [800])])
    with_cover.cover = _cover()
    n0 = _page_count(engine.render(no_cover, fetch_bytes=lambda k: minimal_webp_bytes))
    n1 = _page_count(engine.render(with_cover, fetch_bytes=lambda k: minimal_webp_bytes))
    assert n1 == n0 + 1


def test_cover_renders_without_logo(minimal_webp_bytes, monkeypatch):
    from app.pdf import layout_engine

    layout_engine._load_logo.cache_clear()
    monkeypatch.setattr(layout_engine, "LOGO_PATH", "/no/such/logo.png")
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([_make_block("1", [800])])
    plan.cover = _cover()
    pdf = engine.render(plan, fetch_bytes=lambda k: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"
    layout_engine._load_logo.cache_clear()


def test_cover_empty_blocks_still_renders(minimal_webp_bytes):
    # A cover with no questions is a single page.
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([])
    plan.cover = _cover()
    pdf = engine.render(plan, fetch_bytes=lambda k: minimal_webp_bytes)
    assert _page_count(pdf) == 1


def _page_link_uris(pdf: bytes, page_index: int) -> list[str]:
    """URI targets of the link annotations on one page of the PDF."""
    page = PdfReader(io.BytesIO(pdf)).pages[page_index]
    uris = []
    for annot in page.get("/Annots") or []:
        action = annot.get_object().get("/A")
        if action and action.get("/URI"):
            uris.append(str(action["/URI"]))
    return uris


def test_cover_body_html_link_is_clickable(minimal_webp_bytes):
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([_make_block("1", [800])])
    plan.cover = _cover()
    plan.cover.body = (
        "<p>Dear students,</p>"
        '<p>Visit <a href="https://example.com/consult">my website</a> to book.</p>'
    )
    pdf = engine.render(plan, fetch_bytes=lambda k: minimal_webp_bytes)
    assert "https://example.com/consult" in _page_link_uris(pdf, 0)


def test_cover_body_rich_text_renders(minimal_webp_bytes):
    # Bold/italic/underline marks and empty paragraphs render without error.
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([])
    plan.cover = _cover()
    plan.cover.body = "<p><b>Bold</b> <i>italic</i> <u>underline</u></p><p></p><p>End</p>"
    pdf = engine.render(plan, fetch_bytes=lambda k: minimal_webp_bytes)
    assert _page_count(pdf) == 1


def test_every_page_has_clickable_website_chrome(minimal_webp_bytes):
    # The www.pillora.com.sg header chrome links out on cover and content pages.
    engine = LayoutEngine(fit_width=True)
    plan = engine.compute_layout([_make_block("1", [800])])
    plan.cover = _cover()
    pdf = engine.render(plan, fetch_bytes=lambda k: minimal_webp_bytes)
    for page_index in range(_page_count(pdf)):
        assert "https://www.pillora.com.sg" in _page_link_uris(pdf, page_index)


def test_question_variant_has_no_block_gap():
    engine = LayoutEngine(fit_width=True)
    assert engine.block_gap_px == 0
    # Without a gap the two 400px (scaled) blocks comfortably share a page.
    plan = engine.compute_layout([_make_block("1", [400]), _make_block("2", [400])])
    assert plan.blocks[0].page_index == plan.blocks[1].page_index == 0


# ---------------------------------------------------------------------------
# Layout engine — combined rendering
# ---------------------------------------------------------------------------


def _page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def test_render_returns_expected_page_count(minimal_webp_bytes):
    # Refactor guard: single-plan render still produces one page per packed page.
    # capacity=1000, gap=100 (fit_width=False): 800 + 100 + 800 > 1000 → 2 pages.
    engine = _engine(capacity_px=1000)
    plan = engine.compute_layout([_make_block("1", [800]), _make_block("2", [800])])
    pdf = engine.render(plan, fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 2


def test_render_combined_appends_sections(minimal_webp_bytes):
    # Section 1 packs onto one page (400 + 100 + 400 ≤ 1000); section 2 is one
    # page — the combined PDF holds both, each section starting on a fresh page.
    e1 = _engine(capacity_px=1000)
    p1 = e1.compute_layout([_make_block("1", [400]), _make_block("2", [400])])
    e2 = _engine(capacity_px=1000)
    p2 = e2.compute_layout([_make_block("2", [400])])
    pdf = render_combined([(e1, p1), (e2, p2)], fetch_bytes=lambda key: minimal_webp_bytes)
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 2


def test_render_combined_matches_separate_renders(minimal_webp_bytes):
    # Combined page count equals the sum of the separately rendered sections.
    e1 = LayoutEngine(fit_width=True)
    p1 = e1.compute_layout([_make_block("1", [800])], header_text="Header")
    e2 = LayoutEngine(fit_width=False)
    p2 = e2.compute_layout([_make_block("1", [800])])
    fetch = lambda key: minimal_webp_bytes  # noqa: E731
    separate = _page_count(e1.render(p1, fetch)) + _page_count(e2.render(p2, fetch))
    combined = _page_count(render_combined([(e1, p1), (e2, p2)], fetch))
    assert combined == separate == 2


# ---------------------------------------------------------------------------
# Routes — /api/generate/cover-defaults
# ---------------------------------------------------------------------------


def test_cover_defaults_requires_auth(client):
    resp = client.get("/api/generate/cover-defaults")
    assert resp.status_code == 401


def test_cover_defaults_match_paper_request_defaults(public_client):
    """The served defaults are the same values GeneratePaperRequest falls back
    to, so a client pre-filling from this endpoint and one omitting the fields
    produce identical covers."""
    from app.schemas.generate import GeneratePaperRequest

    resp = public_client.get("/api/generate/cover-defaults")
    assert resp.status_code == 200
    data = resp.json()
    defaults = GeneratePaperRequest(question_ids=[1])
    assert data["cover_title"] == defaults.cover_title
    assert data["cover_body"] == defaults.cover_body
    assert "Dear students," in data["cover_body"]
    assert '<a href="https://www.pillora.com.sg">' in data["cover_body"]


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


def test_generate_select_accepts_search_filter(public_client, sample_paper, reference_data):
    """filters.search narrows the candidate pool like the Browse search box."""
    # Matching keyword (school name) — pool is the sample paper's questions
    resp = public_client.post("/api/generate/select", json={
        "filters": {"search": "raffles"},
        "target_marks": 5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_marks"] == 5
    assert data["exact"] is True

    # Non-matching keyword — empty pool
    resp = public_client.post("/api/generate/select", json={
        "filters": {"search": "zzz-no-such-thing"},
        "target_marks": 5,
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


def test_generate_paper_question_variant_credits_source(
    public_client, sample_paper, db_session, reference_data
):
    # Question variant enables credits and labels each block with the slash format
    # [School/Year/ExamType/P{paper_number}/Q{question_number}].
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_compute(self, blocks, header_text=""):
        captured["blocks"] = blocks
        captured["show_credit"] = self.show_credit
        return LayoutPlan(page_count=1, blocks=blocks, header_text=header_text)

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch.object(LayoutEngine, "compute_layout", spy_compute),
        patch.object(LayoutEngine, "render", return_value=b"%PDF fake"),
    ):
        resp = public_client.post("/api/generate/paper", json={"question_ids": ids, "variant": "question"})

    assert resp.status_code == 200
    assert captured["show_credit"] is True
    assert captured["blocks"][0].source_label == "[Raffles Institution/2024/EOY/P1/Q1]"


def test_generate_paper_answer_variant_no_credit(
    public_client, sample_paper, db_session, reference_data
):
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_compute(self, blocks, header_text=""):
        captured["show_credit"] = self.show_credit
        return LayoutPlan(page_count=1, blocks=blocks, header_text=header_text)

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch.object(LayoutEngine, "compute_layout", spy_compute),
        patch.object(LayoutEngine, "render", return_value=b"%PDF fake"),
    ):
        resp = public_client.post("/api/generate/paper", json={"question_ids": ids, "variant": "answer"})

    assert resp.status_code == 200
    assert captured["show_credit"] is False


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


def test_generate_paper_combined_returns_pdf(public_client, sample_paper, db_session, reference_data):
    ids = _question_ids(db_session, sample_paper)
    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.render_combined", return_value=b"%PDF-1.4 fake pdf bytes"),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids,
            "variant": "combined",
            "header_text": "Test paper",
        })
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 0


def test_generate_paper_combined_builds_question_then_answer_sections(
    public_client, sample_paper, db_session, reference_data
):
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_render_combined(sections, fetch_bytes):
        captured["sections"] = sections
        return b"%PDF fake"

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.render_combined", spy_render_combined),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids,
            "variant": "combined",
            "header_text": "Test paper",
        })

    assert resp.status_code == 200
    sections = captured["sections"]
    assert len(sections) == 2

    q_engine, q_plan = sections[0]
    assert q_engine.fit_width is True
    assert q_engine.show_credit is True
    assert q_plan.header_text == "Test paper"
    assert q_plan.footer_label == "Questions"
    assert [b.label for b in q_plan.blocks] == ["1", "2", "3"]

    a_engine, a_plan = sections[1]
    assert a_engine.fit_width is False
    assert a_engine.show_credit is False
    assert a_plan.footer_label == "Answers"
    assert a_plan.header_text == ""
    # Only Q2 has answer pages; it keeps its question number.
    assert [b.label for b in a_plan.blocks] == ["2"]
    assert all(p.page_type == "answer" for p in a_plan.blocks[0].pages)


def test_generate_paper_combined_omits_empty_answer_section(
    public_client, sample_paper, db_session, reference_data
):
    # Select only questions without answer pages (all but Q2) — no answer section.
    qs = (
        db_session.query(Question)
        .filter_by(paper_id=sample_paper.id)
        .order_by(Question.question_number)
        .all()
    )
    ids = [q.id for q in qs if q.question_number != 2]
    assert ids
    captured = {}

    def spy_render_combined(sections, fetch_bytes):
        captured["sections"] = sections
        return b"%PDF fake"

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.render_combined", spy_render_combined),
    ):
        resp = public_client.post("/api/generate/paper", json={"question_ids": ids, "variant": "combined"})

    assert resp.status_code == 200
    assert len(captured["sections"]) == 1
    assert captured["sections"][0][0].fit_width is True


def test_generate_paper_attaches_cover_and_total_marks(
    public_client, sample_paper, db_session, reference_data
):
    # Question variant: cover built with the paper total (5+3+2) and Questions.
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_render(self, plan, fetch_bytes):
        captured["plan"] = plan
        return b"%PDF fake"

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch.object(LayoutEngine, "render", spy_render),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids,
            "variant": "question",
            "cover_title": "My Paper",
            "cover_subtitle2": "2024 Prelim",
        })

    assert resp.status_code == 200
    plan = captured["plan"]
    assert plan.cover is not None
    assert plan.cover.total_marks == 10
    assert plan.cover.is_questions is True
    assert plan.cover.title == "My Paper"
    assert plan.footer_label == "2024 Prelim Questions"


def test_generate_paper_include_cover_false_omits_cover(
    public_client, sample_paper, db_session, reference_data
):
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_render(self, plan, fetch_bytes):
        captured["plan"] = plan
        return b"%PDF fake"

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch.object(LayoutEngine, "render", spy_render),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids, "variant": "question", "include_cover": False,
        })

    assert resp.status_code == 200
    assert captured["plan"].cover is None


def test_generate_paper_combined_covers_each_section(
    public_client, sample_paper, db_session, reference_data
):
    ids = _question_ids(db_session, sample_paper)
    captured = {}

    def spy_render_combined(sections, fetch_bytes):
        captured["sections"] = sections
        return b"%PDF fake"

    with (
        patch("app.routes.generate.get_image_bytes", return_value=b"fake-img"),
        patch("app.routes.generate.render_combined", spy_render_combined),
    ):
        resp = public_client.post("/api/generate/paper", json={
            "question_ids": ids, "variant": "combined", "cover_subtitle2": "2024 Prelim",
        })

    assert resp.status_code == 200
    (_, q_plan), (_, a_plan) = captured["sections"]
    assert q_plan.cover.is_questions is True and q_plan.cover.total_marks == 10
    assert a_plan.cover.is_questions is False and a_plan.cover.total_marks == 10
    assert a_plan.footer_label == "2024 Prelim Answers"


def test_generate_paper_rejects_unknown_variant(public_client):
    resp = public_client.post("/api/generate/paper", json={"question_ids": [1], "variant": "both"})
    assert resp.status_code == 422
