"""Tokens and cost of launch videos, per video.

    python -m app.builder.video_usage            # the last 20 videos
    python -m app.builder.video_usage <video_id>

Each model call of a video is recorded as a usage event of kind "video" whose
meta.stage is "video:<id>" (older videos, before that tag, show as untagged).
"""
import asyncio
import sys

from sqlalchemy import select

from app.builder import video as video_mod
from app.db.models import BuilderUsageEvent, BuilderVideo
from app.db.session import async_session


async def main(argv: list[str]) -> int:
    async with async_session() as db:
        query = select(BuilderVideo).order_by(BuilderVideo.created_at.desc())
        query = query.where(BuilderVideo.id == argv[0]) if argv else query.limit(20)
        videos = (await db.execute(query)).scalars().all()
        events = (await db.execute(select(BuilderUsageEvent).where(
            BuilderUsageEvent.kind == video_mod.USAGE_KIND))).scalars().all()
    by_video: dict[str, dict] = {}
    for e in events:
        stage = (e.meta or {}).get("stage") or ""
        vid = stage.split(":", 1)[1] if stage.startswith("video:") else None
        if vid is None:
            continue
        row = by_video.setdefault(vid, {"calls": 0, "prompt": 0, "cached": 0, "output": 0, "cost": 0.0})
        meta = e.meta or {}
        row["calls"] += 1
        row["prompt"] += meta.get("prompt_tokens") or 0
        row["cached"] += meta.get("cached_tokens") or 0
        row["output"] += meta.get("completion_tokens") or 0
        row["cost"] += float(e.cost_usd or 0)
    print(f"{'video':10} {'created':16} {'status':9} {'model':30} {'calls':>5} {'prompt':>11} "
          f"{'of it cached':>12} {'output':>9} {'cost':>8}  paid")
    for v in videos:
        r = by_video.get(v.id)
        if r is None:
            print(f"{v.id[:8]:10} {v.created_at:%Y-%m-%d %H:%M} {v.status:9} {(v.model or '-'):30}   (no tagged usage)")
            continue
        print(f"{v.id[:8]:10} {v.created_at:%Y-%m-%d %H:%M} {v.status:9} {(v.model or '-'):30} {r['calls']:>5} "
              f"{r['prompt']:>11,} {r['cached']:>12,} {r['output']:>9,} {r['cost']:>8.3f}  {v.paid_with}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
