import secrets
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services import google_oauth
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.google_oauth import GoogleOAuthError

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE_NAME = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

# Short-lived cookie holding the OAuth `state` nonce, so we can verify that the
# callback belongs to a flow this browser actually started (login CSRF).
_STATE_COOKIE_NAME = "oauth_state"
_STATE_COOKIE_MAX_AGE = 60 * 10  # 10 minutes to complete the Google consent screen


def get_current_user(
    access_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_current_user_optional(
    access_token: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Like ``get_current_user`` but returns ``None`` instead of raising when the
    caller is unauthenticated (or the token is invalid). Used by public endpoints
    that still want to tailor their response to the viewer's tier."""
    if not access_token:
        return None
    payload = decode_access_token(access_token)
    if payload is None:
        return None
    return db.get(User, int(payload["sub"]))


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def can_view_premium(user: Optional[User]) -> bool:
    """Whether ``user`` may see premium paper images / generate with premium
    questions. Admins and premium users qualify; public and anonymous do not."""
    return user is not None and user.role in ("admin", "premium")


def _set_session_cookie(response: Response, user: User) -> None:
    """Issue the session JWT. Shared by password login and the Google callback so
    both paths produce an identical session."""
    token = create_access_token({"sub": str(user.id)})
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )


@router.post("/register", status_code=201, response_model=UserResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = User(
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        password_hash=hash_password(payload.password),
        role="public",
        created_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return user


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # An account created through Google has no password to check, so the generic
    # 401 below would just look like a forgotten password and send the user
    # round in circles. Point them at the button instead. This does disclose
    # that the address has a Google account — a deliberate trade for an
    # otherwise dead-end login, and only for accounts that have *no* password.
    if user is not None and not user.password_hash and user.google_sub:
        raise HTTPException(
            status_code=409,
            detail='This account was created with Google. Use "Sign in with Google" instead.',
        )

    # Everything else stays a single generic 401 — unknown email and wrong
    # password must remain indistinguishable. An account that has *both* a
    # password and a Google link lands here and logs in normally.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _set_session_cookie(response, user)
    return {"message": "Logged in"}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=_COOKIE_NAME, secure=True, samesite="lax")
    return {"message": "Logged out"}


# ---------------------------------------------------------------------------
# Google OAuth 2.0 — server-side authorization-code flow
# ---------------------------------------------------------------------------


@router.get("/providers")
def providers():
    """Which third-party sign-in methods are configured on this deployment, so
    the frontend can hide the Google button when the env vars are unset."""
    return {"google": google_oauth.is_configured()}


@router.get("/google/login")
def google_login():
    """Kick off the flow: remember a random `state` in a cookie and bounce the
    browser to Google's consent screen."""
    if not google_oauth.is_configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    state = secrets.token_urlsafe(32)
    response = RedirectResponse(url=google_oauth.build_authorization_url(state), status_code=307)
    response.set_cookie(
        key=_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=_STATE_COOKIE_MAX_AGE,
    )
    return response


def _oauth_error(code: str) -> RedirectResponse:
    """Bounce back to the login page, which maps `code` to user-facing copy. The
    user is mid-redirect in a browser, so a JSON error body would be a dead end."""
    response = RedirectResponse(url=f"/login?error={code}", status_code=307)
    response.delete_cookie(key=_STATE_COOKIE_NAME, secure=True, samesite="lax")
    return response


def _resolve_google_user(db: Session, profile: dict) -> User:
    """Find, link, or create the account behind a verified Google profile."""
    sub = profile["sub"]
    email = profile["email"]
    given_name = (profile.get("given_name") or "").strip()[:100]
    family_name = (profile.get("family_name") or "").strip()[:100]

    def backfill_names(u: User) -> None:
        # Never overwrite a name the user typed themselves — only fill blanks.
        if not u.first_name:
            u.first_name = given_name
        if not u.last_name:
            u.last_name = family_name

    user = db.query(User).filter(User.google_sub == sub).first()
    if user is not None:
        backfill_names(user)
        return user

    # Google verified ownership of this address, so it is safe to attach to an
    # existing password account. The account keeps its role.
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        user.google_sub = sub
        backfill_names(user)
        return user

    user = User(
        email=email,
        first_name=given_name,
        last_name=family_name,
        password_hash=None,
        google_sub=sub,
        role="public",
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    return user


@router.get("/google/callback")
def google_callback(
    db: Session = Depends(get_db),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    oauth_state: Optional[str] = Cookie(default=None),
):
    if error or not code:
        # The user hit "Cancel" on the consent screen, or Google refused.
        return _oauth_error("google_cancelled")

    if not state or not oauth_state or not secrets.compare_digest(state, oauth_state):
        return _oauth_error("google_state_mismatch")

    try:
        profile = google_oauth.profile_from_code(code)
    except GoogleOAuthError:
        return _oauth_error("google_failed")

    if not profile.get("sub") or not profile.get("email"):
        return _oauth_error("google_failed")
    if not profile.get("email_verified"):
        # Without a verified address we cannot safely match to an existing
        # account, and an unverified address is not proof of identity.
        return _oauth_error("google_email_unverified")

    try:
        user = _resolve_google_user(db, profile)
    except IntegrityError:
        db.rollback()
        return _oauth_error("google_failed")

    response = RedirectResponse(url="/", status_code=307)
    _set_session_cookie(response, user)
    response.delete_cookie(key=_STATE_COOKIE_NAME, secure=True, samesite="lax")
    return response
