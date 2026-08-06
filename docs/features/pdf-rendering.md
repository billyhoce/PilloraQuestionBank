# PDF Rendering

**Scope:** The layout engine that turns a resolved question selection into PDF bytes — packing, page
chrome, the cover page, and the rich-text cover body. **Read this before changing
`app/pdf/layout_engine.py` or `app/pdf/cover_body.py`**, and verify changes visually per
[PDF_GENERATION_TESTING.md](../PDF_GENERATION_TESTING.md).

Who calls it and with what: [paper-generation.md](./paper-generation.md). Library: **ReportLab**
drives the per-page cursor and image flow; **Pillow** decodes the stored WebP page images.

## Route behaviour

`POST /api/generate/paper` (`app/routes/generate.py::generate_paper`). `variant="question"` and
`variant="answer"` each generate one paper per call — the frontend calls it twice in separate-PDFs
mode. `variant="combined"` (the frontend default) generates **one PDF** holding the question paper
followed by the answer paper, each section starting on a fresh page and keeping its own layout
rules; the answer section is omitted entirely when no selected question has answer pages. There is no
server-side autofill at generate time: the selection is already resolved before this endpoint is hit.

- Fetches the selected `Question` rows (eager-loading pages + paper), then **re-sorts them into
  `question_ids` order** — a DB `IN` query is unordered.
- Numbers questions `1..N` in **selection order**. The same numbers are used in both variants: an
  answer keeps the number of its question. For `variant="answer"`, a question with no answer pages is
  **skipped**, but its number stays reserved so the remaining answers still match the question paper.
