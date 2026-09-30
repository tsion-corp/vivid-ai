"""Launch videos: included per plan month, then paid from the owner's
wallet and refunded when they fail or are canceled; the job runs brag in a
throwaway sandbox, checks the deliverables, stores them and notifies; its
model usage never counts against build credits."""
import asyncio
import json

import pytest

from app.api.routes.videos import router as videos_router
from app.builder import blob, video as video_mod
from app.builder.sandbox.base import RunResult
from app.core.config import settings
from app.db.models import BuilderProject, BuilderSnapshot, BuilderUsageEvent, BuilderVideo
from app.services import mail, push
from app.services.plans import usage as plan_usage
from app.services.wallet import ledger
from tests.builder_fakes import FakeSandbox
from tests.test_builder_loop import call, install, models  # noqa: F401
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401
from tests.test_plans import _fund, small_plans  # noqa: F401


@pytest.fixture
def api(client, fake_manager, monkeypatch):  # noqa: F811
    client.app.include_router(videos_router, prefix="/v1")
    started = []
    monkeypatch.setattr(video_mod, "start", started.append)
    client.started = started
    return client


def built(api):
    pid = api.post("/v1/builder/projects", json={"name": "Kicks", "skip_plan": True}).json()["id"]
    assert api.post(f"/v1/builder/projects/{pid}/videos", json={}).status_code == 409   # nothing built
    assert api.post(f"/v1/builder/projects/{pid}/snapshots").status_code == 200
    return pid


def test_allowance_then_wallet_then_refund(api, maker, fake_blob):  # noqa: F811
    pid = built(api)
    allowance = api.get(f"/v1/builder/projects/{pid}/videos/allowance").json()
    assert allowance["included"] == 1 and allowance["left"] == 1 and allowance["price_usd"] == 1.5

    first = api.post(f"/v1/builder/projects/{pid}/videos", json={"tone": "polished", "format": "vertical"})
    assert first.status_code == 202, first.json()
    assert first.json()["paid_with"] == "allowance" and first.json()["status"] == "queued"
    assert api.started == [first.json()["id"]]
    # One at a time per project.
    busy = api.post(f"/v1/builder/projects/{pid}/videos", json={})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "busy"

    async def finish(vid, status="done"):
        async with maker() as db:
            (await db.get(BuilderVideo, vid)).status = status
            await db.commit()
    asyncio.run(finish(first.json()["id"]))
    assert api.get("/v1/builder/me/videos/allowance").json()["left"] == 0

    # The month's video is used: the next one is paid from the wallet.
    short = api.post(f"/v1/builder/projects/{pid}/videos", json={})
    assert short.status_code == 402 and short.json()["error"]["code"] == "insufficient_funds"
    asyncio.run(_fund(maker, 10))
    paid = api.post(f"/v1/builder/projects/{pid}/videos", json={"direction": "the checkout"})
    assert paid.status_code == 202 and paid.json()["paid_with"] == "wallet" and paid.json()["amount_usd"] == 1.5

    async def balance():
        async with maker() as db:
            return await ledger.balance(db, "u1")
    assert asyncio.run(balance()) == 8_500_000
    # Canceled while being made: refunded, and it is gone from the list.
    assert api.delete(f"/v1/builder/projects/{pid}/videos/{paid.json()['id']}").status_code == 204
    assert asyncio.run(balance()) == 10_000_000
    assert [v["id"] for v in api.get(f"/v1/builder/projects/{pid}/videos").json()] == [first.json()["id"]]
    assert api.post(f"/v1/builder/projects/{pid}/videos", json={"format": "portrait"}).status_code == 422
    api.as_user("u2")
    assert api.get(f"/v1/builder/projects/{pid}/videos").status_code == 404


