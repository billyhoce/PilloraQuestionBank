import os
from datetime import datetime, timedelta, UTC
from typing import Optional

import bcrypt
from jose import JWTError, jwt

_JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
_ALGORITHM = "HS256"
_DEFAULT_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def normalize_email(email: str) -> str:
    """The canonical form an address is stored and looked up under.

    Every write and every lookup must go through this, or the same person ends
    up with two accounts. Google's OIDC ``email`` claim is lower-case, so an
    admin who invites ``Billy@Gmail.com`` would otherwise get a *second*,
    unentitled row the moment that person signs in with Google.

    Only case and surrounding whitespace are folded. Gmail's dot and ``+``
    aliases deliberately are **not** — they are provider-specific, and treating
    ``a.b@`` and ``ab@`` as one address would be wrong for every other provider.
    """
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: Optional[str]) -> bool:
    # Google-only accounts have no password_hash; bcrypt.checkpw raises on an
    # empty/malformed hash, so reject those up front rather than 500-ing.
    if not hashed:
        return False
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=_DEFAULT_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, _JWT_SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _JWT_SECRET_KEY, algorithms=[_ALGORITHM])
    except JWTError:
        return None