- `additional_instructions` prints only on the question variant (in `combined`, only on the question
  section's first page). The `header_text` branding rides every page of every variant.
- Returns `Response(pdf, media_type="application/pdf")`.

## Layout engine (`app/pdf/layout_engine.py`)

Works in **300-DPI pixel space** (A4 = 2480×3508 px). Stored images are content-only (≤ 1760 px wide
from ingestion); the engine builds the page margins itself.

`LayoutEngine(page_capacity_px, fit_width, show_credit)` — `page_capacity_px` is the usable vertical
budget, the **content band between the header and footer rule lines** (see
[Page chrome](#page-chrome)), not the raw page height. `fit_width` selects the horizontal treatment
per variant:

- **`fit_width=True` (question paper):** each image is scaled (aspect preserved) to a fixed **1760 px
  content width** and drawn **centered** — **360 px margin each side** (1760 + 360 + 360 = 2480). All
  questions therefore render at the same width regardless of stored size. A **59 px (0.5 cm at 300
  DPI) vertical pad** (`_QUESTION_GAP_PX`) sits below any image that has another packed beneath it on
  the **same physical page** — both between consecutive questions (`block_gap_px`) and between the
  stacked pages of one multi-page question (`intra_gap_px`). There is no trailing pad where the next
  image starts a fresh page, and the pad is included when deciding whether that next image fits.
- **`fit_width=False` (answer paper):** each image keeps its **native size** (≤ 1760 px), **flush to
  the 360 px left margin**, with the remaining width as right padding. It never overflows (360 + 1760
  < 2480). A **100 px vertical gap** separates one question's answer block from the next
  (`block_gap_px`); multiple answer pages of the same question stack with no extra gap
  (`intra_gap_px = 0`).

Both variants draw the question number into the **360 px left margin**, right-aligned just left of
the image.

Dataclasses: `Block(label, source_label, pages, page_index)`,
`LayoutPlan(page_count, blocks, header_text, additional_instructions, footer_label, cover)`,
`CoverSpec(title, subtitle1, subtitle2, body, total_marks, is_questions)`, and
`PageChrome(header_text, footer_label, cover)`.

**`compute_layout` returns a complete plan.** The header, footer and cover go *in* as a `PageChrome`
rather than being assigned onto the returned plan by each caller — a plan is never half-built, so
there is no way to forget one and ship a PDF that renders fine but has no header. Omitting `chrome`
gives bare pages, which is what the layout-only tests want.

### Packing — `compute_layout(blocks, additional_instructions="", chrome=None) -> LayoutPlan`

Greedy packing: keep a running cursor and place each block (one question's pages for this variant) on
the current page. A block starts a new page only when its **first page-image** (plus its credit band)
won't fit in the space left — so a multi-page question packs its first page onto the current page
when there is room and **flows its remaining pages onto following pages**, rather than jumping the
whole question to a fresh page. Two short consecutive questions therefore share a page; a block taller
than a whole page still starts wherever its first page fits.

Heights use the variant's scale (`_image_scale`), with a page-tall image clamped to
`page_capacity_px` (`_page_height_px`). The block-start test uses `_first_unit_height_px` (credit band
+ first page) plus `block_gap_px`, and each subsequent page in the block adds `intra_gap_px` before
its fit test — so inter- and intra-question pads are honoured when packing. The
`additional_instructions` band height is reserved on the first page (`_instructions_height_px`); the
`header_text` branding sits in the top margin and consumes no content capacity. The walk mirrors
`render_onto`'s per-image flow, so `page_count` counts multi-page overflow pages too — **render
remains authoritative**.

### Rendering

Rendering is split so sections can share a document:

- `LayoutEngine.render_onto(canvas, plan, fetch_bytes)` draws a plan onto an existing ReportLab
  canvas, ending on a fresh page.
- `LayoutEngine.render(plan, fetch_bytes) -> bytes` wraps it for a standalone PDF.
- Module-level `render_combined(sections, fetch_bytes)` takes `(engine, plan)` pairs and renders them
  into one PDF — how the `combined` variant appends the answer paper.

For each block, `render` places the page image(s) (`fetch_bytes(image_key)` → Pillow → `ImageReader`)
at the variant's scale and left offset, then draws the **number in the left margin**, right-aligned
just left of the image's edge and nudged slightly below the block's top — drawn *after* the image so
it is never covered. Page-breaks happen per image; an image taller than the page is scaled to fit.

In production `fetch_bytes` is `get_image_bytes`; the `variant="answer"` call only fetches answer
bytes and vice-versa, so no image is fetched twice across the two requests. That injection seam is
also what the sample generator fills with an in-memory dict.

### Per-question source credit (`show_credit`)

On the question paper, each block gets a small grey provenance line just above its image —
`source_label`, formatted `[{School}/{Year}/{ExamType}/{paper_number}/Q{original_number}]` (e.g.
`[Bendemeer Secondary School/2024/Prelim/2/Q6]`; `paper_number` is stored bare and rendered as-is).
Drawn at `_CREDIT_FONT_PX = 40` (~11.5 pt at 300 DPI).

`LayoutEngine(show_credit=True)` reserves a fixed band (`_CREDIT_BAND_PX`) in each block's height so
packing and rendering stay in sync, then draws the line and advances the cursor before the image. The
route enables it for the `question` variant (and the `combined` PDF's question section) and leaves it
off for the answer paper. Blocks with an empty `source_label` reserve no band.

## Page chrome

Every page carries branded furniture, drawn by `LayoutEngine._draw_chrome` once per page:

- **Purple rule lines** (`PURPLE ≈ #776687`) near the top (`_HEADER_LINE_Y_PX`) and bottom
  (`_FOOTER_LINE_Y_PX`), inset `_MARGIN_X_PX` each side. The **content band sits between them**
  (`_CONTENT_TOP_PX … _CONTENT_BOTTOM_PX`), which is what `_DEFAULT_CAPACITY_PX` measures.
- **Logo** top-left, with its **visible** bottom edge a small `_LOGO_RULE_GAP_PX` above the header
  rule — sitting on the line, not crossing it. Loaded from `app/pdf/assets/pillora_logo.png`
  (`LOGO_PATH`) via `_load_logo` (cached, aspect-preserved to `_LOGO_W_PX`). The asset is tightly
  cropped to the wordmark, so its bottom padding is ~0; even so, `_load_logo` still measures the
  transparent bottom padding from `getbbox()` and `_draw_chrome` offsets the padded box by it, keeping
  the mark on the line for any future padded asset. The asset is **optional** — if absent or
  unreadable the page renders without it, no error.
- **Header** (`LayoutPlan.header_text`, the branding) drawn **right-aligned on the header rule** by
  `_draw_page_header`. Lines stack **upward** so the *last* line sits on the rule; any web-address
  token (`_URL_TOKEN`) is auto-linked via `canvas.linkURL` to its normalized `https://…` target. An
  empty header draws nothing. The route sets it to the resolved `header_text` — an admin's request
  field when they sent one, otherwise the generation-config preset, which is also what every
  non-admin gets.
- **Footer label** (`LayoutPlan.footer_label`) **flush-left** under the footer rule, plus **`Page
  {n}`** bottom-right. The footer label is the resolved `footer_text` **verbatim**. The same text
  appears on every section — identical footers on the question and answer sections are intentional
  (the old subtitle2-derived `"… Questions"` / `"… Answers"` labels are gone).

Page numbers **restart at 1 for each section** (each `render_onto` call), so in the `combined` PDF the
question and answer papers number independently. `additional_instructions` render on the first content
page, below the header rule (`_draw_instructions`).

## Cover page

When `LayoutPlan.cover` is set (a `CoverSpec`), `render_onto` draws a branded cover as the section's
**first page**, then content starts on page 2 (`_draw_cover` → `_draw_marks_box`). The cover shows:
the logo centered near the top; an editable **title**; **subtitle 1** with `" – Questions"` /
`" – Answers"` appended per variant (`is_questions`); an editable **subtitle 2**; the editable
**letter body**; a **marks box top-right** (`______ / {total}`); a copyright line; and the standard
chrome. A cover-only section (no blocks) stays a single page.

The route computes `total_marks = sum(q.total_marks or 0 …)`, resolves the effective cover values by
role (`_resolve_generation_options`), builds a `CoverSpec` per section (question section
`is_questions=True`, answer section `False`), and includes it unless covers are disabled — admins
only; non-admins always get one. In `combined`, a cover is prepended to **each** section.

### Rich-text cover body (`app/pdf/cover_body.py`)

The letter body is HTML limited to paragraphs plus bold / italic / underline / link. `to_paragraphs`
whitelists exactly that subset — unknown tags are stripped (text kept), all text is escaped, `href`s
are restricted to `http(s)` / `mailto` (a bare `www.` gets `https://` prefixed), and the emitted
markup is always balanced. The result feeds Platypus `Paragraph` objects, which handle word-wrap and
emit **clickable link annotations** (links render blue + underlined). Plain text with no tags is
accepted as the legacy newline-separated format, so older API clients keep working.

## Verifying changes

`scripts/generate_sample_pdf.py` and `scripts/pdf_to_images.py` drive this engine with **no database,
S3 or network**, then rasterize the output for inspection. Any change to the files above must be
verified this way — see [PDF_GENERATION_TESTING.md](../PDF_GENERATION_TESTING.md).
