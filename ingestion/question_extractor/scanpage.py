"""Scanned pages: straightened, with their ruled lines read off the pixels.

A scan declares one page-sized image and no vector paths
(:meth:`PageGeometry.has_page_sized_image`), so a scanned answer table gives the
table reader no rules to read. This module renders the page and finds the rules in
its pixels instead. It hands :mod:`.tables` the same zero-thickness pieces a
born-digital page's paths give it, so everything from ``rule_segments`` on is
shared.

**Borders.** A scanner can leave dark strips where the glass was wider than the
sheet. They would read as long rules and drag the tilt estimate, so ink that
touches the image edge is painted white before anything is measured. No content
comes within 15.8pt of an edge on any sample scan page, so ink that reaches the
edge belongs to the scanner, not the paper. The border is painted over, not cut
off, so the page keeps its size and origin, and a rectangle measured on it still
lands on the PDF page.

**Tilt.** The sample scans tilt by up to 1.55° (Yuying a2 p4), enough for a row
rule to drift 12pt across a 450pt table and leave rows unread. The tilt is the median angle of
the page's long rules (``scan_skew_min_len``), with verticals counted the same
way round as horizontals. The page is rotated by it about its centre, and the
rules are found again on the straightened image, where no sample page tilts more
than 0.054°. That rotation is the only
transform, and it is reported per page (``straightened.angle_deg``): every
rectangle read from a scan is in the straightened page's points.

**Rules.** A morphological opening with a ``scan_rule_min_len`` kernel keeps only
ink that runs that far along one axis, after Otsu's threshold has split ink from
paper. A short closing (``scan_rule_bridge``) mends breaks in a faint rule. Each
surviving component is fitted with a straight centre line and emitted at its mean
position. A component's pixel box would be a tall box on a tilted or bowed rule,
and the table reader would reject that as too thick to be a rule. Thickness is
measured instead, as ink area over length, and held to the digital pages' limit
(``table_rule_max_thickness``): scanned rules measure 0.35-1.18pt (5th to 95th
percentile over 521), the boldest border 1.59pt. Everything thicker is a filled
block or the strokes of a large heading.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import cv2
import numpy as np
import pymupdf

from .config import ExtractConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PixelRule:
    """One rule found in a page image, in points."""

    horizontal: bool
    pos: float
    """Mean across-axis position of the fitted centre line."""
    lo: float
    hi: float
    """Extent along the rule's own axis."""
    angle_deg: float
    """Tilt of the fitted centre line, image y pointing down."""
    thickness: float
    """Mean stroke thickness: ink area over length."""

    @property
    def length(self) -> float:
        return self.hi - self.lo

    def rect(self) -> pymupdf.Rect:
        if self.horizontal:
            return pymupdf.Rect(self.lo, self.pos, self.hi, self.pos)
        return pymupdf.Rect(self.pos, self.lo, self.pos, self.hi)


@dataclass
class ScanPage:
    """A scanned page's straightened image, and what straightening it found."""

    page: int
    """1-based PDF page number."""
    image: np.ndarray
    """Greyscale, borders whitened, rotated by ``angle_deg``, at ``scan_dpi``."""
    angle_deg: float
    """Counter-clockwise rotation applied about the page centre, as the page is
    seen; 0.0 when the page was not rotated."""
    measured_deg: float | None
    """The tilt measured before rotating; ``None`` when no rule was long enough."""
    scale: float
    """Pixels per point."""
    ink_level: int = 127
    """The grey level splitting ink from paper on this page (Otsu's)."""
    rules: list[PixelRule] = field(default_factory=list)
    """The rules found on the straightened image."""
    problems: list[str] = field(default_factory=list)

    def segments(self) -> list[pymupdf.Rect]:
        """The rules as the zero-thickness pieces ``rule_segments`` holds."""
        return [rule.rect() for rule in self.rules]

    def has_ink(self, rect: pymupdf.Rect, min_span: float) -> bool:
        """Whether ``rect`` holds ink: a pixel row and a pixel column each with at
        least ``min_span`` points of it, so scanner specks do not count."""
        h, w = self.image.shape
        x0, y0 = max(int(rect.x0 * self.scale), 0), max(int(rect.y0 * self.scale), 0)
        x1, y1 = min(int(rect.x1 * self.scale), w), min(int(rect.y1 * self.scale), h)
        if x1 <= x0 or y1 <= y0:
            return False
        ink = self.image[y0:y1, x0:x1] <= self.ink_level
        floor = max(1, int(min_span * self.scale))
        return bool((ink.sum(axis=1) >= floor).any() and (ink.sum(axis=0) >= floor).any())

    def crop(
        self, rect: pymupdf.Rect, pad_px: int
    ) -> tuple[np.ndarray, tuple[int, int]] | None:
        """``rect`` (straightened points) cut from the image and padded with white,
        with the image pixel its top-left corner came from.

        Everything lighter than the page's ink threshold is whitened, which is
        what keeps print showing through from the back of the sheet out of an
        empty cell: on Bedok a1 p7 Tesseract read two blank question cells as
        ``fe i. r a aa ...`` from it. ``None`` when the rectangle covers less than
        a pixel either way.
        """
        h, w = self.image.shape
        x0 = max(int(math.ceil(rect.x0 * self.scale)), 0)
        y0 = max(int(math.ceil(rect.y0 * self.scale)), 0)
        x1 = min(int(math.floor(rect.x1 * self.scale)), w)
        y1 = min(int(math.floor(rect.y1 * self.scale)), h)
        if x1 - x0 < 1 or y1 - y0 < 1:
            return None
        cell = self.image[y0:y1, x0:x1].copy()
        cell[cell > self.ink_level] = 255
        padded = cv2.copyMakeBorder(
            cell, pad_px, pad_px, pad_px, pad_px, cv2.BORDER_CONSTANT, value=255
        )
        return padded, (x0, y0)


