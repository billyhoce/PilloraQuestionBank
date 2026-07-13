"""Tests for the cover-body HTML sanitizer/converter (app/pdf/cover_body.py)."""
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from app.pdf.cover_body import to_paragraphs


def test_paragraph_split():
    assert to_paragraphs("<p>one</p><p>two</p>") == ["one", "two"]


def test_empty_paragraph_becomes_blank_gap():
    assert to_paragraphs("<p>one</p><p></p><p>two</p>") == ["one", "", "two"]


def test_marks_map_to_reportlab_tags():
    assert to_paragraphs("<p><strong>b</strong> <em>i</em> <u>u</u></p>") == [
        "<b>b</b> <i>i</i> <u>u</u>"
    ]
    assert to_paragraphs("<p><b>b</b> and <i>i</i></p>") == ["<b>b</b> and <i>i</i>"]


def test_br_preserved():
    assert to_paragraphs("<p>a<br>b</p>") == ["a<br/>b"]
    assert to_paragraphs("<p>a<br/>b</p>") == ["a<br/>b"]


def test_link_gets_href_color_and_underline():
    [para] = to_paragraphs('<p><a href="https://example.com">here</a></p>')
    assert para == '<a href="https://example.com" color="blue"><u>here</u></a>'


def test_bare_www_href_prefixed_with_https():
    [para] = to_paragraphs('<p><a href="www.pillora.com.sg">site</a></p>')
    assert 'href="https://www.pillora.com.sg"' in para


def test_unsafe_href_dropped_text_kept():
    assert to_paragraphs('<p><a href="javascript:alert(1)">click</a></p>') == ["click"]
    assert to_paragraphs("<p><a>click</a></p>") == ["click"]


def test_unknown_tags_stripped_text_kept():
    assert to_paragraphs("<p><h1>big</h1> <script>x</script>ok</p>") == ["big xok"]
    assert to_paragraphs("<div>loose</div>") == ["loose"]


def test_text_is_escaped():
    assert to_paragraphs("<p>a < b & c > d</p>") == ["a &lt; b &amp; c &gt; d"]


def test_unclosed_marks_are_balanced():
    assert to_paragraphs("<p><b>bold</p><p>next</p>") == ["<b>bold</b>", "next"]


def test_plain_text_fallback_blocks_and_line_breaks():
    body = "Dear students,\n\nline one\nline two\n\nBye"
    assert to_paragraphs(body) == ["Dear students,", "line one<br/>line two", "Bye"]


def test_plain_text_fallback_escapes():
    assert to_paragraphs("a & b < c") == ["a &amp; b &lt; c"]


def test_output_is_valid_reportlab_markup():
    """Every emitted paragraph must be accepted by Platypus Paragraph."""
    style = ParagraphStyle("t", fontName="Helvetica", fontSize=10, leading=12)
    nasty = (
        '<p><b>unclosed <a href="www.x.com">link & "quotes"</p>'
        "<p><span>span</span><script>bad()</script><br></p>"
        "<p></p>"
    )
    for markup in to_paragraphs(nasty):
        if markup:
            Paragraph(markup, style)  # raises on malformed markup
