"""Tunable thresholds for question extraction.

Every magic number the pipeline relies on lives here, so adapting the tool to a
differently formatted paper is a flag change rather than a code change. All
lengths are in PDF points (1/72 inch) unless the name says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractConfig:
    """Thresholds and pads used across the whole pipeline."""

    # --- rendering -------------------------------------------------------
    zoom: float = 3.0
    """Render scale passed to ``pymupdf.Matrix``; 3.0 ≈ 216 dpi."""
    review_zoom: float = 2.0
    """Scale of the clean ``--review`` images; 2.0 ≈ 144 dpi.

    The admin review page shows these under an SVG of the rectangles, so they only
    have to make a candidate's handwriting legible, not to be pixel-exact: a pupil's
    working at 144 dpi stays readable while the image has 4/9 of the pixels of the
    216 dpi render, and these are uploaded with the paper: a page is ~26 KB at 2.0
    on the sample corpus.
    """
    review_webp_quality: int = 80
    """WebP quality of the review images (0-100); 80 keeps pencil and printed
    text edges crisp at a few tens of KB a page (see ``review_zoom``)."""

    # --- running header / footer detection -------------------------------
    furniture_band_frac: float = 0.15
    """Only lines within this fraction of the page top/bottom can be furniture."""
    furniture_min_page_frac: float = 0.5
    """A repeated line must appear on at least this fraction of pages."""
    furniture_min_pages: int = 2
    """...and on at least this many pages, whatever the fraction says."""
    furniture_pad: float = 4.0
    """Clearance left between the furniture and the body band."""
    furniture_key_chars: int = 24
    """Characters of normalised text compared when matching a repeated line.

    A running footer often differs between recto and verso — one side carries
    "[Turn over" and the other does not — which splits its occurrences into two
    counts, each short of the threshold. Comparing a prefix unifies them. Checked
    across the sample corpus: at this length no paper loses body content, while a
    much shorter key starts matching cover-page form fields.
    """
    furniture_tail_frac: float = 0.12
    """A page's last text row this close to the bottom edge may be a footer."""
    furniture_tail_min_pages: int = 3
    """...if the same trailing text appears on at least this many pages.

    Far fewer than the text rule demands, because being the last thing on the page
    and inside the outer margin is strong evidence on its own.
    """
    default_top_margin: float = 40.0
    default_bottom_margin: float = 40.0
    """Body band fallbacks for papers with no repeated header/footer."""

    # --- x_cut / margin calibration --------------------------------------
    cluster_tol: float = 3.0
    """Leading-x values within this distance belong to the same cluster."""
    min_cluster_support: int = 2
    """A cluster needs this many lines before it can be the content column."""
    min_gutter_gap: float = 8.0
    """Required clear space between the gutter and the content column."""
    gutter_search_frac: float = 0.25
    """Bare numbers this far into the page (fraction of width) may be anchors."""
    content_right_pad: float = 6.0
    min_right_margin: float = 12.0
    """Page edge kept clear of the right crop edge."""
    x_cut_fallback_pad: float = 8.0
    """Used as ``content_x - pad`` when no distinct gutter cluster is found."""

    # --- anchors ---------------------------------------------------------
    max_anchor_number: int = 99
    """Reject implausibly large "question numbers"."""
    row_tol: float = 4.0
    """Vertical slack when deciding two lines share a row."""

    # --- question boundaries ---------------------------------------------
    snap_lookback: float = 60.0
    """How far above an anchor to hunt for the real whitespace break."""
    snap_lookahead: float = 4.0
    min_snap_gap: float = 6.0
    """Whitespace narrower than this is not treated as a question break."""
    band_top_pad: float = 3.0
    band_bottom_pad: float = 3.0

    # --- divider rules ---------------------------------------------------
    divider_max_height: float = 2.0
    divider_min_width_frac: float = 0.6
    """A thin fill/stroke at least this wide (fraction of page) is a divider."""

    # --- graph grids ------------------------------------------------------
    grid_rule_max_thickness: float = 2.0
    """A grid rule is a hairline; in the sample papers it is drawn with no width
    at all. Shares its value with ``divider_max_height`` by coincidence, not by
    meaning: this one applies across whichever axis the rule is thin on."""
    grid_rule_min_span_frac: float = 0.3
    """...and runs at least this much of the page along the other axis.

    Well below what a real grid spans (the sample grids cover 0.83 of the width
    and 0.89 of the height), because the test that discriminates is the pitch,
    not the length: keeping the length loose lets a grid printed inside a margin
    still register."""
    grid_min_rules: int = 8
    """Rules needed in *each* family before a page can be a grid.

    Not a tuned number. Across the sample papers the two grid pages carry 91 and
    101 rules in their smaller family and no other page carries more than two, so
    any threshold from 5 to 80 gives the same answer."""
    grid_pitch_tol: float = 0.25
    """A gap this far from the median (as a fraction of it) still counts as even."""
    grid_regular_frac: float = 0.8
    """...and this fraction of the gaps must count, not all of them.

    A graph grid prints a heavier rule every fifth line, drawn over the fine one,
    and the pair reads as a gap of nearly zero."""
    grid_min_coverage_frac: float = 0.5
    """The rules' bounding box must cover this much of the body band.

    A grid is given the whole sheet; a ruled box inside a question is not, and
    widening a crop to the full page for one would throw away the boundary the
    text was going to give it."""

    # --- answer tables (``--table``) ---------------------------------------
    # Measured on the two born-digital table keys in ``samples/`` — the FMS key
    # (``coverpage_formulae_footer_funnyheader_endofpaper`` p22) and the CCHMS
    # key (``coverpage_formulae_numberheader_footer_blankpage_graphgrid`` p21) —
    # and on the synthetic ``samples/answer_tables/`` papers. See ``tables.py``.
    table_rule_max_thickness: float = 2.0
    """A table rule is a hairline: both keys draw theirs as 0.48pt fills. Shared in
    value, not meaning, with ``grid_rule_max_thickness``. A scanned rule's stroke
    measures 0.35-1.18pt (5th to 95th percentile), the boldest 1.59pt (Bedok a2
    p4's border); the thicker ink a scan offers is filled blocks and a heading's
    strokes (``scanpage.py``)."""
    table_rule_pos_tol: float = 1.0
    """Pieces this close across their axis are one rule drawn in pieces.

    Both keys draw each rule cell by cell, and the pieces of one rule share their
    position to the hundredth of a point. The closest two *different* rules come
    is a 14.3pt row (CCHMS 4(a)), so the value only has to beat rounding."""
    table_rule_join_gap: float = 2.0
    """Pieces this close along their axis join into one rule, and a horizontal
    and a vertical rule this close touch.

    Both keys leave 0.5pt between the pieces of a rule (FMS 120.7 -> 121.2). The
    ceiling is the nearest stray ink comes to a cell edge: an underline in an FMS
    answer cell starts 5.2pt inside it, and joining across that gap would turn
    the underline into a row rule."""
    table_edge_min_frac: float = 0.3
    """A vertical rule is a column edge when it runs at least this fraction of the
    tallest vertical in its table.

    Real edges run 1.0 of it (all five FMS edges) or 0.75 (the CCHMS right-hand
    pair, which ends at y=606 while the left pair runs to 777). The verticals of
    the graph grid drawn in FMS 13(iii)'s answer cell run 0.17, and are not
    edges. Anything from 0.2 to 0.7 gives the same answer on both keys."""
    table_row_min_cover: float = 0.95
    """A horizontal rule is a row boundary of a column pair when it covers at
    least this fraction of the pair's width, question column included.

    Row rules cover 1.0 once their pieces are joined. The widest rule-like ink
    inside a cell is an FMS underline covering 0.75 of its pair (179 of 239pt,
    though 0.93 of its answer column — which is why the test is on the pair) and
    the FMS graph grid's lines cover 0.51."""
    table_min_row_height: float = 3.0
    """Two row rules closer than this are one double rule, not a row. The
    shortest real row in either key is 14.3pt."""
    table_straddle_frac: float = 0.3
    """A line crosses a row rule when at least this fraction of its height lies
    on *each* side of the rule.

    A line crossing a rule means the rules are not where the rows are, which is
    the one wrong reading that would merge or split answers silently. A fraction
    and not a distance, because a glyph's box overstates it: the CCHMS 8(b) cell
    sets 19.2pt-tall parentheses whose box reaches 2.08pt above its row rule,
    0.11 of their height. The closest text comes to any long rule in either key
    is 0.24 of its height (CCHMS 12(c) against the left pair's y=578 rule); a
    rule through the middle of a line is 0.5."""

    table_open_edge_min_frac: float = 0.5
    """An undrawn outer edge is inferred where at least this fraction of a table's
    row rules (and two at the least) run past its outermost edge and end together.

    The scanned key with no right border ends 2 of 3 to 6 of 6 of its row rules
    together on every page, within 3.1pt (p4: 407.8-410.9). No table with a
    border has its row rules run past it, except tables drawn inside an answer
    cell (Bedok a1 p4, Yuying a1 p2), which are dropped as nested anyway."""
    table_label_min_frac: float = 0.5
    """With a layout, a table is an answer table only when at least this fraction
    of its non-empty question cells open with a question number or a part label.

    Every answer table in the samples scores 0.8 or more, the lowest being a
    10-row Yuying page whose misses are its ``Qn`` header (OCR'd ``n``) and an
    ``l(a)``. The non-answer table they offer, Bedok a2 p1's ``Year | Level``
    box, has no question cell at all. "Most" sits between."""
    table_cell_inset: float = 2.0
    """Points a cell is cut inside its rules wherever its contents are read: the
    question cell OCR reads, and the answer area tested for ink.

    Measured on Yuying's question cells: at 2pt every label read, while 3.5pt
    clipped the glyphs of labels set close to the rule (``11(a)`` became
    ``1iqajuly``). A rule is at most 2pt thick (``table_rule_max_thickness``),
    half of it either side of its position."""
    table_max_number_step: int = 1
    """Question numbers down a section rise by at most this much from one question
    to the next; a larger step means a question was lost, and is flagged. Every
    sample key numbers its questions without a gap but one: the FMS key prints
    no row for its Q6, which is what a reviewer needs to be told."""

    # --- scanned answer tables (``--table`` on a scan) ----------------------
    # Measured on the five scanned table sections in ``samples/s4_a_math/``: Bedok
    # View a1/a2 and Yuying a1/a2 (200 dpi page images) and the
    # ``coverpage_formulae_blankpageinmiddle_endofpaper`` key (300 dpi). See
    # ``scanpage.py``.
    scan_dpi: int = 300
    """Resolution a scanned page is rendered at. Straightening, line finding and
    OCR all work on this one image. It is at or above every sample scan's own
    resolution, and it is the resolution Tesseract is trained for."""
    scan_rule_min_len: float = 25.0
    """Ink must run at least this far along one axis to be read as a rule.

    Longer than any glyph, so text, digits and most of the maths fall away, while
    the shortest real table edge — the side of a one-line row — is a single long
    vertical across several rows. Fraction bars and underlines survive, and the
    table reader already rejects those."""
    scan_rule_bridge: float = 1.5
    """Breaks this short along a rule are closed before it is measured, so a faint
    or dotted scanned rule is read whole."""
    scan_skew_min_len: float = 150.0
    """Only rules at least this long measure a page's tilt: long enough that a
    fraction bar or underline cannot vote, and every sample table has several."""
    scan_max_skew_deg: float = 5.0
    """A measured tilt above this is not trusted, and the page is flagged rather
    than rotated. The steepest sample page tilts 1.55° (Yuying a2 p4); a tilt much past
    2° breaks a hairline rule into pieces shorter than ``scan_rule_min_len``, so a
    larger reading comes from a few stray strokes, not from the table."""
    scan_rule_pos_tol: float = 3.0
    """``table_rule_pos_tol`` on a scanned page.

    A scanned rule is a few pixels thick and slightly bowed, so the pieces of one
    rule found either side of a break sit up to 1.3pt apart across their axis,
    where a born-digital key's agree to the hundredth of a point. The closest
    two different rules come is still the 14.3pt row of the digital keys."""

    # --- OCR of scanned question cells (``ocr.py``) ------------------------
    ocr_image: str = "pillora-tesseract"
    """The Tesseract image the root ``docker-compose.yml`` builds (``docker compose build
    tesseract``): Tesseract 5.3.0 with the English model."""
    ocr_psm: int = 6
    """Tesseract's page segmentation mode for one cell: a block of text.

    Compared with 7 (a single line) over the 131 question cells of the five
    scanned sections, the two read 122 alike. Of the other nine, 7 invented a
    ``7`` or an ``a`` in eight blank cells, and read nothing in the old scan's p5
    cell holding ``7(ii)`` and ``7(iii)``, which 6 read as the two lines they are,
    so the two-label check could flag the missing row rule."""
    ocr_whitelist: str = "0123456789()abcdefghijklmnopqrstuvwxyz."
    """Every character a question label such as ``12(a)(ii)`` holds, and no
    capital or punctuation a stray mark could become. Part labels need the
    lower-case letters, so a ``1`` can still read as ``l`` (Yuying's ``l(a)``);
    the row grouping repairs that (``tablequestions.py``)."""
    ocr_pad: int = 12
    """White pixels added round each crop. Tesseract misreads a glyph that
    touches the image edge."""
    ocr_timeout_s: float = 300.0
    """Seconds the one container run per section may take. All 131 scanned cells
    of the samples read in 0.8s, most of it the container's start-up."""

    # --- figures ---------------------------------------------------------
    figure_min_overlap: float = 0.25
    """Fraction of a figure's height that must fall inside the band."""
    figure_max_area_frac: float = 0.9
    """Ignore boxes this close to page-sized (background fills)."""
    min_figure_span: float = 4.0
    """Boxes smaller than this in both directions are glyph strokes, not figures."""

    # --- crop trimming ----------------------------------------------------
    trim_crops: bool = True
    """Trim whitespace off each crop once the boundaries have been decided."""
    crop_pad: float = 2.0
    """Ink clearance left on all four sides of a trimmed crop."""
    trim_luminance: int = 250
    """Grey level below which a pixel counts as ink.

    Deliberately near-white. At a mid-grey threshold a pale grid or a lightly
    shaded answer box reads as whitespace and gets trimmed away; at this level
    only genuinely blank paper does, which still strips the white padding some
    image bounding boxes carry.
    """
    trim_pixel_fallback: bool = True
    """Let rendered pixels supply the ink box when a page's geometry is blind.

    A scanned paper declares one page-sized image and no vector paths, and
    ``collect_figures`` discards that box as a background fill — rightly, since it
    says nothing about where on the page the ink is. What is left for the trim is
    the text layer alone, which on a scan sees the OCR'd words and none of the
    drawn diagram. On the sample scan's p13 that pulled the top edge of Q9 down to
    the diagram's own label ``S`` and clipped 12pt off the circle above it.

    The trigger is that same page-sized image (``figure_max_area_frac``), not the
    weaker "this page has no figures": triggering on the weaker test regresses the
    born-digital papers, snapping the real paper's p7 Q12 top edge 15pt onto a
    divider rule the geometry pass had deliberately set aside.
    """
    trim_min_ink_span: float = 1.5
    """Ink a pixel row or column needs before the fallback counts it, in points.

    Without a floor the scan's own noise is ink. Measured on the sample scan and
    the false positives an unfiltered scan produced:

    ==================================  ==================
    p6 scanner speck, 31.7pt too high   2px  = 0.67pt
    p17/p19 gutter sliver, 12pt too far 1-3px = 0.33-1.0pt
    p13 arc, first row                  5px  = 1.67pt
    p13 arc, five rows in               40-80px
    ==================================  ==================

    Sweeping the floor over those pages, the top edge found (pt):

    ==========  ====  ====  ====  ====  ====  ====  ====
    min_span    0.0   0.5   1.0   1.5   2.0   3.0   4.0
    p13 arc     86.5  86.5  86.5  86.5  86.9  88.2  88.2
    p6 speck    43.3  43.3  75.3  75.3  75.7  75.7  75.7
    ==========  ====  ====  ====  ====  ====  ====  ====

    (p13's arc really starts at 86.5, p6's text at 75.0.) Anything from 1.0 to 3.0
    rejects the speck and keeps the arc; this sits in the middle. The floor need
    not find the arc's very first row — ``crop_pad`` absorbs a few thin ones.

    The floor does not reject a *stroke* of the gutter number that crosses the
    cut, which is why ``trim_gutter_inset`` exists as well: it counts ink along a
    column, and a digit has plenty of that.
    """
    trim_gutter_inset: float = 2.0
    """Points right of the crop's left edge the scanned-page pixel scan starts.

    The scan runs from the crop's left edge, which is ``x_cut``, and a question
    number printed against that cut can spill a fraction of a point past it. Such
    a sliver is one pixel column wide at ``zoom=3`` but carries the digit's full
    height of ink, so ``trim_min_ink_span`` — which measures ink *along* the
    column — passes it, and the left edge stays pinned on the cut with nothing
    trimmed. On the sample scan's p15 the ``0`` of ``10`` runs 0.77pt past a cut
    of 71.5 and did exactly that.

    Measured over that paper's 17 question pages: the gutter number reaches past
    the cut on one of them, by 0.77pt, and the nearest any content ink comes to
    the cut is 7.93pt (p12; the rest sit 9-15pt clear). This value is under a
    third of that margin and over twice the worst overhang. It is clamped to
    ``content_x`` so it can never reach into the content column on a paper whose
    gutter is tighter, and it applies only to the pixel fallback: the text layer
    is unioned in whole, so a word inside the inset is still seen.
    """

    # --- non-question pages ----------------------------------------------
    blank_page_patterns: tuple[str, ...] = (
        r"blank\s*page",
        r"intentionally\s+left\s+blank",
        r"no\s+questions?\s+on\s+this\s+page",
    )
    """A page whose only text matches one of these carries no question."""
    blank_page_max_chars: int = 80
    """...and is this short, so a question that mentions a blank page survives."""
    blank_page_marker_frac: float = 0.5
    """...and the marker must be this much of the text, not an aside within it."""

    # --- end of paper ------------------------------------------------------
    end_of_paper_patterns: tuple[str, ...] = (r"end\s*of\s*(?:the\s*)?paper",)
    """A short line matching one of these ends the paper. Empty disables the check.

    ``\\s*`` rather than ``\\s+`` because OCR loses the space: one sample paper
    prints ``--- End ofPaper -:``.
    """
    end_of_paper_max_chars: int = 40
    """...and the line must be no longer than this.

    A sentence that mentions the end of the paper is not the marker. Every marker
    in the sample corpus is 18 characters or fewer, across 15 distinct spellings
    from ``END OF PAPER`` to ``~ End of Paper ~``.
    """
