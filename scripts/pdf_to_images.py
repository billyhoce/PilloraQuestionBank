#!/usr/bin/env python3
"""
Convert a PDF's pages to PNG images (one file per page).

Works on any PDF — generated sample papers, files in samples/, etc. The
default 120 DPI keeps an A4 page around 992×1403px: small enough to inspect
cheaply, sharp enough that the page chrome text stays legible. Raise --dpi to
zoom into a suspect page.

Usage:
  python scripts/pdf_to_images.py <pdf_path> [--out-dir DIR] [--dpi N]

Example:
  python scripts/pdf_to_images.py sample_paper.pdf --dpi 120
"""

import argparse
from pathlib import Path

import fitz  # PyMuPDF


def pdf_to_pngs(pdf_path, out_dir=None, dpi: int = 120) -> list[Path]:
    """Rasterize every page of ``pdf_path`` to ``page_NN.png`` files in
    ``out_dir`` (default: ``<pdf-stem>_pages/`` beside the PDF). Returns the
    written paths in page order."""
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir else pdf_path.parent / f"{pdf_path.stem}_pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=dpi)
            path = out_dir / f"page_{i:02d}.png"
            pix.save(path)
            paths.append(path)
    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("pdf_path", help="PDF file to convert")
    parser.add_argument("--out-dir", help="output directory (default: <pdf-stem>_pages/)")
    parser.add_argument("--dpi", type=int, default=120, help="render resolution (default: 120)")
    args = parser.parse_args(argv)

    for path in pdf_to_pngs(args.pdf_path, args.out_dir, args.dpi):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
