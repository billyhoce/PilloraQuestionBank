"""Rasterise a page once, then draw on the pixels.

Every output of a run (the annotated ``pNN.png``, the ``--debug`` render, the
``--review`` image) shows the same page, so its pixels are produced once by
:func:`rasterise_page` and each annotated output is that pixmap with an overlay
composited onto it. PyMuPDF has no way to draw on a pixmap, so the overlay is the
annotations drawn as vectors on a blank page of the same size, rasterised with an
alpha channel at the same zoom (:func:`draw_on`). That blank page is cheap; the
page's own content, its text and scanned images, is never rasterised twice.

The composite is ``out = floor(under * (255 - alpha) / 255) + over`` (the overlay's
colour is premultiplied), so lines, fills and text come out as they did when drawn
on the page itself, to within a level or two in a channel: the overlay's 8-bit alpha
and premultiplied colour are rounded once there and once more here. Opaque marks
(the red rectangles) land within one level; translucent fills (the debug view's
12% shading) can be two off in a few thousand pixels of a page. Floor rather than
round because it matched MuPDF's own result best on the sample corpus.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pymupdf

Draw = Callable[[pymupdf.Page], None]
"""Draws one page's annotations onto a blank page of the page's size."""


def rasterise_page(page: pymupdf.Page, zoom: float) -> pymupdf.Pixmap:
    """The page as it prints, with nothing drawn on it, at ``zoom`` (3.0 is ~216 dpi)."""
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))


def draw_on(pixmap: pymupdf.Pixmap, page: pymupdf.Page, zoom: float, draw: Draw) -> pymupdf.Pixmap:
    """A copy of ``pixmap`` (``page`` rasterised at ``zoom``) with ``draw``'s marks on it."""
    scratch = pymupdf.open()
    try:
        blank = scratch.new_page(width=page.rect.width, height=page.rect.height)
        draw(blank)
        overlay = blank.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    finally:
        scratch.close()
    return _composite(pixmap, overlay)


def _composite(under: pymupdf.Pixmap, over: pymupdf.Pixmap) -> pymupdf.Pixmap:
    base = _samples(under).astype(np.int32)
    top = _samples(over).astype(np.int32)
    alpha = top[..., 3:4]
    out = np.clip(base * (255 - alpha) // 255 + top[..., :3], 0, 255).astype(np.uint8)
    return pymupdf.Pixmap(pymupdf.csRGB, under.width, under.height, out.tobytes(), False)


def _samples(pixmap: pymupdf.Pixmap) -> np.ndarray:
    rows = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.stride)
    return rows[:, : pixmap.width * pixmap.n].reshape(pixmap.height, pixmap.width, pixmap.n)
