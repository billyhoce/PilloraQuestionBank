"""Task fingerprints: what a task's artefacts were made from.

A fingerprint is the sha256 (hex, 64 characters: the webapp's ``ingest_task.fingerprint``
is a ``VARCHAR(64)``) of a stage's name and code ``version``, the content of every file it
reads, the slice of configuration and the options it reads. Each stage declares those on
its :class:`~pipeline.registry.Stage` (``inputs``, ``settings``, ``outputs``); this module
only hashes them.

The store records a ``done`` task's fingerprint. Two things use it:

* the runner, before running a claimed task: a fingerprint equal to the recorded one with
  the declared outputs present means the artefacts are already what this run would write,
  so the task completes without running;
* the runner, when a run starts (:meth:`Runner.revalidate`): a ``done`` task whose
  fingerprint no longer matches, or whose outputs are gone (a scratch folder rebuilt after
  a restart), is stale, and so is everything downstream of it.

What is deliberately not in a fingerprint: ``ExtractConfig.ocr_command`` (where Tesseract
runs, not how it reads; see ``PipelineConfig.extract_settings``), the scheduling knobs, the
job's ``force`` option (it changes whether the model is asked, not what a given plan makes
of the file) and a stage's own outputs (they are what is being vouched for). A directory
output is checked for existing, not for content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import artefacts
from .outcome import StageContext
from .registry import Stage

_CHUNK = 1024 * 1024
MISSING = "-"


def file_digest(path: Path) -> str:
    """sha256 of a file's bytes; of a folder, of its files' relative names and digests;
    :data:`MISSING` for a path that does not exist."""
    if path.is_dir():
        digest = hashlib.sha256()
        for entry in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(entry.relative_to(path).as_posix().encode("utf-8"))
            digest.update(file_digest(entry).encode("ascii"))
        return digest.hexdigest()
    if not path.is_file():
        return MISSING
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _key(ctx: StageContext, item: Path) -> str:
    try:
        return item.relative_to(ctx.job_dir).as_posix()
    except ValueError:
        return "source"  # the booklet PDF: its folder differs between workers, its content does not


def compute(stage: Stage, ctx: StageContext) -> str:
    """The fingerprint ``stage`` would give a task run with ``ctx`` now."""
    inputs: dict[str, str] = {}
    for item in stage.inputs(ctx):
        if isinstance(item, Path):
            inputs[_key(ctx, item)] = file_digest(item)
        else:
            inputs[item] = ""
    payload = {
        "stage": stage.name,
        "version": stage.version,
        "inputs": inputs,
        "settings": stage.settings(ctx),
    }
    text = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def outputs_exist(stage: Stage, ctx: StageContext) -> bool:
    return all(path.exists() for path in stage.outputs(ctx))


# --- helpers the stages declare their inputs and settings with --------------------------

def source_digest(ctx: StageContext) -> str:
    """The booklet's sha256: ``register``'s record of it in ``job.json`` when there is one
    (reading the PDF again for every task would be wasted), else hashed now."""
    path = ctx.path(artefacts.JOB_NAME)
    if path.is_file():
        try:
            return str(artefacts.read_json(path)["sha256"])
        except (ValueError, KeyError):
            pass
    return file_digest(ctx.source)


def source_input(ctx: StageContext) -> str:
    return "source:" + source_digest(ctx)


def plan_inputs(ctx: StageContext) -> list[Path]:
    """What a section stage reads of its section, besides its own predecessors' output:
    the plan, the split's page map and the section's split PDF."""
    split = ctx.path(artefacts.SPLIT_DIR)
    return [
        ctx.path(artefacts.SEGMENTS_NAME),
        split / artefacts.SPLIT_NAME,
        split / f"{ctx.section}.pdf",
    ]


def ingest_settings(ctx: StageContext) -> dict:
    from dataclasses import asdict

    return asdict(ctx.config.ingest)


def extract_settings(ctx: StageContext) -> dict:
    return ctx.config.extract_settings()


def render_settings(ctx: StageContext) -> dict:
    """The extract settings and whether the job asked for the debug renders."""
    return {"extract": extract_settings(ctx), "debug": ctx.debug}

