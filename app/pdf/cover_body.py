"""Sanitize the rich-text cover body into ReportLab paragraph markup.

The frontend cover-body editor (TipTap) produces HTML limited to paragraphs
plus bold / italic / underline / link marks. ``to_paragraphs`` converts that
HTML into the mini-HTML markup Platypus ``Paragraph`` accepts, whitelisting
exactly those tags and escaping everything else, so arbitrary client input can
never break (or script) the PDF renderer.

Output is one markup string per paragraph; an empty string stands for an empty
``<p></p>`` and renders as a blank-line gap. Emitted tags are always balanced —
``Paragraph`` raises on malformed markup — even when the input HTML is not.

Plain text (no ``<`` at all) is treated as the legacy newline-separated format
so pre-rich-text API clients keep working.
"""
from html.parser import HTMLParser
from xml.sax.saxutils import escape, quoteattr

# Marks copied through 1:1 (open/close), normalized to ReportLab's tag names.
_MARK_TAGS = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u"}

_LINK_COLOR = "blue"


def _safe_href(href: str) -> str | None:
    """Return a cleaned link target, or ``None`` to drop the link (text kept)."""
    href = (href or "").strip()
    if href.lower().startswith("www."):
        href = f"https://{href}"
    lowered = href.lower()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return href
    return None


class _CoverBodyParser(HTMLParser):
    """Walk the editor HTML and re-emit only whitelisted markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._parts: list[str] = []  # markup chunks of the paragraph being built
        self._open: list[str] = []   # closing markup owed, innermost last

    # -- paragraph assembly --------------------------------------------------

    def _flush_paragraph(self) -> None:
        # Close any marks left open by malformed input so output stays balanced.
        while self._open:
            self._parts.append(self._open.pop())
        self.paragraphs.append("".join(self._parts).strip())
        self._parts = []

    # -- HTMLParser hooks ------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            if self._parts or self._open:
                self._flush_paragraph()
        elif tag == "br":
            self._parts.append("<br/>")
        elif tag in _MARK_TAGS:
            rl = _MARK_TAGS[tag]
            self._parts.append(f"<{rl}>")
            self._open.append(f"</{rl}>")
        elif tag == "a":
            href = _safe_href(dict(attrs).get("href", ""))
            if href is None:
                self._open.append("")  # link dropped; keep nesting balanced
            else:
                self._parts.append(f"<a href={quoteattr(href)} color={quoteattr(_LINK_COLOR)}><u>")
                self._open.append("</u></a>")
        # Any other tag is stripped; its text content still flows through.

    def handle_endtag(self, tag):
        if tag == "p":
            self._flush_paragraph()
        elif tag in _MARK_TAGS or tag == "a":
            if self._open:
                self._parts.append(self._open.pop())

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._parts.append("<br/>")

    def handle_data(self, data):
        self._parts.append(escape(data))


def _plain_text_paragraphs(body: str) -> list[str]:
    """Legacy format: blank-line-separated blocks become paragraphs; hard
    newlines within a block become ``<br/>`` line breaks."""
    paragraphs: list[str] = []
    block: list[str] = []
    for line in body.split("\n"):
        if line.strip():
            block.append(escape(line.strip()))
        elif block:
            paragraphs.append("<br/>".join(block))
            block = []
    if block:
        paragraphs.append("<br/>".join(block))
    return paragraphs


def to_paragraphs(body: str) -> list[str]:
    """Convert an HTML (or legacy plain-text) cover body to ReportLab markup,
    one balanced markup string per paragraph ("" = blank-line gap)."""
    if "<" not in body:
        return _plain_text_paragraphs(body)
    parser = _CoverBodyParser()
    parser.feed(body)
    parser.close()
    if parser._parts or parser._open:  # trailing text outside any <p>
        parser._flush_paragraph()
    return parser.paragraphs
