"""Push notifications: the phones a user signed in on.

    POST   /v1/me/push-tokens          {token, platform?, app_version?} -> the device
    GET    /v1/me/push-tokens          the user's devices
    DELETE /v1/me/push-tokens/{token}  at sign-out (URL-encode the token)

The backend pushes when a build turn or an app build ends; see
app/services/push.py for the messages and their `data`.
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_session_user
from app.core.errors import APIError
from app.db.models import User
from app.services import push

router = APIRouter(prefix="/me/push-tokens", tags=["push"])


class PushTokenIn(BaseModel):
    #: The Expo push token, ExponentPushToken[...].
    token: str = Field(max_length=255)
    platform: Literal["ios", "android"] | None = None
    app_version: str | None = Field(default=None, max_length=32)


class PushDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    token: str
    platform: str | None
    app_version: str | None
    created_at: datetime
    last_seen_at: datetime


@router.post("", response_model=PushDeviceOut, status_code=201)
async def register_device(body: PushTokenIn, user: User = Depends(get_session_user),
                          db: AsyncSession = Depends(get_db)):
    """Call after sign-in and whenever Expo hands the app a new token; it is
    safe to call on every launch."""
    token = body.token.strip()
    if not push.valid(token):
        raise APIError(422, "invalid_token", "That is not an Expo push token (ExponentPushToken[...]).")
    row = await push.register(db, user.id, token, body.platform, body.app_version)
    await db.commit()
    return row


@router.get("", response_model=list[PushDeviceOut])
async def list_devices(user: User = Depends(get_session_user), db: AsyncSession = Depends(get_db)):
    return await push.devices(db, user.id)


@router.delete("/{token}", status_code=204)
async def remove_device(token: str, user: User = Depends(get_session_user),
                        db: AsyncSession = Depends(get_db)):
    """At sign-out. Removing a token that is not registered is not an error."""
    await push.unregister(db, user.id, token.strip())
    await db.commit()
    return Response(status_code=204)
