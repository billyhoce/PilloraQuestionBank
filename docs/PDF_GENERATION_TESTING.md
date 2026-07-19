# PDF Generation Testing

Local sample generation and visual self-verification for the paper-generation engine
(see [BACKEND.md](./BACKEND.md) § Paper Generation Engine for the engine itself).

Two scripts drive the real layout engine with **no database, S3, or network** — for eyeballing
layout changes (by a developer or by Claude) without standing up infrastructure:

```
python scripts/generate_sample_pdf.py --png            # combined paper + per-page PNGs
python scripts/pdf_to_images.py some.pdf --dpi 120     # rasterize any PDF to PNGs
```

## Sample generator (`scripts/generate_sample_pdf.py`)

Mirrors `generate_paper()`'s orchestration exactly (same engine/plan/cover wiring per variant)
but feeds it synthetic placeholder pages from `app/pdf/sample_data.py` — deterministic PIL-drawn
images (bordered, labeled, faintly tinted for answers) whose sizes cycle through the layout edge
cases: small blocks that pack together, a narrow page that exercises the upscale-to-1760px path,
a near-page-filling block, a multi-page block that overflows `compute_layout`'s page estimate,
and an answer-less question whose number stays reserved.

All synthetic sizes stay within what the ingestion pipeline can actually produce: every stored
page image is a crop of one 300-DPI A4 scan page, width-capped at 1760 px by
`app/pdf/image_processing.standardize` — so ≤ 1760 px wide and ≤ ~2490 px tall, which always
fits a page's content band. Sizes outside those bounds are deliberately not simulated.

Flags mirror `GeneratePaperRequest` (`--variant`, `--header`/`--footer`, `--cover*`, rich-text
`--cover-body`), plus `--questions N` (default 5 — one of each synthetic size), `--out`,
`--png`/`--dpi`, and repeatable `--image PATH` to substitute real image files. `fetch_bytes` is
an in-memory dict lookup — the same injection seam the route fills with `get_image_bytes`.

## PNG converter (`scripts/pdf_to_images.py`)

`pdf_to_pngs` (PyMuPDF) rasterizes each page to `page_NN.png` in `<pdf-stem>_pages/`. Works on
any PDF — generated samples or the papers in `samples/`. The 120-DPI default keeps A4 pages
~992×1403 px: legible chrome text at a size cheap to inspect (raise `--dpi` to zoom into a
suspect page).

## The self-verification loop

1. Change layout code (`app/pdf/layout_engine.py`, `app/pdf/cover_body.py`, …).
2. `python scripts/generate_sample_pdf.py --png --out <scratch>/sample.pdf`
3. Inspect the PNGs: cover (title/subtitles/marks box/rich-text body), page chrome, question
   numbering, credits, packing, section boundaries.
4. Compare against a pre-change run. Compare **PNGs, not PDF bytes** — ReportLab embeds
   timestamps, so PDFs are never byte-identical; the rendered pixels are deterministic.

**Caveat:** synthetic placeholders can't reveal issues that depend on real scan content
(greyscale backgrounds, near-margin ink, WebP artifacts). For those, feed real pages back in via
`--image` (e.g. pages produced by `pdf_to_images.py` from a paper in `samples/`).

Tests: `tests/test_sample_pdf.py`.
