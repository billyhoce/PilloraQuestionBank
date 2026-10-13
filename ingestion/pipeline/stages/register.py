"""``register``: identify the booklet and write ``job.json``.

Records what later stages (and a human) need to know about the input: its sha256
(the fingerprint a rerun compares), size, page count and the hash of the stage
configuration. It also makes the too-large-to-ask check early, so a booklet the
Messages API cannot take is flagged at the first task rather than after a queue
wait; with no committed fixture to fall back on, ``segment`` will then fail with
the same reason.
"""

from __future__ import annotations

import hashlib
import logging

import pymupdf

from ingester.segmenter import fixture_path, too_large_to_ask
from question_extractor.pipeline import paper_name

from .. import artefacts
from ..outcome import Outcome, StageContext, done, failed
from ..registry import CPU, JOB, Stage

log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def run(ctx: StageContext) -> Outcome:
    source = ctx.source
    if not source.is_file():
        return failed(f"{source} does not exist")
    try:
        with pymupdf.open(source) as document:
            page_count = document.page_count
    except Exception as exc:
        return failed(f"{source.name} cannot be opened as a PDF ({exc})")

    size = source.stat().st_size
    paper = paper_name(source)
    refusal = too_large_to_ask(page_count, size, ctx.config.ingest)
    has_fixture = fixture_path(source).exists() or ctx.path(artefacts.SEGMENTS_NAME).exists()
    needs_review = False
    if refusal is not None and not has_fixture:
        log.warning("%s: %s", paper, refusal)
        needs_review = True

    artefacts.write_json(
        ctx.path(artefacts.JOB_NAME),
        {
            "job_id": ctx.job_id,
            "paper": paper,
            "source": source.as_posix(),
            "sha256": _sha256(source),
            "size_bytes": size,
            "page_count": page_count,
            "config_hash": ctx.config.stage_config_hash(),
            "too_large_to_ask": refusal,
            "has_fixture": has_fixture,
        },
    )
    return done(needs_review=needs_review)


STAGE = Stage(
    name="register",
    scope=JOB,
    kind=CPU,
    run=run,
    inputs=lambda ctx: [ctx.source],
    # job.json records the configuration's hash and the too-large check, so all of it counts
    settings=lambda ctx: {"config": ctx.config.stage_config_hash()},
    outputs=lambda ctx: [ctx.path(artefacts.JOB_NAME)],
)
