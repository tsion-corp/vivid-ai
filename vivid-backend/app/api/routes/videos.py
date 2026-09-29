"""Launch videos of a project (app/builder/video.py)."""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.routes.builder import _owned
from app.api.routes.wallet import _insufficient
from app.builder import snapshots, video as video_mod
from app.core.errors import APIError
from app.db.models import BuilderVideo, User
from app.schemas.videos import VideoAllowanceOut, VideoIn, VideoOut
from app.services.wallet import ledger

log = logging.getLogger("vivid.videos")

router = APIRouter(prefix="/builder", tags=["builder-videos"])


def _out(video: BuilderVideo) -> VideoOut:
    video_url, poster_url = video_mod.urls(video)
    return VideoOut(id=video.id, status=video.status, tone=video.tone, format=video.format,
                    direction=video.direction, duration_s=video.duration_s, video_url=video_url,
                    poster_url=poster_url, share_copy=video.share_copy, error=video.error,
                    paid_with=video.paid_with,
                    amount_usd=video.amount_micro / 1_000_000 if video.amount_micro else None,
                    created_at=video.created_at, finished_at=video.finished_at)


@router.get("/me/videos/allowance", response_model=VideoAllowanceOut)
async def my_allowance(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Your launch videos this plan month, and the price of one more."""
    return VideoAllowanceOut(**await video_mod.allowance(db, user.id))


@router.get("/projects/{project_id}/videos/allowance", response_model=VideoAllowanceOut)
async def project_allowance(project_id: str, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """The allowance a video of this project draws on: its owner's."""
    project = await _owned(project_id, user, db, "viewer")
    return VideoAllowanceOut(**await video_mod.allowance(db, project.owner_id))


@router.post("/projects/{project_id}/videos", response_model=VideoOut, status_code=202)
async def make_video(project_id: str, body: VideoIn, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """Start a launch video: about ten minutes. Included in the owner's plan
    while the month's videos last, then paid from the owner's wallet
    (refunded if it fails). Poll GET .../videos/{id}."""
    project = await _owned(project_id, user, db, "editor")
    snapshot = await snapshots.current(db, project)
    if snapshot is None:
        raise APIError(409, "nothing_built", "Build the app before making its video.")
    try:
        video = await video_mod.request(db, project, user, body.tone, body.format, body.direction, snapshot)
    except video_mod.VideoError as e:
        await db.rollback()
        raise APIError(e.status, e.code, str(e))
    except ledger.InsufficientFunds as e:
        await db.rollback()
        raise _insufficient(e)
    await db.commit()
    video_mod.start(video.id)
    return _out(video)


@router.get("/projects/{project_id}/videos", response_model=list[VideoOut])
async def list_videos(project_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db, "viewer")
    rows = await db.execute(select(BuilderVideo).where(BuilderVideo.project_id == project_id,
                                                       BuilderVideo.status != video_mod.CANCELED)
                            .order_by(BuilderVideo.created_at.desc()).limit(50))
    return [_out(v) for v in rows.scalars()]


async def _video(db: AsyncSession, project_id: str, video_id: str) -> BuilderVideo:
    video = await db.get(BuilderVideo, video_id)
    if video is None or video.project_id != project_id:
        raise APIError(404, "not_found", "No such video")
    return video


@router.get("/projects/{project_id}/videos/{video_id}", response_model=VideoOut)
async def get_video(project_id: str, video_id: str, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db, "viewer")
    return _out(await _video(db, project_id, video_id))


@router.delete("/projects/{project_id}/videos/{video_id}", status_code=204)
async def delete_video(project_id: str, video_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Stop a video being made (a paid one is refunded), or remove a finished one."""
    await _owned(project_id, user, db, "editor")
    video = await _video(db, project_id, video_id)
    if video.status in video_mod.ACTIVE:
        await video_mod.cancel(db, video)
    else:
        video.status = video_mod.CANCELED
    await db.commit()
    return Response(status_code=204)
