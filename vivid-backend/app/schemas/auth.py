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


class DeleteMeRequest(BaseModel):
    #: The code POST /auth/me/deletion-code emailed.
    code: str = Field(min_length=4, max_length=12)


class DeletionBlocker(BaseModel):
    #: pending_withdrawal | earnings_unwithdrawn
    code: str
    message: str
    amount_kobo: int | None = None


class DeletionPreviewOut(BaseModel):
    """What deleting the account would do."""
    blockers: list[DeletionBlocker]
    projects: int
    wallet_balance_micro: int
    #: none | forfeited (below forfeit_below_micro) | refund_by_support
    wallet_outcome: str
    forfeit_below_micro: int
    #: How long money and KYC records are kept afterwards.
    records_kept_days: int
    #: The masked address the code goes to; null when the account has none.
    confirm_email: str | None = None


class DeletionOut(BaseModel):
    deleted: bool
    projects_deleted: int
    wallet_outcome: str


class HandoffRequest(BaseModel):
    #: A path on the web app to land on, e.g. /settings/billing.
    next: str | None = Field(default=None, max_length=200)


class HandoffOut(BaseModel):
    url: str
    token: str
    expires_in: int


class HandoffExchangeRequest(BaseModel):
    token: str = Field(max_length=2048)


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
