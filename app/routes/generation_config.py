from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import CoverTitle, User
from app.routes.auth import get_current_user, require_admin
from app.schemas.generation_config import (
    CoverTitleResponse,
    GenerationConfigResponse,
    GenerationConfigUpdate,
)
from app.schemas.reference import NameRequest
from app.services.generation_config import get_or_create_config

router = APIRouter(prefix="/api", tags=["generation-config"])


def _not_found(label: str):
    raise HTTPException(status_code=404, detail=f"{label} not found")


def _titles(db: Session) -> list[CoverTitle]:
    # id order = creation order; the first title is the non-admin default.
    return db.query(CoverTitle).order_by(CoverTitle.id).all()


def _config_response(db: Session) -> GenerationConfigResponse:
    cfg = get_or_create_config(db)
    return GenerationConfigResponse(
        titles=[CoverTitleResponse.model_validate(t) for t in _titles(db)],
        subtitle1_placeholder=cfg.subtitle1_placeholder,
        subtitle2_placeholder=cfg.subtitle2_placeholder,
        cover_body=cfg.cover_body,
        header_text=cfg.header_text,
        footer_text=cfg.footer_text,
    )


@router.get("/generation-config", response_model=GenerationConfigResponse)
def get_generation_config(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """The generation presets plus the cover-title list, for pre-filling the
    Generate form (all roles) and the admin Generation Config page."""
    return _config_response(db)


@router.put("/generation-config", response_model=GenerationConfigResponse)
def update_generation_config(
    payload: GenerationConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Replace the generation presets. ``cover_body`` is stored as-is and
    sanitized at render time (app/pdf/cover_body.py), same as the request path."""
    cfg = get_or_create_config(db)
    cfg.subtitle1_placeholder = payload.subtitle1_placeholder
    cfg.subtitle2_placeholder = payload.subtitle2_placeholder
    cfg.cover_body = payload.cover_body
    cfg.header_text = payload.header_text
    cfg.footer_text = payload.footer_text
    db.flush()
    return _config_response(db)


# ---------------------------------------------------------------------------
# Cover titles
# ---------------------------------------------------------------------------


@router.get("/cover-titles")
def list_cover_titles(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    return {"data": _titles(db)}


@router.post("/cover-titles", response_model=CoverTitleResponse, status_code=201)
def create_cover_title(
    payload: NameRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    obj = CoverTitle(name=payload.name)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cover title already exists")
    return obj


@router.put("/cover-titles/{cover_title_id}", response_model=CoverTitleResponse)
def update_cover_title(
    cover_title_id: int,
    payload: NameRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    obj = db.get(CoverTitle, cover_title_id)
    if obj is None:
        _not_found("Cover title")
    obj.name = payload.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cover title already exists")
    return obj


@router.delete("/cover-titles/{cover_title_id}", status_code=204)
def delete_cover_title(
    cover_title_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    obj = db.get(CoverTitle, cover_title_id)
    if obj is None:
        _not_found("Cover title")
    # Nothing references titles (the chosen text is baked into the PDF), so a
    # plain delete is safe — no FK guard needed.
    db.delete(obj)
