"""FastAPI dependency providers for the app's outbound I/O.

Routes take these via ``Depends`` instead of calling S3 and the Claude API
directly, which gives one seam that both production and tests use: production
gets the real client, `tests/conftest.py` swaps in a fake through
``app.dependency_overrides``.

The alternative — and what this replaced — was ``patch("app.routes.X.helper")``
in every test. That couples a test to the *import site* of a helper it may never
mention, so moving a function between modules breaks tests unrelated to it. It
also meant the route's real interface (what it needs to do its job) was invisible
in its signature.

``app/pdf/layout_engine.py`` already worked this way with its ``fetch_bytes``
parameter; these providers extend the same idea to the route layer.
"""

from typing import Callable

from app.ai.topic_labeler import label_question
from app.storage.s3_client import get_image_bytes, get_presigned_url

Presigner = Callable[[str], str]
ImageFetcher = Callable[[str], bytes]


def get_presigner() -> Presigner:
    """Makes a time-limited public URL for an object key."""
    return get_presigned_url


def get_image_fetcher() -> ImageFetcher:
    """Reads an object's raw bytes for server-side use (PDF render, AI vision)."""
    return get_image_bytes


def get_question_labeller():
    """The Claude call that splits a question into parts and labels them."""
    return label_question
