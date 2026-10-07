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

from app.ai.filename_extractor import extract_metadata
from app.ai.topic_labeler import label_question
from app.storage.object_store import ObjectStore, S3ObjectStore
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


def get_object_store() -> ObjectStore:
    """put / get / presign / delete-prefix over the bucket, for auto-import jobs."""
    return S3ObjectStore()


def get_metadata_extractor():
    """The Claude call that reads paper metadata out of a filename."""
    return extract_metadata


def get_pipeline_runner():
    """The factory the ingest worker builds its pipeline runner with.

    Returns ``factory(store, job_dir, config, wrap) -> runner``; the runner needs
    ``run_one()`` and ``revalidate(job_id)``. ``wrap`` adds the worker's S3 and database edges
    to a registry. Tests override it with a factory whose stages write a canned proposal
    (``tests/test_worker.py``) so no PDF, OCR or Claude call is needed."""
    from pipeline.registry import default_registry
    from pipeline.runner import Runner

    def factory(store, job_dir, config, wrap):
        return Runner(store, wrap(default_registry()), job_dir, config)

    return factory
