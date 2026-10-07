"""The review page's read side: a job's proposal with page-image URLs, and the page-range
hand-off to the manual import flow."""

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
