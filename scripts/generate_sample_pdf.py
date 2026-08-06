#!/usr/bin/env python3
"""
Generate a sample paper PDF with the real layout engine — no database or S3.

Question/answer pages are synthetic placeholder images (app/pdf/sample_data.py)
whose sizes cycle through the layout edge cases — packing, upscaling of narrow
pages, a near-page-filling block, a multi-page block — within the size bounds
the ingestion pipeline guarantees for stored images. The orchestration
mirrors POST /api/generate/paper (app/routes/generate.py), so what this script
renders is what the route would render for the same options.

Intended for visual self-verification of layout changes: generate with --png,
then read the PNGs and inspect the pages (cover, chrome, numbering, packing).

Usage:
  python scripts/generate_sample_pdf.py [options]

Examples:
  python scripts/generate_sample_pdf.py --png
  python scripts/generate_sample_pdf.py --variant question --questions 3 --no-cover
  python scripts/generate_sample_pdf.py --image page1.png --image page2.png --png
"""

import argparse
import sys
from pathlib import Path

# Add repo root (for app.*) and this directory (for pdf_to_images) to the path.
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app.pdf.layout_engine import CoverSpec, LayoutEngine, PageChrome, render_combined
from app.pdf.sample_data import build_sample_blocks, sample_marks
from pdf_to_images import pdf_to_pngs

_DEFAULT_INSTRUCTIONS = (
    "<p>Answer <b>all</b> questions.<br>Show your working clearly.</p>"
)
_DEFAULT_PAGE_HEADER = (
    '<p>Visit <a href="https://www.pillora.com.sg">www.pillora.com.sg</a> for more '
    "learning resources.<br>Join @PilloraSecondary on Telegram to learn together!</p>"
)
_DEFAULT_FOOTER = '<p>Pillora Learning — <a href="https://www.pillora.com.sg">pillora.com.sg</a></p>'
_DEFAULT_BODY = (
    "<p>Dear student,</p>"
    "<p>This is a <b>sample</b> cover letter with <i>rich-text</i> markup and a "
    '<a href="https://www.pillora.com.sg">link</a>, exercising the same body '
    "rendering path as admin-configured covers.</p>"
    "<p>All the best!</p>"
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--variant",
        choices=["question", "answer", "combined"],
        default="combined",
        help="which paper to render (default: combined)",
    )
    parser.add_argument(
        "--questions",
        type=int,
        default=3,
        help="number of sample questions; 3 covers every synthetic page size (default: 3)",
    )
    parser.add_argument(
        "--page-header",
        default=_DEFAULT_PAGE_HEADER,
        help="branding header (rich-text HTML), right-aligned on the top rule of every page",
    )
    parser.add_argument(
        "--instructions",
        default=_DEFAULT_INSTRUCTIONS,
        help="additional instructions (rich-text HTML) below the top rule (question paper only)",
    )
    parser.add_argument(
        "--footer",
        default=_DEFAULT_FOOTER,
        help="footer text (rich-text HTML) on every page",
    )
    parser.add_argument(
        "--cover",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include a cover page per section (default: yes)",
    )
    parser.add_argument("--cover-title", default="Topical Worksheets")
    parser.add_argument("--cover-subtitle1", default="Sample Subject — Algebra")
    parser.add_argument("--cover-subtitle2", default="2025 Prelim")
    parser.add_argument(
        "--cover-body",
        default=_DEFAULT_BODY,
        help="cover letter as rich-text HTML (default exercises <b>/<i>/<a>)",
    )
    parser.add_argument(
        "--image",
        action="append",
        metavar="PATH",
        help="use this image file (repeatable, cycled) instead of synthetic pages",
    )
    parser.add_argument("--out", default="sample_paper.pdf", help="output PDF path")
    parser.add_argument("--png", action="store_true", help="also convert the PDF to PNGs")
    parser.add_argument("--dpi", type=int, default=120, help="PNG resolution with --png (default: 120)")
    return parser


def generate(args) -> bytes:
    """Render PDF bytes for the parsed options. Mirrors generate_paper()."""
    total_marks = sample_marks(args.questions)

    def cover_for(is_questions: bool) -> CoverSpec | None:
        if not args.cover:
            return None
        return CoverSpec(
            title=args.cover_title,
            subtitle1=args.cover_subtitle1,
            subtitle2=args.cover_subtitle2,
            body=args.cover_body,
            total_marks=total_marks,
            is_questions=is_questions,
        )

    def chrome_for(is_questions: bool) -> PageChrome:
        return PageChrome(
            header_text=args.page_header,
            footer_label=args.footer,
            cover=cover_for(is_questions),
        )

    if args.variant == "combined":
        q_blocks, images = build_sample_blocks(args.questions, "question", args.image)
        q_engine = LayoutEngine(fit_width=True, show_credit=True)
        q_plan = q_engine.compute_layout(
            q_blocks,
            additional_instructions=args.instructions,
            chrome=chrome_for(True),
        )
        sections = [(q_engine, q_plan)]
        a_blocks, a_images = build_sample_blocks(args.questions, "answer", args.image)
        if a_blocks:
            images.update(a_images)
            a_engine = LayoutEngine(fit_width=False)
            a_plan = a_engine.compute_layout(a_blocks, chrome=chrome_for(False))
            sections.append((a_engine, a_plan))
        return render_combined(sections, fetch_bytes=images.__getitem__)

    is_question = args.variant == "question"
    blocks, images = build_sample_blocks(args.questions, args.variant, args.image)
    engine = LayoutEngine(fit_width=is_question, show_credit=is_question)
    plan = engine.compute_layout(
        blocks,
        additional_instructions=args.instructions if is_question else "",
        chrome=chrome_for(is_question),
    )
    return engine.render(plan, fetch_bytes=images.__getitem__)


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    pdf = generate(args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf)
    print(f"PDF: {out} ({len(pdf)} bytes)")

    if args.png:
        for path in pdf_to_pngs(out, dpi=args.dpi):
            print(f"PNG: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
