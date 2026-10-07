"""The proposal: the one JSON document the admin review page reads and edits.

``report`` builds it (``proposal.json``) from what the section stages left: the segment
plan (which answer section belongs to which question section), each section's
``manifest.json`` and split PDF, and the review WebPs the render stages wrote. See
``ingestion/README.md`` ("The proposal") for the shape; this module is the one place
that knows it.

Everything in it is in the **booklet's** terms, so the review page and the cropper
never need the split PDFs: pages are booklet page numbers (the manifest's
``original_page``), images are ``pages/pNN.webp`` at booklet numbering, and rectangles
are PDF points on that booklet page in its original, unstraightened frame.

Rectangles are never dropped. A question's rectangles go under its ``question_rects``;
an answer rectangle goes to the question with the same number, or under
``orphan_answers`` when there is none; so every rectangle of every extracted section's
manifest is in the proposal exactly once.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from ingester.router import EXTRACTED, SectionReport
from ingester.segments import SegmentPlan
from question_extractor.render import REVIEW_SUBDIR, review_filename

from . import artefacts

PAGES_DIR = "pages"


def page_image(page: int) -> str:
    """Job-relative path of a booklet page's review image: ``pages/p07.webp``
    (``p100.webp`` from the hundredth page; the number is at least two digits)."""
    return f"{PAGES_DIR}/{review_filename(page)}"


def unstraighten(rect: tuple[float, float, float, float], angle_deg: float, width: float, height: float):
    """Map a rectangle from a straightened scan's frame back to the page as filed.

    The straightened page is the original rotated counter-clockwise (as seen, y down)
    by ``angle_deg`` about the page centre (``cv2.getRotationMatrix2D``); this rotates
    the four corners the other way and takes their axis-aligned bounding box (a rotated
    rectangle is not an axis-aligned one, and the box is what a crop can use; at the
    <=5 degrees a scan is straightened by it is a few points larger than the original
    on each side).
    """
    x0, y0, x1, y1 = rect
    if not angle_deg:
        return rect
    cx, cy = width / 2.0, height / 2.0
    cos, sin = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    xs, ys = [], []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        dx, dy = x - cx, y - cy
        xs.append(cx + cos * dx - sin * dy)
        ys.append(cy + sin * dx + cos * dy)
    return min(xs), min(ys), max(xs), max(ys)


@dataclass
class _Section:
    """One extracted section as the proposal reads it."""

    report: SectionReport
    manifest: dict
    pdf: Path


def build(
    job_dir: Path,
    plan: SegmentPlan | None,
    split: dict,
    reports: list[SectionReport],
    tolerance: float,
) -> dict:
    """The proposal for a job, copying each review image to ``pages/`` as it goes.

    ``split`` is ``split.json``'s sections/skipped/warnings (see ``report._read_split``);
    ``reports`` are the section rows ``report`` decided; ``tolerance`` is how far (points)
    a rectangle may stick out of its page before that is warned about (it is clipped
    either way).
    """
    warnings: list[str] = []
    by_label = {r.label: r for r in reports}
    entries = {e["label"]: e for e in split["sections"]}
    segments = list(plan.segments) if plan is not None else []

    staging = job_dir / (PAGES_DIR + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    loaded: dict[str, _Section] = {}
    for report in reports:
        if report.status != EXTRACTED:
            continue
        entry = entries[report.label]
        manifest = artefacts.read_json(job_dir / report.label / "manifest.json")
        loaded[report.label] = _Section(
            report=report,
            manifest=manifest,
            pdf=job_dir / artefacts.SPLIT_DIR / entry["file"],
        )

    # Pair by the segment index: "an answer paper takes its question paper's index".
    questions = [s for s in segments if s.kind == "question"]
    answers = [s for s in segments if s.kind == "answer"]
    taken: set[str] = set()
    papers: list[dict] = []
    for q in questions:
        a = next((x for x in answers if x.index == q.index and x.label not in taken), None)
        if a is not None:
            taken.add(a.label)
        if q.label not in loaded and not (a is not None and a.label in loaded):
            continue  # nothing of this paper was extracted: it is in ``unrouted``
        papers.append(_paper(job_dir, staging, q.label, a, loaded, by_label, tolerance))
    for a in answers:  # an answer paper with no question paper of its own
        if a.label in taken or a.label not in loaded:
            continue
        warnings.append(f"{a.label}: answer section has no question section with index {a.index}")
        papers.append(_paper(job_dir, staging, None, a, loaded, by_label, tolerance))

    unrouted = [
        {
            "label": r.label,
            "status": r.status,
            "reason": r.reason,
            "first_page": r.first_page,
            "last_page": r.last_page,
        }
        for r in reports
        if r.status != EXTRACTED
    ]
    artefacts.replace_dir(staging, job_dir / PAGES_DIR)
    return {"papers": papers, "unrouted": unrouted, "warnings": warnings}


def _paper(job_dir, staging, q_label, answer, loaded, by_label, tolerance) -> dict:
    a_label = answer.label if answer is not None else None
    warnings: list[str] = []
    pages: list[dict] = []
    questions: dict[int, dict] = {}
    orphans: list[dict] = []

    if q_label is not None and q_label not in loaded:
        warnings.append(_missing(by_label.get(q_label), q_label))
    if a_label is not None and a_label not in loaded:
        warnings.append(_missing(by_label.get(a_label), a_label))

    for label in (q_label, a_label):
        section = loaded.get(label) if label else None
        if section is None:
            continue
        is_answer = label == a_label
        review_pages = {p["page"]: p for p in section.manifest["pages"]}
        angles = {p["page"]: (p.get("straightened") or {}).get("angle_deg", 0.0) for p in section.manifest["pages"]}
        sizes = _page_sizes(section)

        for page in section.manifest["pages"]:
            local = page["page"]
            booklet = page["original_page"]
            source = job_dir / label / REVIEW_SUBDIR / review_filename(local)
            image = None
            if source.is_file():
                shutil.copyfile(source, staging / review_filename(booklet))
                image = page_image(booklet)
            else:
                warnings.append(f"{label} page {local} (booklet page {booklet}): no review image")
            width, height = sizes.get(local, (None, None))
            pages.append({
                "page": booklet,
                "image": image,
                "width_pt": width,
                "height_pt": height,
                "needs_review": page["needs_review"],
                "review_reason": page["review_reason"],
            })

        for q in section.manifest["questions"]:
            number = q["question_number"]
            rects = []
            flags: list[str] = []
            for rect in q["rects"]:
                local = rect["page"]
                width, height = sizes.get(local, (None, None))
                rects.append(_rect(
                    rect, angles.get(local, 0.0), width, height, tolerance, f"{label} Q{number}", warnings
                ))
                for flag in _rect_flags(rect, review_pages.get(local)):
                    if flag not in flags:
                        flags.append(flag)
            if is_answer:
                target = questions.get(number)
                if target is None:
                    orphans.extend(rects)
                else:
                    target["answer_rects"].extend(rects)
                    target["flags"].extend(f for f in flags if f not in target["flags"])
            else:
                questions[number] = {
                    "number": number, "question_rects": rects, "answer_rects": [], "flags": flags,
                }

    # The answer section's questions were read after the question section's in the loop
    # above, so every question of the paper is known when an answer rectangle looks for it.
    pages.sort(key=lambda p: p["page"])
    return {
        "label": q_label,
        "answer_label": a_label,
        "answer_template": answer.template if answer is not None else None,
        "pages": pages,
        "questions": sorted(questions.values(), key=lambda q: q["number"]),
        "orphan_answers": orphans,
        "warnings": warnings,
    }


def _missing(report: SectionReport | None, label: str) -> str:
    if report is None:
        return f"{label}: not in this job's split"
    return f"{label} was {report.status.replace('_', ' ')}: {report.reason}"


def _page_sizes(section: _Section) -> dict[int, tuple[float, float]]:
    """Each page's size in points as the review image shows it (``page.rect`` applies the
    page's rotation, as the render does), by section-local page number."""
    try:
        with pymupdf.open(section.pdf) as doc:
            return {n + 1: (round(page.rect.width, 2), round(page.rect.height, 2)) for n, page in enumerate(doc)}
    except Exception:  # an unreadable split PDF: the rects keep their numbers, unclipped
        return {}


