"""Tests for the admin-managed generation config and cover-title CRUD."""

from app.models.orm import CoverTitle
from app.services.generation_config import (
    DEFAULT_COVER_BODY,
    DEFAULT_HEADER_TEXT,
    DEFAULT_SUBTITLE1_PLACEHOLDER,
    DEFAULT_SUBTITLE2_PLACEHOLDER,
)

_CONFIG_PAYLOAD = {
    "subtitle1_placeholder": "eg) subtitle 1",
    "subtitle2_placeholder": "eg) subtitle 2",
    "cover_body": "<p>New body</p>",
    "header_text": "Visit www.pillora.com.sg for resources.",
    "additional_instructions": "Answer all questions.",
    "footer_text": "Pillora 2026",
}


# ---------------------------------------------------------------------------
# GET /api/generation-config
# ---------------------------------------------------------------------------


def test_get_generation_config_requires_auth(client):
    resp = client.get("/api/generation-config")
    assert resp.status_code == 401


def test_get_generation_config_lazily_creates_defaults(public_client):
    """Any authenticated role can read the config; an unseeded database gets
    the canonical defaults created on the fly."""
    resp = public_client.get("/api/generation-config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cover_body"] == DEFAULT_COVER_BODY
    assert data["subtitle1_placeholder"] == DEFAULT_SUBTITLE1_PLACEHOLDER
    assert data["subtitle2_placeholder"] == DEFAULT_SUBTITLE2_PLACEHOLDER
    assert data["header_text"] == DEFAULT_HEADER_TEXT
    assert data["additional_instructions"] == ""
    assert data["footer_text"] == ""
    assert data["titles"] == []


def test_get_generation_config_lists_titles_in_id_order(admin_client, db_session):
    db_session.add_all([CoverTitle(name="B title"), CoverTitle(name="A title")])
    db_session.flush()
    resp = admin_client.get("/api/generation-config")
    assert resp.status_code == 200
    # id order = creation order, not alphabetical — the first is the default.
    assert [t["name"] for t in resp.json()["titles"]] == ["B title", "A title"]


# ---------------------------------------------------------------------------
# PUT /api/generation-config
# ---------------------------------------------------------------------------


def test_update_generation_config_admin_only(public_client):
    resp = public_client.put("/api/generation-config", json=_CONFIG_PAYLOAD)
    assert resp.status_code == 403


def test_update_generation_config_premium_forbidden(premium_client):
    resp = premium_client.put("/api/generation-config", json=_CONFIG_PAYLOAD)
    assert resp.status_code == 403


def test_update_generation_config_round_trips(admin_client):
    resp = admin_client.put("/api/generation-config", json=_CONFIG_PAYLOAD)
    assert resp.status_code == 200
    for key, value in _CONFIG_PAYLOAD.items():
        assert resp.json()[key] == value

    again = admin_client.get("/api/generation-config")
    for key, value in _CONFIG_PAYLOAD.items():
        assert again.json()[key] == value


# ---------------------------------------------------------------------------
# Cover titles CRUD
# ---------------------------------------------------------------------------


def test_list_cover_titles_requires_auth(client):
    resp = client.get("/api/cover-titles")
    assert resp.status_code == 401


def test_create_cover_title_admin_only(public_client):
    resp = public_client.post("/api/cover-titles", json={"name": "Nope"})
    assert resp.status_code == 403


def test_cover_title_crud_cycle(admin_client):
    created = admin_client.post("/api/cover-titles", json={"name": "Topical Worksheets"})
    assert created.status_code == 201
    title_id = created.json()["id"]

    listed = admin_client.get("/api/cover-titles")
    assert listed.status_code == 200
    assert [t["name"] for t in listed.json()["data"]] == ["Topical Worksheets"]

    updated = admin_client.put(f"/api/cover-titles/{title_id}", json={"name": "Revision Pack"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Revision Pack"

    deleted = admin_client.delete(f"/api/cover-titles/{title_id}")
    assert deleted.status_code == 204
    assert admin_client.get("/api/cover-titles").json()["data"] == []


def test_create_cover_title_duplicate_returns_409(admin_client):
    assert admin_client.post("/api/cover-titles", json={"name": "Twice"}).status_code == 201
    resp = admin_client.post("/api/cover-titles", json={"name": "Twice"})
    assert resp.status_code == 409


def test_update_cover_title_duplicate_returns_409(admin_client):
    admin_client.post("/api/cover-titles", json={"name": "First"})
    second = admin_client.post("/api/cover-titles", json={"name": "Second"}).json()
    resp = admin_client.put(f"/api/cover-titles/{second['id']}", json={"name": "First"})
    assert resp.status_code == 409


def test_cover_title_not_found_returns_404(admin_client):
    assert admin_client.put("/api/cover-titles/999", json={"name": "X"}).status_code == 404
    assert admin_client.delete("/api/cover-titles/999").status_code == 404