class VideoSandbox(FakeSandbox):
    """Enough of the vivid-video sandbox: tar and ffprobe."""

    def __init__(self, rendered=True):
        super().__init__()
        self.rendered = rendered

    async def run(self, cmd, timeout=60, env=None):
        self.commands.append(cmd)
        if "tar -xzf" in cmd:
            return RunResult(0, "", "")
        if cmd.startswith("ffprobe"):
            if not self.rendered:
                return RunResult(1, "", "No such file")
            return RunResult(0, json.dumps({"streams": [{"width": 1920, "height": 1080}],
                                            "format": {"duration": "21.3"}}), "")
        if cmd.startswith("test -s"):
            return RunResult(0, "", "")
        if cmd.startswith("ffmpeg"):                            # view_frames: a still at the last argument
            self.blobs[cmd.split()[-1]] = b"\xff\xd8jpeg"
            return RunResult(0, "", "")
        return RunResult(0, "", "")


async def _queued(maker, rendered=True):
    async with maker() as db:
        project = BuilderProject(owner_id="u1", name="Kicks", mode="build")
        db.add(project)
        await db.flush()
        snap = BuilderSnapshot(project_id=project.id, seq=1, r2_key="snap-key")
        db.add(snap)
        await db.flush()
        video = BuilderVideo(project_id=project.id, user_id="u1", owner_id="u1", snapshot_id=snap.id,
                             format="landscape", paid_with="wallet", amount_micro=1_500_000)
        db.add(video)
        await ledger.credit(db, "u1", 1_500_000, ledger.DEPOSIT_BANK, "t", "seed")
        await ledger.debit(db, "u1", 1_500_000, ledger.VIDEO, "vivid", f"video:{video.id}")
        await db.commit()
        return video.id, project.id


def _wire(monkeypatch, maker, fake_blob, sandbox):  # noqa: F811
    fake_blob["snap-key"] = b"tarball"
    monkeypatch.setattr(video_mod, "async_session", maker)

    async def create_fresh(name, target=None, wait=True):
        return sandbox
    monkeypatch.setattr(video_mod.manager, "create_fresh", create_fresh)

    async def record_sandbox(project_id, sandbox_id, seconds):
        return None
    monkeypatch.setattr(video_mod.usage, "record_sandbox", record_sandbox)
    sent = []

    async def send(to, subject, text, html=None, reply_to=None):
        sent.append(subject)
        return True
    monkeypatch.setattr(mail, "send", send)
    monkeypatch.setattr(push, "send_later", lambda *a, **k: None)
    monkeypatch.setattr(blob, "presigned_url", lambda key, expires_in=3600: f"https://r2/{key}")
    return sent


def test_the_job_makes_checks_stores_and_meters(maker, fake_blob, monkeypatch):  # noqa: F811
    sandbox = VideoSandbox()
    sandbox.files["brag-output/share-copy.txt"] = "Kicks, delivered before lunch."
    sandbox.blobs["brag-output/brag.mp4"] = b"mp4"
    sandbox.blobs["brag-output/brag.jpg"] = b"jpg"
    _wire(monkeypatch, maker, fake_blob, sandbox)
    model = install(monkeypatch, [
        ("", [call("read_file", {"path": "project/src/App.tsx"}, "r1")]),
        ("", [call("run_command", {"command": "cd brag-output/composition && npx hyperframes render --output ../brag.mp4"}, "r2")]),
        ("A lunch-rush angle.", []),
    ])
    vid, pid = asyncio.run(_queued(maker))
    asyncio.run(video_mod._run(vid))

    async def row():
        async with maker() as db:
            video = await db.get(BuilderVideo, vid)
            events = (await db.execute(BuilderUsageEvent.__table__.select())).all()
            return video, events
    video, events = asyncio.run(row())
    assert video.status == "done" and video.duration_s == 21.3, video.error
    assert video.share_copy == "Kicks, delivered before lunch." and fake_blob[video.video_key] == b"mp4"
    assert sandbox.killed
    system = model.requests[0]["messages"][0]["content"]
    assert "never switch to brag-slim" in system and "Format: landscape (1920x1080" in system
    assert sorted(model.requests[0]["tools"]) == ["edit_file", "list_files", "read_file", "run_command",
                                                  "view_frames", "write_file"]
    assert {e.kind for e in events} == {"video"}

    async def meter():
        async with maker() as db:
            return (await plan_usage.meter(db, await plan_usage.account_for(db, "u1"))).month_used
    assert asyncio.run(meter()) == 0                        # videos never eat build credits


