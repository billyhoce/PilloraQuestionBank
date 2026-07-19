"""Tests for the local sample-PDF generator and PDF→PNG converter scripts.

These drive the real layout engine end-to-end with synthetic images — no DB,
S3, or network. Expected page counts are computed from the engine itself so
the tests don't hardcode page geometry.
"""
import io
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import generate_sample_pdf  # noqa: E402
import pdf_to_images  # noqa: E402

from app.pdf.layout_engine import LayoutEngine  # noqa: E402
from app.pdf.sample_data import build_sample_blocks, make_page_png  # noqa: E402


def _planned_pages(n_questions: int, variant: str) -> int:
    """Page count the engine's own layout predicts for a synthetic paper."""
    blocks, _ = build_sample_blocks(n_questions, variant)
    is_question = variant == "question"
    engine = LayoutEngine(fit_width=is_question, show_credit=is_question)
    return engine.compute_layout(blocks).page_count


def _page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def test_make_page_png_dimensions():
    raw = make_page_png(1234, 567, "label")
    img = Image.open(io.BytesIO(raw))
    assert img.size == (1234, 567)


def test_question_variant_page_count(tmp_path):
    out = tmp_path / "q.pdf"
    rc = generate_sample_pdf.main(
        ["--variant", "question", "--questions", "3", "--no-cover", "--out", str(out)]
    )
    assert rc == 0
    # The first three synthetic questions are small blocks with no overflow, so
    # the rendered count matches the layout estimate exactly.
    assert _page_count(out) == _planned_pages(3, "question")


def test_cover_adds_one_page(tmp_path):
    args = ["--variant", "question", "--questions", "3", "--out"]
    without = tmp_path / "without.pdf"
    with_cover = tmp_path / "with.pdf"
    generate_sample_pdf.main([*args, str(without), "--no-cover"])
    generate_sample_pdf.main([*args, str(with_cover), "--cover"])
    assert _page_count(with_cover) == _page_count(without) + 1


def test_combined_has_both_sections(tmp_path):
    out = tmp_path / "combined.pdf"
    generate_sample_pdf.main(
        ["--variant", "combined", "--questions", "3", "--no-cover", "--out", str(out)]
    )
    expected = _planned_pages(3, "question") + _planned_pages(3, "answer")
    assert _page_count(out) == expected


def test_multi_page_block_overflows_layout_estimate(tmp_path):
    # Question 5's two images sum taller than a page, so rendering flows onto
    # an extra page that compute_layout's estimate doesn't count.
    out = tmp_path / "overflow.pdf"
    generate_sample_pdf.main(
        ["--variant", "question", "--questions", "5", "--no-cover", "--out", str(out)]
    )
    assert _page_count(out) > _planned_pages(5, "question")


def test_png_conversion(tmp_path):
    out = tmp_path / "paper.pdf"
    generate_sample_pdf.main(
        [
            "--variant", "question", "--questions", "2", "--no-cover",
            "--out", str(out), "--png", "--dpi", "60",
        ]
    )
    pngs = sorted((tmp_path / "paper_pages").glob("page_*.png"))
    assert len(pngs) == _page_count(out)
    img = Image.open(pngs[0])
    # A4 at 60 dpi: 8.27in × 11.69in → ~496×702 px.
    assert img.size[0] == pytest.approx(496, abs=1)
    assert img.size[1] == pytest.approx(702, abs=1)


def test_pdf_to_images_standalone(tmp_path):
    pdf = tmp_path / "any.pdf"
    generate_sample_pdf.main(
        ["--variant", "answer", "--questions", "2", "--no-cover", "--out", str(pdf)]
    )
    out_dir = tmp_path / "custom_out"
    paths = pdf_to_images.pdf_to_pngs(pdf, out_dir, dpi=60)
    assert [p.parent for p in paths] == [out_dir] * len(paths)
    assert len(paths) == _page_count(pdf)
    assert all(p.exists() for p in paths)


def test_user_supplied_image(tmp_path):
    img_path = tmp_path / "real.png"
    img_path.write_bytes(make_page_png(1760, 500, "user image"))
    out = tmp_path / "user.pdf"
    rc = generate_sample_pdf.main(
        [
            "--variant", "question", "--questions", "4", "--no-cover",
            "--image", str(img_path), "--out", str(out),
        ]
    )
    assert rc == 0
    assert _page_count(out) >= 1
