from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import User
from app.routes.auth import require_admin
from app.schemas.site_config import SiteConfigResponse, SiteConfigUpdate
from app.services.site_config import get_or_create_site_config, sanitize_about_content

router = APIRouter(prefix="/api", tags=["site-config"])


@router.get("/site-config", response_model=SiteConfigResponse)
def get_site_config(db: Session = Depends(get_db)):
    """The site-wide settings. Deliberately **unauthenticated**: the About page is
    public, and the public Browse page needs ``protect_images`` to decide how to
    render question images."""
    return SiteConfigResponse.model_validate(get_or_create_site_config(db))


@router.put("/site-config", response_model=SiteConfigResponse)
def update_site_config(
    payload: SiteConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update the site-wide settings. Admin only.

    A partial update — only the fields present in the body are written — so the
    About editor and the image toggle, which live on different pages, cannot
    clobber each other. ``about_content`` is sanitized here rather than at render
    time, since it is rendered as HTML in the browser."""
    cfg = get_or_create_site_config(db)
    if payload.about_content is not None:
        cfg.about_content = sanitize_about_content(payload.about_content)
    if payload.protect_images is not None:
        cfg.protect_images = payload.protect_images
    db.flush()
    return SiteConfigResponse.model_validate(cfg)
