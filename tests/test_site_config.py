"""Tests for the site-wide config: the public About content and the
image-protection toggle."""

from app.services.site_config import DEFAULT_ABOUT_CONTENT, sanitize_about_content


# ---------------------------------------------------------------------------
# GET /api/site-config — public
# ---------------------------------------------------------------------------


def test_get_site_config_is_public(client):
    """No auth dependency at all: the About page and the Browse page both read
    this while signed out."""
    resp = client.get("/api/site-config")
    assert resp.status_code == 200
    assert resp.json() == {
        "about_content": DEFAULT_ABOUT_CONTENT,
        "protect_images": False,
    }


def test_get_site_config_lazily_creates_the_row(client, db_session):
    """An unseeded database self-heals rather than 500-ing, same as the
    generation config."""
    from app.models.orm import SiteConfig

    assert db_session.get(SiteConfig, 1) is None
    client.get("/api/site-config")
    assert db_session.get(SiteConfig, 1) is not None


# ---------------------------------------------------------------------------
# PUT /api/site-config — admin only
# ---------------------------------------------------------------------------


def test_put_site_config_requires_auth(client):
    resp = client.put("/api/site-config", json={"protect_images": True})
    assert resp.status_code == 401


def test_put_site_config_rejects_non_admin(public_client):
    resp = public_client.put("/api/site-config", json={"protect_images": True})
    assert resp.status_code == 403


def test_admin_can_set_both_fields(admin_client):
    resp = admin_client.put(
        "/api/site-config",
        json={"about_content": "<p>Hello</p>", "protect_images": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"about_content": "<p>Hello</p>", "protect_images": True}

    assert admin_client.get("/api/site-config").json()["protect_images"] is True


def test_update_is_partial_so_the_two_editors_do_not_clobber_each_other(admin_client):
    """The About page and the User Management toggle write the same row from
    different screens; sending one field must leave the other alone."""
    admin_client.put(
        "/api/site-config",
        json={"about_content": "<p>Original</p>", "protect_images": True},
    )

    resp = admin_client.put("/api/site-config", json={"protect_images": False})
    assert resp.status_code == 200
    assert resp.json() == {"about_content": "<p>Original</p>", "protect_images": False}

    resp = admin_client.put("/api/site-config", json={"about_content": "<p>New</p>"})
    assert resp.json() == {"about_content": "<p>New</p>", "protect_images": False}


def test_about_content_is_sanitized_on_write(admin_client):
    """Stored HTML is rendered straight into the browser, so the allowlist runs
    on write rather than on render."""
    resp = admin_client.put(
        "/api/site-config",
        json={
            "about_content": (
                "<h2>Title</h2>"
                "<script>alert(1)</script>"
                '<img src="x" onerror="alert(1)">'
                '<a href="javascript:alert(1)">bad</a>'
                '<a href="https://pillora.com.sg">good</a>'
                '<ul><li style="color:#ff0000">red</li></ul>'
            )
        },
    )
    assert resp.status_code == 200
    stored = resp.json()["about_content"]

    # Dangerous constructs are gone...
    assert "<script" not in stored
    assert "alert(1)" not in stored
    assert "onerror" not in stored
    assert "javascript:" not in stored
    assert "<img" not in stored
    # ...while the marks the editor actually produces survive.
    assert "<h2>Title</h2>" in stored
    assert '<a href="https://pillora.com.sg">good</a>' in stored
    assert "<ul>" in stored and "color:" in stored


# ---------------------------------------------------------------------------
# The sanitizer itself
# ---------------------------------------------------------------------------


def test_sanitizer_keeps_the_editor_marks():
    html = (
        "<h1>H</h1><h2>H</h2><h3>H</h3>"
        "<p><strong>b</strong><em>i</em><u>u</u><s>s</s></p>"
        "<ul><li>a</li></ul><ol><li>b</li></ol>"
        '<span style="font-family:Georgia, serif;font-size:20px;color:#112233">x</span>'
    )
    out = sanitize_about_content(html)
    for fragment in ("<h1>", "<h2>", "<h3>", "<strong>", "<em>", "<u>", "<s>",
                     "<ul>", "<ol>", "<li>", "font-family", "font-size", "color"):
        assert fragment in out, fragment


def test_sanitizer_drops_css_that_could_hijack_the_page():
    """Only the properties the toolbar can set survive — a stored `position:fixed`
    overlay would otherwise cover the whole app."""
    out = sanitize_about_content('<p style="color:red;position:fixed;top:0">x</p>')
    assert "color" in out
    assert "position" not in out
    assert "top" not in out


def test_sanitizer_drops_script_and_style_bodies_whole():
    """bleach keeps a disallowed tag's text, which would dump a <style> block onto
    the page as prose — the usual result of pasting from Word."""
    out = sanitize_about_content("<p>keep</p><script>alert(1)</script><style>p{color:red}</style>")
    assert out == "<p>keep</p>"


def test_sanitizer_accepts_empty_and_none():
    assert sanitize_about_content("") == ""
    assert sanitize_about_content(None) == ""
