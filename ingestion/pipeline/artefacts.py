"""Artefacts: the files a stage leaves under its job dir.

A stage's output is a file, never an in-memory hand-off, so the next stage can run
in another process (or, in the webapp, another machine) and a human can open or
edit the file in between. Every write goes to a sibling temp file and is renamed
into place, so a reader never sees half an artefact and a crash leaves the previous
one intact.

Layout under ``<job dir>``, matching ``ingester ingest``'s ``output/<paper>/``::

    options.json                  submit: what the job asks for (``debug``)
    job.json                      register
    segments.json                 segment
    _split/<label>.pdf, split.json  split
    <label>/manifest.json, detections.json   locate
    <label>/pNN.png, review/pNN.webp, _debug/pNN.png   render
    <label>/grid.json, cells.tiff   grid (a table section: column pairs, row bands, OCR cells)
    <label>/ocr.json                ocr (one read per cell of the TIFF)
    <label>/labelled.json, manifest.json, tables.json   questions
    <label>/pNN.png, review/pNN.webp, _debug/pNN.png   render (table route)
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

OPTIONS_NAME = "options.json"
JOB_NAME = "job.json"
SEGMENTS_NAME = "segments.json"
SPLIT_DIR = "_split"
SPLIT_NAME = "split.json"
CELLS_TIFF_NAME = "cells.tiff"
OCR_NAME = "ocr.json"


def write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".tmp")
    partial.write_bytes(data)
    os.replace(partial, path)
    return path


def write_json(path: Path, data: object) -> Path:
    return write_bytes(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def replace_dir(partial: Path, final: Path) -> Path:
    """Swap a fully built folder in for ``final``.

    A directory cannot be renamed over a non-empty one, so the old copy is removed
    first; the window is the two calls, and a crash inside it leaves the finished
    ``partial`` for the stage's rerun to rebuild from.
    """
    if final.exists():
        shutil.rmtree(final)
    os.replace(partial, final)
    return final


def read_options(job_dir: Path) -> dict:
    """The options the job was submitted with; none when nothing was asked for."""
    path = job_dir / OPTIONS_NAME
    return read_json(path) if path.is_file() else {}
