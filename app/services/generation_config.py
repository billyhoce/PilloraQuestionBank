"""Generation-config access and its seed defaults.

The config is a singleton row (id=1) of admin-set presets applied to every
non-admin paper generation. The Alembic migration seeds it (and one cover
title) with the values below; ``get_or_create_config`` re-creates the row on
the fly if it is ever missing (e.g. test databases built straight from
``Base.metadata.create_all``).
"""

from sqlalchemy.orm import Session

from app.models.orm import GenerationConfig

DEFAULT_COVER_TITLE = "Topical Worksheets"

DEFAULT_SUBTITLE1_PLACEHOLDER = "e.g. Secondary 3 Mathematics"
DEFAULT_SUBTITLE2_PLACEHOLDER = "e.g. 2024 Prelim"

# Branding drawn right-aligned on the top rule of every generated page. Newlines
# stack upward so the last line sits on the rule; the URL token is auto-linked.
DEFAULT_HEADER_TEXT = (
    "Visit www.pillora.com.sg for more learning resources.\n"
    "Join @PilloraSecondary on Telegram to learn together!"
)

# Rich-text HTML limited to the marks the cover renderer supports
# (<p>/<br>/<b>/<i>/<u>/<a href>; see app/pdf/cover_body.py).
DEFAULT_COVER_BODY = (
    "<p>Dear students,</p>"
    "<p>Did you know that research shows students learn best when they focus on topical practice "
    "first before moving on to full-paper practice? Many students jump straight into full exam "
    "papers as practice without realising that they are losing marks in the SAME few areas every "
    "time.</p>"
    "<p>That is why I have compiled and vetted these topical worksheets, making sure they contain "
    "only exam-style questions.</p>"
    "<p>I recommend identifying your weaker topics and practising them using these topical "
    "worksheets before moving to timed full papers. If you need help figuring out your weaker "
    "areas, or need to clarify anything about any specific topic, come book a consultation "
    "session with me through my website, without having to sign up for any tuition package.</p>"
    "<p>For more resources such as Math and Science notes, topical worksheets, WA1–3/EOY papers, "
    'and textbook/workbook answers, please visit '
    '<a href="https://www.pillora.com.sg">www.pillora.com.sg</a>.</p>'
    "<p>You can do it! All the best :)</p>"
    "<p>Teacher Jia Xin<br>Founder of Pillora Learning</p>"
)


def get_or_create_config(db: Session) -> GenerationConfig:
    """Return the singleton config row, creating it with the defaults if the
    database has never been seeded."""
    cfg = db.get(GenerationConfig, 1)
    if cfg is None:
        cfg = GenerationConfig(
            id=1,
            subtitle1_placeholder=DEFAULT_SUBTITLE1_PLACEHOLDER,
            subtitle2_placeholder=DEFAULT_SUBTITLE2_PLACEHOLDER,
            cover_body=DEFAULT_COVER_BODY,
            header_text=DEFAULT_HEADER_TEXT,
        )
        db.add(cfg)
        db.flush()
    return cfg
