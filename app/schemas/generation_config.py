from pydantic import BaseModel

_orm = {"from_attributes": True}


class CoverTitleResponse(BaseModel):
    id: int
    name: str
    model_config = _orm


class GenerationConfigUpdate(BaseModel):
    """Admin update of the generation presets (all six scalar fields).

    ``cover_body``, ``header_text``, ``additional_instructions`` and
    ``footer_text`` are rich text — the paragraph/bold/italic/underline/link HTML
    the editor produces, sanitized to the supported subset by
    ``app/pdf/rich_text.py`` at render time. Plain text is still accepted and
    treated as the legacy newline-separated format."""

    subtitle1_placeholder: str
    subtitle2_placeholder: str
    cover_body: str
    header_text: str
    additional_instructions: str
    footer_text: str


class GenerationConfigResponse(BaseModel):
    """The full config plus the cover-title list (id order — the first title is
    the non-admin dropdown default). Served to any authenticated user: every
    value here is printed verbatim in the PDFs users generate, so nothing is
    secret; the admin-only part is *writing* it."""

    titles: list[CoverTitleResponse]
    subtitle1_placeholder: str
    subtitle2_placeholder: str
    cover_body: str
    header_text: str
    additional_instructions: str
    footer_text: str
