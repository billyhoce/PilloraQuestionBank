import os
from datetime import datetime, timedelta, UTC
from typing import Optional

import bcrypt
from jose import JWTError, jwt

_JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
_ALGORITHM = "HS256"
_DEFAULT_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
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