def test_a_video_that_never_renders_fails_and_refunds(maker, fake_blob, monkeypatch):  # noqa: F811
    _wire(monkeypatch, maker, fake_blob, VideoSandbox(rendered=False))
    install(monkeypatch, [("Done.", []), ("Still done.", [])])
    vid, _ = asyncio.run(_queued(maker))
    asyncio.run(video_mod._run(vid))

    async def check():
        async with maker() as db:
            return await db.get(BuilderVideo, vid), await ledger.balance(db, "u1")
    video, balance = asyncio.run(check())
    assert video.status == "failed" and "not charged" in video.error and balance == 1_500_000


def test_stale_videos_are_reaped_and_refunded(maker):  # noqa: F811
    from datetime import datetime, timedelta, timezone
    vid, _ = asyncio.run(_queued(maker))

    async def age_and_reap():
        async with maker() as db:
            (await db.get(BuilderVideo, vid)).created_at = datetime.now(timezone.utc) - timedelta(hours=2)
            await db.commit()
            n = await video_mod.reap(db)
            await db.commit()
            return n, (await db.get(BuilderVideo, vid)).status, await ledger.balance(db, "u1")
    assert asyncio.run(age_and_reap()) == (1, "failed", 1_500_000)


def test_allowance_follows_the_plan(monkeypatch):
    from app.services.plans import catalog
    assert [catalog.get(p).videos_per_month for p in ("free", "pro", "max")] == [1, 5, 20]
    monkeypatch.setattr(settings, "PLAN_PRO_VIDEOS", 7)
    assert catalog.get("pro").videos_per_month == 7


def test_a_pilot_uses_its_model_is_free_and_sees_its_frames(maker, fake_blob, monkeypatch):  # noqa: F811
    sandbox = VideoSandbox()
    sandbox.files["brag-output/share-copy.txt"] = "Kicks."
    sandbox.blobs["brag-output/brag.mp4"] = b"mp4"
    sandbox.blobs["brag-output/brag.jpg"] = b"jpg"
    _wire(monkeypatch, maker, fake_blob, sandbox)
    model = install(monkeypatch, [
        ("", [call("view_frames", {"path": "brag-output/brag.mp4", "times": [0, 2.5]}, "f1")]),
        ("Looks right.", []),
    ])

    async def make_pilot():
        async with maker() as db:
            project = BuilderProject(owner_id="u1", name="Kicks", mode="build")
            db.add(project)
            await db.flush()
            snap = BuilderSnapshot(project_id=project.id, seq=1, r2_key="snap-key")
            db.add(snap)
            await db.flush()
            from app.db.models import User
            user = await db.get(User, "u1") or User(id="u1", email="u1@x.test")
            video = await video_mod.pilot(db, project, user, "anthropic/claude-fable-5.1", None,
                                          "landscape", None, snap)
            await db.commit()
            return video.id
    vid = asyncio.run(make_pilot())
    asyncio.run(video_mod._run(vid))

    async def after():
        async with maker() as db:
            return await db.get(BuilderVideo, vid), (await video_mod.allowance(db, "u1"))["used"]
    video, used = asyncio.run(after())
    assert video.status == "done" and video.paid_with == "pilot" and used == 0     # never counted
    assert all(r["model"] == "anthropic/claude-fable-5.1" for r in model.requests)
    # The stills come back to the model as images in the next message.
    last = model.requests[1]["messages"][-1]
    images = [p for p in last["content"] if p.get("type") == "image_url"]
    assert last["role"] == "user" and len(images) == 2
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "2 still(s)" in model.requests[1]["messages"][-2]["content"]


def test_view_frames_refuses_paths_outside_the_work_dir():
    text, urls = asyncio.run(video_mod._frames(VideoSandbox(), {"path": "/etc/passwd"}))
    assert text.startswith("error") and urls == []
    text, urls = asyncio.run(video_mod._frames(VideoSandbox(), {"path": "../x.mp4"}))
    assert text.startswith("error") and urls == []
