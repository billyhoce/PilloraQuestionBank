"""WebP encoding of the clean review images; the only module that writes WebP."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pymupdf


def write_webp(pixmap: pymupdf.Pixmap, path: Path, quality: int) -> None:
    """Write ``pixmap`` as a lossy WebP of the given quality (0-100)."""
    rows = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.stride)
    rgb = rows[:, : pixmap.width * pixmap.n].reshape(pixmap.height, pixmap.width, pixmap.n)
    ok, data = cv2.imencode(
        ".webp", cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_WEBP_QUALITY, quality]
    )
    if not ok:
        raise OSError(f"could not encode {path.name} as WebP")
    path.write_bytes(data.tobytes())
