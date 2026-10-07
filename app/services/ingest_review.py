"""The review page's read side: a job's proposal with page-image URLs, and the page-range
hand-off to the manual import flow."""

import math
from typing import Any

import fitz  # PyMuPDF
from question_extractor.config import ExtractConfig

from app.models.orm import IngestJob
from app.services.ingest_jobs import InvalidPdfError, job_prefix
from app.storage.object_store import ObjectStore

# Review images are rendered at the ingestion config's ``review_zoom`` (points -> pixels).
# This is the one place the webapp turns that into pixel sizes; the SPA only reads them.
REVIEW_ZOOM = ExtractConfig().review_zoom
REVIEW_URL_TTL = 3600


class NoProposalError(Exception):
    pass


class PageRangeError(ValueError):
    pass


class ProposalEditError(ValueError):
    """An edited proposal that breaks a rule; the message is shown to the admin as is."""


def pixel_size(width_pt: float, height_pt: float) -> tuple[int, int]:
    return round(width_pt * REVIEW_ZOOM), round(height_pt * REVIEW_ZOOM)


def build_review(job: IngestJob, store: ObjectStore) -> dict[str, Any]:
    """The edited proposal if there is one, else the generated one, each page given a presigned
    ``url`` and its ``width_px`` x ``height_px``. A page whose image is missing keeps ``url`` null."""
    proposal = job.proposal_edited if job.proposal_edited is not None else job.proposal
    if proposal is None:
        raise NoProposalError()
    prefix = job_prefix(job.id)
    papers = []
    for paper in proposal.get("papers", []):
        pages = []
        for page in paper.get("pages", []):
            width_px, height_px = pixel_size(page["width_pt"], page["height_pt"])
            image = page.get("image")
            pages.append(
                {
                    **page,
                    "url": store.presign(prefix + image, REVIEW_URL_TTL) if image else None,
                    "width_px": width_px,
                    "height_px": height_px,
                }
            )
        papers.append({**paper, "pages": pages})
    return {
        "job_id": str(job.id),
        "filename": job.filename,
        "status": job.status,
        "edited": job.proposal_edited is not None,
        "page_count": job.page_count,
        "review_zoom": REVIEW_ZOOM,
        "proposal": {**proposal, "papers": papers},
    }


def extract_page_range(pdf_bytes: bytes, first_page: int, last_page: int) -> bytes:
    """A new PDF of booklet pages ``first_page``..``last_page`` (1-based, inclusive)."""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as src:
            if not 1 <= first_page <= last_page <= src.page_count:
                raise PageRangeError(f"Pages must be within 1 and {src.page_count}")
            with fitz.open() as out:
                out.insert_pdf(src, from_page=first_page - 1, to_page=last_page - 1)
                return out.tobytes()
    except PageRangeError:
        raise
    except Exception as e:
        raise InvalidPdfError("The source PDF could not be read") from e


_RECT_KEYS = {"page", "x0", "y0", "x1", "y1"}
_QUESTION_KEYS = {"number", "question_rects", "answer_rects", "flags"}
_PAPER_KEYS = {"questions", "orphan_answers"}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _check_rect(rect: Any, pages: dict[int, dict], where: str) -> dict:
    if not isinstance(rect, dict) or set(rect) != _RECT_KEYS:
        raise ProposalEditError(f"{where}: a rectangle needs exactly page, x0, y0, x1 and y1")
    page = rect["page"]
    if isinstance(page, bool) or not isinstance(page, int) or page not in pages:
        raise ProposalEditError(f"{where}: page {page} is not one of this paper's pages")
    if not all(_is_number(rect[k]) for k in ("x0", "y0", "x1", "y1")):
        raise ProposalEditError(f"{where}: rectangle coordinates must be numbers")
    size = pages[page]
    if not (rect["x0"] < rect["x1"] and rect["y0"] < rect["y1"]):
        raise ProposalEditError(f"{where}: a rectangle on page {page} has no area (needs x0 < x1 and y0 < y1)")
    if rect["x0"] < 0 or rect["y0"] < 0 or rect["x1"] > size["width_pt"] or rect["y1"] > size["height_pt"]:
        raise ProposalEditError(
            f"{where}: a rectangle lies outside page {page} "
            f"(0-{size['width_pt']} x 0-{size['height_pt']} points)"
        )
    return {k: rect[k] for k in ("page", "x0", "y0", "x1", "y1")}


def _check_paper(edit: Any, original: dict, i: int) -> dict:
    where = f"Paper {i + 1}"
    if not isinstance(edit, dict) or set(edit) != _PAPER_KEYS:
        raise ProposalEditError(f"{where}: expected exactly questions and orphan_answers")
    if not isinstance(edit["questions"], list) or not isinstance(edit["orphan_answers"], list):
        raise ProposalEditError(f"{where}: questions and orphan_answers must be lists")
    pages = {p["page"]: p for p in original.get("pages", [])}
    questions, seen = [], set()
    for q in edit["questions"]:
        if not isinstance(q, dict) or set(q) != _QUESTION_KEYS:
            raise ProposalEditError(f"{where}: a question needs exactly number, question_rects, answer_rects and flags")
        number = q["number"]
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ProposalEditError(f"{where}: a question number must be a positive whole number")
        if number in seen:
            raise ProposalEditError(f"{where}: question number {number} is used more than once")
        seen.add(number)
        qwhere = f"{where}, question {number}"
        if not isinstance(q["question_rects"], list) or not isinstance(q["answer_rects"], list):
            raise ProposalEditError(f"{qwhere}: rectangles must be lists")
        if not q["question_rects"]:
            raise ProposalEditError(f"{qwhere}: a question needs at least one rectangle")
        if not isinstance(q["flags"], list) or not all(isinstance(f, str) for f in q["flags"]):
            raise ProposalEditError(f"{qwhere}: flags must be a list of text")
        questions.append(
            {
                "number": number,
                "question_rects": [_check_rect(r, pages, qwhere) for r in q["question_rects"]],
                "answer_rects": [_check_rect(r, pages, qwhere) for r in q["answer_rects"]],
                "flags": list(q["flags"]),
            }
        )
    orphans = [_check_rect(r, pages, f"{where}, unmatched answers") for r in edit["orphan_answers"]]
    return {**original, "questions": questions, "orphan_answers": orphans}


def save_edited_proposal(job: IngestJob, body: Any) -> None:
    """Validate and store the admin's edit. Only each paper's ``questions`` and ``orphan_answers``
    are editable: they are merged onto the *original* proposal server-side, so pages (images,
    sizes), labels, unrouted sections and warnings can never be rewritten by the client. Raises
    ``NoProposalError`` or ``ProposalEditError``."""
    if job.proposal is None:
        raise NoProposalError()
    originals = job.proposal.get("papers", [])
    papers = body.get("papers") if isinstance(body, dict) and set(body) == {"papers"} else None
    if not isinstance(papers, list) or len(papers) != len(originals):
        raise ProposalEditError(f"Expected edits for exactly {len(originals)} paper(s)")
    job.proposal_edited = {
        **job.proposal,
        "papers": [_check_paper(p, o, i) for i, (p, o) in enumerate(zip(papers, originals))],
    }
