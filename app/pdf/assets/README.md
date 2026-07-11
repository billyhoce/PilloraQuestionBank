# PDF generation assets

Drop `pillora_logo.png` here to brand generated papers.

- **File name:** `pillora_logo.png` (path is `app/pdf/assets/pillora_logo.png`, referenced as
  `LOGO_PATH` in `app/pdf/layout_engine.py`).
- **Format:** PNG, ideally with a transparent background (drawn with `mask="auto"`).
- **Sizing:** scaled to a fixed width (aspect ratio preserved) — 250 px in the page header,
  350 px on the cover. A source image ~500–1000 px wide is plenty at 300 DPI.

The logo is optional: if this file is absent, the header and cover render without it (no error).
`_load_logo()` caches the result, so adding or replacing the file takes effect on the next process
restart.
