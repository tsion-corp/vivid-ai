"""Pilot a launch video with a chosen model, to compare models on quality,
time and cost before setting VIDEO_MODEL and VIDEO_PRICE_USD.

    python -m app.builder.video_pilot <project_id> --model anthropic/claude-fable-5.1 \\
        [--tone polished] [--format landscape] [--direction "..."]

Runs in the foreground (about 10-20 minutes), is never charged and never
counts against the owner's allowance (paid_with "pilot"), and prints the
result: status, duration, a link to the video, tokens and cost.
"""
import argparse
import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.builder import snapshots, usage
from app.builder import video as video_mod
from app.db.models import BuilderProject, BuilderUsageEvent, BuilderVideo, User
from app.db.session import async_session


async def main(args: argparse.Namespace) -> int:
    started = datetime.now(timezone.utc)
    async with async_session() as db:
        project = await db.get(BuilderProject, args.project_id)
        if project is None:
            print(f"no project {args.project_id}")
            return 2
        owner = await db.get(User, project.owner_id)
        snapshot = await snapshots.current(db, project)
        if snapshot is None:
            print("that project has no built version")
            return 2
        video = await video_mod.pilot(db, project, owner, args.model, args.tone, args.format,
                                      args.direction, snapshot)
        await db.commit()
        video_id = video.id
    print(f"pilot {video_id}: {project.name} with {args.model} ({args.format}, tone {args.tone or 'auto'})")
    clock = time.monotonic()
    await video_mod._run(video_id)                     # the same job the API starts, awaited here
    minutes = (time.monotonic() - clock) / 60
    async with async_session() as db:
        video = await db.get(BuilderVideo, video_id)
        rows = (await db.execute(select(
            BuilderUsageEvent.kind, func.sum(BuilderUsageEvent.quantity), func.sum(BuilderUsageEvent.cost_usd))
            .where(BuilderUsageEvent.project_id == video.project_id, BuilderUsageEvent.created_at >= started,
                   BuilderUsageEvent.kind.in_((video_mod.USAGE_KIND, usage.SANDBOX)))
            .group_by(BuilderUsageEvent.kind))).all()
        link, _poster = video_mod.urls(video)
    print(f"status   {video.status}{'  (' + (video.error or '') + ')' if video.error else ''}")
    print(f"time     {minutes:.1f} min   video {video.duration_s or 0:.1f} s")
    total = 0.0
    for kind, quantity, cost in rows:
        total += float(cost or 0)
        print(f"{kind:8} {float(quantity or 0):,.0f} {'tokens' if kind == video_mod.USAGE_KIND else 'sandbox s'}"
              f"   ${float(cost or 0):.3f}")
    print(f"cost     ${total:.3f}")
    if link:
        print(f"video    {link}")
    return 0 if video.status == video_mod.DONE else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_id")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tone")
    parser.add_argument("--format", default="landscape")
    parser.add_argument("--direction")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
