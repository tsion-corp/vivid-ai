from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class EmailStartRequest(BaseModel):
    # Pasted addresses and codes often carry spaces.
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")


class EmailVerifyRequest(EmailStartRequest):
    code: str = Field(min_length=4, max_length=12)


class DecaneLoginRequest(BaseModel):
    # The Decane access token from the sign-in callback.
    access_token: str
    # Google's pass-through profile from the same callback — display-only,
    # never used to look accounts up.
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    picture: str | None = Field(default=None, max_length=1024)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str | None = None
    avatar_url: str | None = None
    profile_email: str | None = None
    created_at: datetime


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
