"""The proposal: the one JSON document the admin review page reads and edits.

``report`` builds it (``proposal.json``) from what the section stages left: the segment
plan (which answer section belongs to which question section), each section's
``manifest.json`` and split PDF, and the review WebPs the render stages wrote. This
module is the one place that knows its shape (at the end of this docstring); the
behaviour is in docs/features/ingestion-pipeline.md.

Everything in it is in the **booklet's** terms, so the review page and the cropper
never need the split PDFs: pages are booklet page numbers (the manifest's
``original_page``), images are ``pages/pNN.webp`` at booklet numbering, and rectangles
are PDF points on that booklet page, in the frame its review image shows: the page as
filed, or for a straightened scan the page rotated by its ``straightened_deg``.

Rectangles are never dropped. A question's rectangles go under its ``question_rects``;
an answer rectangle goes to the question with the same number, or under
``orphan_answers`` when there is none (in an answer-only paper there is no question to
match, so each answer number becomes a question of its own); so every rectangle of every extracted section's
manifest is in the proposal exactly once.

A paper has a ``role``. ``question`` is the usual paper (a question section, usually with
its answer section). ``answer_only`` is an answer section with no question section of its
own, such as answers uploaded apart from the questions: its answer rectangles keep their
question numbers, as questions with empty ``question_rects``, so a later step can attach
them to the question paper they belong to. A question section with no answer section is
flagged by a warning.

Shape::

    {"papers": [{
        "label": "q1", "role": "question", "answer_label": "a1", "answer_template": "table",
        "pages": [{"page": 7, "image": "pages/p07.webp", "width_pt": 595.3, "height_pt": 841.9,
                   "straightened_deg": null, "needs_review": false, "review_reason": null}],
        "questions": [{"number": 1,
                       "question_rects": [{"page": 7, "x0": 72.0, "y0": 100.0, "x1": 523.0, "y1": 160.0}],
                       "answer_rects": [{"page": 23, "x0": 72.0, "y0": 100.0, "x1": 290.0, "y1": 160.0}],
                       "flags": []}],
        "orphan_answers": [{"page": 23, "x0": ..., "y0": ..., "x1": ..., "y1": ...}],
        "warnings": []}],
     "unrouted": [{"label": "a2", "status": "not_routed", "reason": "...",
                   "first_page": 31, "last_page": 36}],
     "warnings": []}

- Pairing: a question section and the answer section with the same segment ``index``
  form one paper. ``answer_label`` is null when there is no such answer section;
  ``answer_template`` is that section's template.
- Pages: the question and answer sections' rendered pages, each once, sorted by booklet
  page. ``width_pt``/``height_pt`` are the size as the review image shows it (rotation
  applied); the image is ``review_zoom`` times that in pixels. ``image`` is null (with a
  paper warning) if the WebP could not be written.
- Straightened scans: a scanned page that was straightened has ``straightened_deg``, the
  rotation (counter-clockwise as seen, about the page centre, the page keeping its size)
  its review image and every rectangle on it were made after; a cropper rotates the page
  as filed by it first. ``null`` for a page in its own frame; a proposal from before the
  key existed has every rectangle in the page's own frame.
- Flags: per question, without repetition, ``page N: <reason>`` for each flagged page it
  touches (answer pages' reasons go to the question they answer), ``pixel_ink`` and
  ``grid_page``.
- Unrouted: every section not extracted, with its reason and booklet page range. A question
  section not extracted whose answer section was still gets a paper with no ``questions``
  and the answers in ``orphan_answers``. An answer-only upload is a paper with
  ``label: null``. A paper none of whose sections was extracted is omitted. A proposal
  without ``role`` is a ``question`` paper.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from ingester.router import EXTRACTED, SectionReport
from ingester.segments import SegmentPlan, pair_segments
from question_extractor.render import REVIEW_SUBDIR, review_filename

from . import artefacts

PAGES_DIR = "pages"
ROLE_QUESTION = "question"
ROLE_ANSWER_ONLY = "answer_only"


def page_image(page: int) -> str:
    """Job-relative path of a booklet page's review image: ``pages/p07.webp``
    (``p100.webp`` from the hundredth page; the number is at least two digits)."""
    return f"{PAGES_DIR}/{review_filename(page)}"


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
    papers: list[dict] = []
    for q, a in pair_segments(segments):
        if q is not None:
            if a is None and q.label in loaded:
                warnings.append(f"{q.label}: question section has no answer section with index {q.index}")
            if q.label not in loaded and not (a is not None and a.label in loaded):
                continue  # nothing of this paper was extracted: it is in ``unrouted``
            papers.append(_paper(job_dir, staging, q.label, a, loaded, by_label, tolerance))
        else:  # an answer paper with no question paper of its own
            if a.label not in loaded:
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
                "straightened_deg": angles.get(local) or None,
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
                rects.append(_rect(rect, width, height, tolerance, f"{label} Q{number}", warnings))
                for flag in _rect_flags(rect, review_pages.get(local)):
                    if flag not in flags:
                        flags.append(flag)
            if is_answer:
                target = questions.get(number)
                if target is None and q_label is None:
                    # An answer-only paper: the answers are the questions, kept by number.
                    questions[number] = {
                        "number": number, "question_rects": [], "answer_rects": rects, "flags": flags,
                    }
                elif target is None:
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
    if a_label is None:
        warnings.append(f"{q_label}: no answer section in this booklet; the paper has question pages only")
    if q_label is None:
        warnings.append(f"{a_label}: answer-only paper; its answers keep their question numbers and need attaching to a question paper")
    return {
        "label": q_label,
        "role": ROLE_QUESTION if q_label is not None else ROLE_ANSWER_ONLY,
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


def _rect(rect, width, height, tolerance, who, warnings) -> dict:
    x0, y0, x1, y1 = rect["x0"], rect["y0"], rect["x1"], rect["y1"]
    if width is not None:
        # A straightened page keeps its size, so its rectangles are clipped to it alike.
        clipped = (max(x0, 0.0), max(y0, 0.0), min(x1, width), min(y1, height))
        out = max(clipped[0] - x0, clipped[1] - y0, x1 - clipped[2], y1 - clipped[3])
        if out > tolerance:
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
