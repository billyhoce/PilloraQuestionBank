import re

from pydantic import BaseModel, EmailStr, field_validator

_PASSWORD_RULES = [
    (r".{8,}", "at least 8 characters"),
    (r"[A-Z]", "at least one uppercase letter"),
    (r"[a-z]", "at least one lowercase letter"),
    (r"[0-9]", "at least one number"),
    (r"[^A-Za-z0-9]", "at least one special character"),
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

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
    role: str

    model_config = {"from_attributes": True}
