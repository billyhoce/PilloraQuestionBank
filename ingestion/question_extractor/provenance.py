"""Where the PDF being processed came from.

The file handed to the extractor is not always the file a user started from: a
router carves a multi-paper document into sections and feeds each section in on
its own. Every rectangle this pipeline reports is in the coordinate space of the
PDF it was given, so a section's page 1 may be page 7 of the document it came
from -- and with no record of that, a rectangle cannot be addressed in the
source at all.

:class:`SourceProvenance` is that record: the original PDF, and a map from each
page of the processed PDF to the page it came from. It is optional at the
pipeline's boundary, and when it is absent the manifest is exactly the manifest
this tool has always written -- every page number local, unqualified, and no
provenance fields at all. Nothing downstream of here changes behaviour on it;
the mapping is applied only where the manifest records a page number.

The map is taken on trust but checked against the document it claims to
describe. A map that does not cover the document is a mistake in the *caller*,
not in the paper, but it is reported the same way everything else wrong with a
run is (see CLAUDE.md, "Warn, never raise"): one warning naming what disagrees,
collected into the manifest. An unmapped page then falls back to its own local
number, which is the only defensible guess, so a bad map degrades to today's
behaviour for the pages it missed rather than losing them.

Warnings here name counts and the first offending page rather than listing every
one, so a 300-page document with a wholly absent map still produces a message a
human can read.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceProvenance:
    """The document a processed PDF was carved out of.

    ``page_map`` maps a 1-based page of the processed PDF to the 1-based page it
    occupies in ``original_pdf``. An empty map means the two are page-for-page
    the same document, which is the useful shape when the original was not split
    but merely renamed or re-saved.
    """

    original_pdf: Path
    page_map: Mapping[int, int] = field(default_factory=dict)

    def original_page(self, page: int) -> int:
        """The original document's page number for a page of the processed PDF.

        An unmapped page answers with itself. That is deliberately quiet: the map
        was already checked against the page count when the run began, so the
        disagreement is reported once there instead of at every page that reads
        it.
        """
        return self.page_map.get(page, page)

    def original_pages(self, pages: list[int]) -> list[int]:
        """:meth:`original_page` across a question's page list, order kept."""
        return [self.original_page(page) for page in pages]

    def manifest_entry(self) -> dict:
        """The provenance block as the manifest records it.

        The map is written out whole, with string keys as JSON requires, so a
        rectangle can be re-addressed without the caller that produced it.
        """
        return {
            "original_pdf": str(self.original_pdf),
            "page_map": {str(page): origin for page, origin in sorted(self.page_map.items())},
        }


def check_page_map(
    provenance: SourceProvenance | None, page_count: int, label: str
) -> None:
    """Warn about every way a page map disagrees with the document it describes.

    Three disagreements are worth a human's attention, and none of them stops a
    run:

    * **unmapped pages** -- the map covers less than the document, so those pages
      will report their local number as if no provenance had been given;
    * **entries past the end** -- the map describes pages the document does not
      have, which usually means the map belongs to a different section;
    * **collisions** -- two pages claiming one original page, which makes the
      rectangles on them indistinguishable in the source.

    An empty map is the documented "same document" case and is not checked.
    """
    if provenance is None or not provenance.page_map:
        return

    pages = provenance.page_map
    unmapped = [page for page in range(1, page_count + 1) if page not in pages]
    if unmapped:
        log.warning(
            "%s: page map covers %d of the document's %d page(s); %d unmapped "
            "(first: page %d) will report their local page number",
            label,
            page_count - len(unmapped),
            page_count,
            len(unmapped),
            unmapped[0],
        )

    outside = sorted(page for page in pages if not 1 <= page <= page_count)
    if outside:
        log.warning(
            "%s: page map has %d entry/entries for pages outside the document "
            "(1-%d, first: page %d); they are never read",
            label,
            len(outside),
            page_count,
            outside[0],
        )

    seen: dict[int, int] = {}
    collisions = []
    for page, origin in sorted(pages.items()):
        if origin in seen:
            collisions.append((seen[origin], page, origin))
        else:
            seen[origin] = page
    if collisions:
        first, second, origin = collisions[0]
        log.warning(
            "%s: page map sends %d page pair(s) to the same original page "
            "(first: pages %d and %d both map to original page %d)",
            label,
            len(collisions),
            first,
            second,
            origin,
        )
