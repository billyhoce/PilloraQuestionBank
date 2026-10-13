from pydantic import BaseModel


class SiteConfigUpdate(BaseModel):
    """Admin update of the site-wide settings.

    Both fields are **optional** and only the ones present are applied. The two
    settings are edited from different pages — the About content from
    ``/about``, the image toggle from User Management — so a full replace would
    let one page silently overwrite the other's value with whatever it happened
    to have loaded."""

    about_content: str | None = None
    protect_images: bool | None = None


class SiteConfigResponse(BaseModel):
    """Served to **anyone**, signed in or not: the About page is public and the
    Browse page (also public) needs the image-protection flag. Neither value is
    secret — writing them is what's restricted."""

    about_content: str
    protect_images: bool

    model_config = {"from_attributes": True}
