import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator

_PASSWORD_RULES = [
    (r".{8,}", "at least 8 characters"),
    (r"[A-Z]", "at least one uppercase letter"),
    (r"[a-z]", "at least one lowercase letter"),
    (r"[0-9]", "at least one number"),
    (r"[^A-Za-z0-9]", "at least one special character"),
]


class RegisterRequest(BaseModel):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    email: EmailStr
    password: str

    @field_validator("first_name", "last_name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        failures = [msg for pattern, msg in _PASSWORD_RULES if not re.search(pattern, v)]
        if failures:
            raise ValueError("password must contain " + ", ".join(failures))
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str

    # Excluded from the response; only the two computed flags below are exposed,
    # so the client can tell how the account signs in without seeing the hash.
    password_hash: Optional[str] = Field(default=None, exclude=True)
    google_sub: Optional[str] = Field(default=None, exclude=True)

    @computed_field
    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    @computed_field
    @property
    def has_google(self) -> bool:
        return bool(self.google_sub)

    model_config = {"from_attributes": True}