def _rect(rect, angle, width, height, tolerance, who, warnings) -> dict:
    x0, y0, x1, y1 = rect["x0"], rect["y0"], rect["x1"], rect["y1"]
    if width is not None:
        x0, y0, x1, y1 = unstraighten((x0, y0, x1, y1), angle, width, height)
        clipped = (max(x0, 0.0), max(y0, 0.0), min(x1, width), min(y1, height))
        # How far it stuck out. A straightened scan's box always does by a little (see
        # ``unstraighten``), so only a digital page's overhang is worth a warning.
        out = max(clipped[0] - x0, clipped[1] - y0, x1 - clipped[2], y1 - clipped[3])
        if out > tolerance and not angle:
            warnings.append(f"{who}: rectangle on booklet page {rect['original_page']} sticks out of the page by {out:.1f}pt; clipped")
        x0, y0, x1, y1 = clipped
    return {
        "page": rect["original_page"],
        "x0": round(x0, 2), "y0": round(y0, 2), "x1": round(x1, 2), "y1": round(y1, 2),
    }


def _rect_flags(rect: dict, page: dict | None) -> list[str]:
    flags = []
    if page is not None and page["needs_review"]:
        flags.append(f"page {page['original_page']}: {page['review_reason']}")
    if rect.get("pixel_ink"):
        flags.append("pixel_ink")
    if rect.get("grid_page"):
        flags.append("grid_page")
    return flags
