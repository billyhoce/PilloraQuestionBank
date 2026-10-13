"""Site-config access, its seed default, and the About-content sanitizer.

The config is a singleton row (id=1) of settings that apply site-wide rather
than to paper generation. The Alembic migration seeds it; ``get_or_create_site_config``
re-creates the row on the fly if it is ever missing (e.g. test databases built
straight from ``Base.metadata.create_all``), mirroring
``app/services/generation_config.py``.
"""

import re

import bleach
from bleach.css_sanitizer import CSSSanitizer
from sqlalchemy.orm import Session

from app.models.orm import SiteConfig

DEFAULT_ABOUT_CONTENT = (
    "<h2>About Pillora</h2>"
    "<p>Pillora Learning maintains this question bank so students and tutors can build "
    "topical practice from real secondary school exam papers.</p>"
    "<p>Browse questions by subject, level and topic, then generate a custom paper as a "
    "downloadable PDF.</p>"
    "<p>Admins can edit this page from the About tab.</p>"
)

# The About page is the one place we render stored HTML straight into the
# browser, so the allowlist is the security boundary. It is deliberately wider
# than the PDF subset in app/pdf/rich_text.py — this content is drawn by a
# browser, not ReportLab, so headings, lists and inline styling are all fine.
ALLOWED_TAGS = {
    "p", "br", "hr",
    "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "h1", "h2", "h3", "h4",
    "ul", "ol", "li",
    "blockquote",
    "a", "span", "div",
}

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "span": ["style"],
    "div": ["style"],
    "p": ["style"],
    "li": ["style"],
    "h1": ["style"],
    "h2": ["style"],
    "h3": ["style"],
    "h4": ["style"],
}

# Anything not listed is dropped from the style attribute, so an editor can set
# colour/size/font but not, say, position an element over the rest of the page.
ALLOWED_CSS_PROPERTIES = [
    "color",
    "background-color",
    "font-size",
    "font-family",
    "font-weight",
    "font-style",
    "text-align",
    "text-decoration",
]

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=ALLOWED_CSS_PROPERTIES)

# bleach strips a disallowed *tag* but keeps its text, which is inert but would
# dump the body of a <script>/<style> block onto the page as visible prose — the
# usual result of pasting from Word. Drop those two elements whole first.
_DROP_WHOLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)


def sanitize_about_content(html: str) -> str:
    """Strip everything outside the allowlist from admin-authored About HTML.

    Sanitizing on **write** rather than on render keeps the stored value clean
    for every future consumer and avoids a frontend sanitizer dependency. Only
    admins can write this field, but a compromised admin session should not
    become stored XSS against every visitor — including signed-out ones, since
    the About page is public.
    """
    return bleach.clean(
        _DROP_WHOLE.sub("", html or ""),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
    )


def get_or_create_site_config(db: Session) -> SiteConfig:
    """Return the singleton site-config row, creating it with the defaults if the
    database has never been seeded."""
    cfg = db.get(SiteConfig, 1)
    if cfg is None:
        cfg = SiteConfig(id=1, about_content=DEFAULT_ABOUT_CONTENT, protect_images=False)
        db.add(cfg)
        db.flush()
    return cfg
