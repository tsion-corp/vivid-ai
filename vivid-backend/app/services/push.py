"""Push notifications to the mobile app, through Expo's push service.

The app registers its Expo push token after sign-in (POST /v1/me/push-tokens)
and removes it at sign-out. The backend tells a user's phones when something
they would otherwise wait on has finished: a build turn, an app build.

Sending is best effort and never fails the work it reports on. A token Expo
says is no longer installed (DeviceNotRegistered) is deleted.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import PushDevice
from app.services.models_gateway import http

log = logging.getLogger("vivid.push")

#: What Expo hands the app: ExponentPushToken[...] (or ExpoPushToken[...]).
TOKEN = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_\-]{10,200}\]$")
#: Expo takes at most 100 messages per request.
BATCH = 100


def valid(token: str) -> bool:
    return bool(TOKEN.match(token or ""))


async def register(db: AsyncSession, user_id: str, token: str, platform: str | None,
                   app_version: str | None) -> PushDevice:
    """The device, now the user's (a token re-registered by another user
    moves to them: one phone, one signed-in person). The caller commits."""
    row = (await db.execute(select(PushDevice).where(PushDevice.token == token))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = PushDevice(user_id=user_id, token=token)
        db.add(row)
    row.user_id, row.last_seen_at = user_id, now
    row.platform = platform or row.platform
    row.app_version = app_version or row.app_version
    await db.flush()
    return row


async def unregister(db: AsyncSession, user_id: str, token: str) -> bool:
    out = await db.execute(delete(PushDevice).where(PushDevice.user_id == user_id,
                                                    PushDevice.token == token))
    return bool(out.rowcount)


async def devices(db: AsyncSession, user_id: str) -> list[PushDevice]:
    return list((await db.execute(select(PushDevice).where(PushDevice.user_id == user_id)
                                  .order_by(PushDevice.created_at))).scalars())


async def send(user_id: str, title: str, body: str, data: dict | None = None) -> int:
    """Notify every phone the user signed in on. Returns how many Expo
    accepted. Never raises."""
    if not settings.PUSH_ENABLED:
        return 0
    try:
        from app.db.session import async_session
        async with async_session() as db:
            tokens = [d.token for d in await devices(db, user_id)]
            if not tokens:
                return 0
            accepted, gone = await _deliver(tokens, title, body, data or {})
            if gone:
                await db.execute(delete(PushDevice).where(PushDevice.token.in_(gone)))
                await db.commit()
            return accepted
    except Exception as e:                                   # a push is never worth a failure
        log.warning("push to %s failed: %s", user_id, e)
        return 0


def send_later(user_id: str, title: str, body: str, data: dict | None = None) -> None:
    """Fire and forget, from code that must not wait on Expo."""
    try:
        asyncio.get_running_loop().create_task(send(user_id, title, body, data))
    except RuntimeError:
        pass


async def _deliver(tokens: list[str], title: str, body: str, data: dict) -> tuple[int, list[str]]:
    headers = {"accept": "application/json", "content-type": "application/json"}
    if settings.EXPO_PUSH_ACCESS_TOKEN:
        headers["authorization"] = f"Bearer {settings.EXPO_PUSH_ACCESS_TOKEN}"
    accepted, gone = 0, []
    for i in range(0, len(tokens), BATCH):
        chunk = tokens[i:i + BATCH]
        messages = [{"to": t, "title": title[:120], "body": body[:240], "data": data,
                     "sound": "default", "priority": "high", "channelId": "default"}
                    for t in chunk]
        r = await http.client().post(settings.EXPO_PUSH_URL, json=messages, headers=headers,
                                     timeout=10)
        if r.status_code >= 400:
            log.warning("expo push answered %s: %s", r.status_code, r.text[:300])
            continue
        tickets = (r.json() or {}).get("data") or []
        for token, ticket in zip(chunk, tickets):
            if ticket.get("status") == "ok":
                accepted += 1
            elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                gone.append(token)
            else:
                log.info("expo push ticket for a device: %s", ticket.get("message"))
    return accepted, gone


# --------------------------------------------------------------- messages
# What each finished piece of work says. `data.type` lets the app open the
# right screen: a project's thread, or its builds.

def turn_finished(user_id: str, project_id: str, project_name: str, *, ok: bool, reason: str,
                  summary: str | None, message_id: str | None, planning: bool = False) -> None:
    if reason == "cancelled":
        return                                               # the user stopped it; they know
    name = project_name or "Your app"
    if planning:
        body = ("A question about your app is waiting for you." if reason == "asked"
                else "The plan is ready to review." if ok
                else "Planning stopped. Open the app to see why.")
    elif ok:
        body = summary or "Your changes are ready to preview."
    else:
        body = "The build didn't finish. Open the app to see what happened."
    send_later(user_id, name, body, {"type": "turn", "project_id": project_id,
                                     "message_id": message_id, "ok": ok})


def app_build_finished(user_id: str, project_id: str, project_name: str, *, build_id: str,
                       platform: str, status: str, artifact_url: str | None) -> None:
    kind = "Android" if platform == "android" else "iOS"
    name = project_name or "Your app"
    if status == "finished":
        body = f"Your {kind} build is ready to install."
    elif status == "failed":
        body = f"Your {kind} build failed. Open the app for the logs."
    else:
        return                                               # canceled: the user did that
    send_later(user_id, name, body, {"type": "app_build", "project_id": project_id,
                                     "build_id": build_id, "status": status,
                                     "artifact_url": artifact_url})
