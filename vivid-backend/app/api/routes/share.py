"""The public side of a preview link (vividbuild.ai/s/<token>): no sign-in.

The page asks here for the live preview, which wakes the project's workspace
the way the owner's preview does, and pings while it stays open so the
workspace is not put to sleep under a viewer. It gets the preview's address
and nothing else: not the code, the thread, the versions or the edit tools
(the preview's editor only answers a parent that turns it on, and this page
never does).
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes import builder as builder_routes
from app.builder import targets
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import BuilderProject, BuilderShare
from app.schemas.builder import SharedPreviewOut
from app.services import rate_limit

log = logging.getLogger("vivid.share")

router = APIRouter(prefix="/s", tags=["builder-share"])


def _ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


async def _shared(token: str, request: Request, db: AsyncSession) -> BuilderProject:
    redis = request.app.state.redis
    if not (await rate_limit.check_bucket(redis, f"share:{token[:16]}", settings.BUILDER_SHARE_PER_MINUTE)
            and await rate_limit.check_bucket(redis, f"share-ip:{_ip(request)}",
                                              settings.BUILDER_SHARE_IP_PER_MINUTE)):
        raise APIError(429, "rate_limited", "Too many opens of this link. Wait a minute.")
    share = (await db.execute(select(BuilderShare).where(BuilderShare.token == token))).scalar_one_or_none()
    project = await db.get(BuilderProject, share.project_id) if share else None
    if project is None:
        raise APIError(404, "not_found", "This link was turned off or never existed.")
    return project


@router.get("/{token}", response_model=SharedPreviewOut)
async def open_shared(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """The live preview behind a link, waking its workspace if it slept.
    409 nothing_built while the project has no version yet."""
    project = await _shared(token, request, db)
    if not project.current_snapshot_id and await builder_routes.snapshots.latest(db, project.id) is None:
        raise APIError(409, "nothing_built", "There is nothing to show yet.")
    sandbox = await builder_routes._sandbox(project.id, request)
    return SharedPreviewOut(name=project.name, target=targets.of(project).name,
                            url=sandbox.preview_url(), device_url=builder_routes._device_url(sandbox))


@router.post("/{token}/ping", status_code=204)
async def ping_shared(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Keeps the workspace awake while the page is open (send every minute)."""
    project = await _shared(token, request, db)
    await builder_routes.manager.touch(project.id)
    return Response(status_code=204)
