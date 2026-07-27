"""Google OAuth 2.0 (server-side authorization-code flow).

Pure helpers — no DB, no FastAPI. The route layer (``app/routes/auth.py``) owns
the cookies, the account lookup and the redirects.

The client secret never leaves the server and no Google JavaScript is loaded in
the browser: we redirect the user to Google, Google redirects back to
``GOOGLE_REDIRECT_URI`` with a one-time code, and we exchange that code
server-to-server.

Configuration comes from the environment (see ``.env.example``). When any of the
three values is missing the feature is simply off — ``is_configured()`` returns
False and the frontend hides the Google button.
"""
import os
from typing import Optional
from urllib.parse import urlencode

import httpx

_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
_GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

# Only non-sensitive scopes, so the OAuth consent screen needs no Google review.
_SCOPES = "openid email profile"

_TIMEOUT = 10.0


class GoogleOAuthError(Exception):
    """Raised when Google rejects the code exchange or the userinfo lookup."""


def is_configured() -> bool:
    return bool(_GOOGLE_CLIENT_ID and _GOOGLE_CLIENT_SECRET and _GOOGLE_REDIRECT_URI)


def build_authorization_url(state: str) -> str:
    """The URL to send the browser to. ``state`` is echoed back by Google and
    checked against a cookie to defeat login CSRF."""
    params = {
        "client_id": _GOOGLE_CLIENT_ID,
        "redirect_uri": _GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        # No refresh token needed — we mint our own session JWT and never call
        # Google again on the user's behalf.
        "access_type": "online",
        # Always let the user pick which Google account to use.
        "prompt": "select_account",
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Trade the one-time authorization code for an access token."""
    try:
        resp = httpx.post(
            _TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": _GOOGLE_CLIENT_ID,
                "client_secret": _GOOGLE_CLIENT_SECRET,
                "redirect_uri": _GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GoogleOAuthError(f"token exchange failed: {exc}") from exc
    if resp.status_code != 200:
        raise GoogleOAuthError(f"token exchange returned {resp.status_code}")
    return resp.json()


def fetch_userinfo(access_token: str) -> dict:
    """Read the signed-in Google profile.

    Uses the OIDC userinfo endpoint rather than verifying the ``id_token`` JWT
    locally: the response comes straight from Google over TLS in a call the
    client cannot influence, so it is equally trustworthy without a JWKS fetch.

    Returns Google's raw payload: ``sub``, ``email``, ``email_verified``,
    ``given_name``, ``family_name``.
    """
    try:
        resp = httpx.get(
            _USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GoogleOAuthError(f"userinfo request failed: {exc}") from exc
    if resp.status_code != 200:
        raise GoogleOAuthError(f"userinfo returned {resp.status_code}")
    return resp.json()


def profile_from_code(code: str) -> dict:
    """``exchange_code`` + ``fetch_userinfo``, with the two failure modes that
    matter to the caller collapsed into ``GoogleOAuthError``."""
    token = exchange_code(code)
    access_token: Optional[str] = token.get("access_token")
    if not access_token:
        raise GoogleOAuthError("token response contained no access_token")
    return fetch_userinfo(access_token)