def read_scan_page(page: pymupdf.Page, config: ExtractConfig) -> ScanPage:
    """Render, whiten the borders, straighten, and find the rules again."""
    scale = config.scan_dpi / 72.0
    gray = _whiten_borders(_render_gray(page, config.scan_dpi))
    measured = _skew(_find_rules(gray, scale, config), config)
    scan = ScanPage(
        page=page.number + 1, image=gray, angle_deg=0.0, measured_deg=measured, scale=scale
    )
    if measured is not None and abs(measured) > config.scan_max_skew_deg:
        scan.problems.append(
            f"the scan measures a {measured:.1f}° tilt, more than "
            f"scan_max_skew_deg ({config.scan_max_skew_deg}°); it was not straightened"
        )
    elif measured:
        scan.image = _rotate(gray, measured)
        scan.angle_deg = measured
    scan.ink_level = int(cv2.threshold(scan.image, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[0])
    scan.rules = _find_rules(scan.image, scale, config)
    return scan


def straightened_image(page: pymupdf.Page, angle_deg: float, config: ExtractConfig) -> np.ndarray:
    """The image :func:`read_scan_page` produced for this page, made again.

    Rendering is deterministic, so the renders redo it from the recorded angle
    rather than every scanned page's image being held until the end of the run.
    """
    gray = _whiten_borders(_render_gray(page, config.scan_dpi))
    return _rotate(gray, angle_deg) if angle_deg else gray


def straightened_document(
    page: pymupdf.Page, angle_deg: float, config: ExtractConfig
) -> pymupdf.Document:
    """A one-page document the size of ``page`` holding its straightened image.

    What the renders draw a scanned page's rectangles on, since those rectangles
    are in the straightened page's points. The caller closes it.
    """
    ok, png = cv2.imencode(".png", straightened_image(page, angle_deg, config))
    doc = pymupdf.open()
    sheet = doc.new_page(width=page.rect.width, height=page.rect.height)
    if ok:
        sheet.insert_image(sheet.rect, stream=png.tobytes())
    return doc


def _render_gray(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[
        :, : pix.width
    ].copy()


def _ink(gray: np.ndarray) -> np.ndarray:
    """Ink as 255 on 0, split from the paper by Otsu's threshold."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return binary


def _whiten_borders(gray: np.ndarray) -> np.ndarray:
    """``gray`` with every ink component touching the image edge painted white."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(_ink(gray), connectivity=8)
    h, w = gray.shape
    touching = [
        i
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_LEFT] == 0
        or stats[i, cv2.CC_STAT_TOP] == 0
        or stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] == w
        or stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] == h
    ]
    if not touching:
        return gray
    out = gray.copy()
    out[np.isin(labels, touching)] = 255
    log.debug("whitened %d border component(s)", len(touching))
    return out


def _rotate(gray: np.ndarray, angle_deg: float) -> np.ndarray:
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_deg, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=255,
    )


def _find_rules(gray: np.ndarray, scale: float, config: ExtractConfig) -> list[PixelRule]:
    """Every horizontal and vertical run of ink at least ``scan_rule_min_len`` long."""
    binary = _ink(gray)
    length = max(int(config.scan_rule_min_len * scale), 3)
    bridge = max(int(round(config.scan_rule_bridge * scale)), 1)
    rules: list[PixelRule] = []
    for horizontal in (True, False):
        shape = (length, 1) if horizontal else (1, length)
        mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, shape))
        shape = (bridge + 1, 1) if horizontal else (1, bridge + 1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, shape))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if (w if horizontal else h) < length:
                continue
            ys, xs = np.nonzero(labels[y : y + h, x : x + w] == i)
            along, across = (xs + x, ys + y) if horizontal else (ys + y, xs + x)
            slope, intercept = np.polyfit(along.astype(float), across.astype(float), 1)
            lo, hi = int(along.min()), int(along.max()) + 1
            thickness = float(area) / (hi - lo) / scale
            if thickness > config.table_rule_max_thickness:
                continue  # a filled block or a heading's strokes, not a hairline
            mid = (lo + hi - 1) / 2.0
            rules.append(
                PixelRule(
                    horizontal=horizontal,
                    pos=float(slope * mid + intercept) / scale,
                    lo=lo / scale,
                    hi=hi / scale,
                    angle_deg=math.degrees(math.atan(slope)),
                    thickness=thickness,
                )
            )
    return rules


def _skew(rules: list[PixelRule], config: ExtractConfig) -> float | None:
    """The page's tilt: the median angle of its long rules, verticals sign-flipped.

    A page turned clockwise tilts its horizontals one way and its verticals the
    other in image coordinates, so flipping the verticals makes both vote alike.
    """
    angles = [
        rule.angle_deg if rule.horizontal else -rule.angle_deg
        for rule in rules
        if rule.length >= config.scan_skew_min_len
    ]
    return float(np.median(angles)) if angles else None
