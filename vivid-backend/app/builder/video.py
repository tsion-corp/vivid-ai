"""Launch videos: a short, shareable video of a project, made from its code.

The open-source brag skill (skills/video/brag, MIT) run as a job: an agent
reads the project, plans an angle and a storyboard, writes a Hyperframes
composition (skills/video/hyperframes, Apache-2.0) and renders it with
headless Chromium and ffmpeg, in a throwaway sandbox of the vivid-video
template, which carries those and brag's music and sound effects.

Each plan includes a number of videos a month (Plan.videos_per_month); more
are paid from the project owner's wallet, refunded when a video fails or is
canceled. Model usage is recorded as kind "video", so videos never draw on
build credits.
"""
import asyncio
import base64
import io
import json
import tarfile
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import assets as assets_mod
from app.builder import blob, routing, targets, tools, usage
from app.builder.loop import ModelCall, ModelStep
from app.builder.sandbox.base import Sandbox, SandboxError
from app.builder.sandbox.manager import manager
from app.core.config import settings
from app.db.models import BuilderProject, BuilderSnapshot, BuilderVideo, User
from app.db.session import async_session
from app.services import mail, push
from app.services.models_gateway import provider
from app.services.plans import usage as plan_usage
from app.services.wallet import ledger, to_micro

log = logging.getLogger("vivid.builder.video")

QUEUED, COMPOSING, RENDERING, DONE, FAILED, CANCELED = (
    "queued", "composing", "rendering", "done", "failed", "canceled")
ACTIVE = (QUEUED, COMPOSING, RENDERING)
TONES = ("default", "polished", "yc-parody", "chaotic", "deadpan", "cinematic", "app-store")
FORMATS = {"landscape": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080)}
#: Usage kind: seen by economics, never by the plan meter (kind "model").
USAGE_KIND = "video"
VIVID = "vivid"

#: Where things are in the sandbox (the template's /home/user/app).
PROJECT_DIR, OUT_DIR, SKILLS_DIR = "project", "brag-output", "skills"
#: The skills shipped with the backend: brag, and the Hyperframes skills it uses.
SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills" / "video"
#: Put in the system prompt; everything else under skills/ the agent reads when it needs it.
#: Keep in step with sandbox-templates/vivid-video/template.py.
HYPERFRAMES_VERSION = "0.8.91"
PROMPT_SKILLS = ("brag/SKILL.md", "hyperframes/hyperframes-core/SKILL.md",
                 "hyperframes/hyperframes-cli/SKILL.md")


class VideoError(Exception):
    """A video could not be made or started; str() is safe to show."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


# ---------------------------------------------------------------- allowance
def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def allowance(db: AsyncSession, owner_id: str) -> dict:
    """The owner's videos this plan month: included, used, left, the price
    of one more, and when the count starts again."""
    account = await plan_usage.account_for(db, owner_id)
    used = (await db.execute(select(func.count()).select_from(BuilderVideo).where(
        BuilderVideo.owner_id == owner_id, BuilderVideo.created_at >= account.month_start,
        BuilderVideo.status.not_in((FAILED, CANCELED)),
        BuilderVideo.paid_with == "allowance"))).scalar_one()
    included = account.plan.videos_per_month
    resets = (_aware(account.subscription.period_end) if account.subscription
              else plan_usage._next_month(account.month_start))
    return {"plan": account.plan.id, "included": included, "used": int(used),
            "left": max(included - int(used), 0), "price_usd": settings.VIDEO_PRICE_USD,
            "resets_at": resets}


async def request(db: AsyncSession, project: BuilderProject, user: User, tone: str | None,
                  fmt: str, direction: str | None, snapshot: BuilderSnapshot) -> BuilderVideo:
    """A queued video, paid from the allowance or the owner's wallet
    (ledger.InsufficientFunds when that is short). The caller commits, then
    calls start()."""
    active = (await db.execute(select(BuilderVideo.id).where(
        BuilderVideo.project_id == project.id, BuilderVideo.status.in_(ACTIVE)))).first()
    if active:
        raise VideoError("busy", "A video of this project is already being made.", 409)
    if fmt not in FORMATS:
        raise VideoError("bad_format", "Format is landscape, vertical or square.")
    left = (await allowance(db, project.owner_id))["left"]
    video = BuilderVideo(project_id=project.id, user_id=user.id, owner_id=project.owner_id,
                         snapshot_id=snapshot.id, tone=(tone or "").strip()[:80] or None, format=fmt,
                         direction=(direction or "").strip()[:300] or None,
                         paid_with="allowance" if left > 0 else "wallet", model=settings.VIDEO_MODEL)
    db.add(video)
    await db.flush()
    if video.paid_with == "wallet":
        video.amount_micro = to_micro(settings.VIDEO_PRICE_USD)
        await ledger.debit(db, project.owner_id, video.amount_micro, ledger.VIDEO, VIVID,
                           f"video:{video.id}", ref=project.id,
                           original_amount=str(settings.VIDEO_PRICE_USD), original_currency="USD",
                           description=f"Launch video of {project.name}")
    return video


async def pilot(db: AsyncSession, project: BuilderProject, user: User, model: str,
                tone: str | None, fmt: str, direction: str | None,
                snapshot: BuilderSnapshot) -> BuilderVideo:
    """An internal test run with a chosen model (scripts/video_pilot.py): not
    charged and not counted against the owner's allowance. The caller commits,
    then calls start()."""
    if fmt not in FORMATS:
        raise VideoError("bad_format", "Format is landscape, vertical or square.")
    video = BuilderVideo(project_id=project.id, user_id=user.id, owner_id=project.owner_id,
                         snapshot_id=snapshot.id, tone=(tone or "").strip()[:80] or None, format=fmt,
                         direction=(direction or "").strip()[:300] or None,
                         paid_with="pilot", model=model)
    db.add(video)
    await db.flush()
    return video


async def _refund(db: AsyncSession, video: BuilderVideo, why: str) -> None:
    if video.paid_with == "wallet" and video.amount_micro > 0:
        await ledger.credit(db, video.owner_id, video.amount_micro, ledger.REFUND, VIVID,
                            f"video-refund:{video.id}", ref=video.project_id,
                            description=f"Launch video {why}")


async def cancel(db: AsyncSession, video: BuilderVideo) -> None:
    """Stop a video being made (refunded), or forget a finished one. The caller commits."""
    if video.status in ACTIVE:
        task = _tasks.pop(video.id, None)
        if task is not None:
            task.cancel()
        video.status, video.finished_at = CANCELED, datetime.now(timezone.utc)
        await _refund(db, video, "canceled")


async def reap(db: AsyncSession, older_than: timedelta = timedelta(minutes=45)) -> int:
    """Videos a restart left mid-way: failed and refunded. The caller commits."""
    cutoff = datetime.now(timezone.utc) - older_than
    rows = (await db.execute(select(BuilderVideo).where(
        BuilderVideo.status.in_(ACTIVE), BuilderVideo.created_at < cutoff))).scalars()
    n = 0
    for video in list(rows):
        if video.id in _tasks:
            continue
        video.status, video.error = FAILED, "It was interrupted. Try again; you were not charged."
        video.finished_at = datetime.now(timezone.utc)
        await _refund(db, video, "interrupted")
        n += 1
    return n


# ------------------------------------------------------------------- prompt
def _skill(rel: str) -> str:
    try:
        return (SKILLS_ROOT / rel).read_text(encoding="utf-8")
    except OSError:
        log.warning("video skill file missing: %s", rel)
        return ""


def skills_tarball() -> bytes:
    """The skills (a few hundred small files) as one upload."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tf:
        if SKILLS_ROOT.is_dir():
            tf.add(SKILLS_ROOT, arcname=SKILLS_DIR)
    return out.getvalue()


def system_prompt(video: BuilderVideo, project: BuilderProject) -> str:
    w, h = FORMATS[video.format]
    wishes = [f"- Format: {video.format} ({w}x{h}, 30fps)."]
    if video.format in ("vertical", "square"):
        wishes.append("- It's for phones (TikTok, Reels, Shorts, Status): show the app's MOBILE layout, built at "
                      "390 css px from its mobile classes and scaled up (references/formats.md); never shrink the desktop.")
    if video.tone:
        wishes.append(f"- Tone: {video.tone}.")
    if video.direction:
        wishes.append(f"- The person's direction: {video.direction}")
    preamble = f"""# You are making a launch video, as a job with nobody watching

Run the full /brag workflow below for the project "{project.name}", from start to finish,
without asking anything: there is no one to answer and no preview to show. Where it says to
ask the user or invite them to preview, decide yourself and go on. Skip its model check and
never switch to brag-slim: this is always the full workflow, with Hyperframes.

Where things are (paths relative to the working directory):
- The project's code: `{PROJECT_DIR}/` (read it; never change it).
- Your output directory: `{OUT_DIR}/` (brag-plan.md, composition-brief.md,
  composition/, work/). Use exactly this one; never a timestamped one.
- brag's music and sound effects: `brag-assets/music/`, `brag-assets/sfx/`,
  cue presets in `brag-assets/music/cues/`. Everything brag calls `<skill-dir>/assets/`
  is `brag-assets/`. Every other `<skill-dir>/…` path (references/, scripts/, examples/)
  is under `{SKILLS_DIR}/brag/`; its absolute form, for the `import` in `audio/score.mjs`,
  is `/home/user/app/{SKILLS_DIR}/brag/scripts/synth/index.mjs`.
- Hyperframes {HYPERFRAMES_VERSION} is installed globally: run `hyperframes <command>` (check,
  render, snapshot, tts…) rather than `npx hyperframes`, which may fetch a different version.
- Look at your work with the `view_frames` tool after every draft render (and at the poster):
  you can't judge motion, depth or framing from the code alone.
- Voiceover works offline here: `node {SKILLS_DIR}/brag/scripts/voice.mjs vo.json --out
  {OUT_DIR}/composition/assets/vo` (Kokoro is installed; no API keys).
- Before rendering, `node {SKILLS_DIR}/brag/scripts/verify-composition.mjs
  {OUT_DIR}/composition --tone <tone>` must print "passes"; fix what it names.
- The Hyperframes skills are in `{SKILLS_DIR}/hyperframes/<skill>/SKILL.md` with their
  references: read hyperframes-animation, hyperframes-creative, hyperframes-keyframes and
  hyperframes-audio there when brag says to load them.
- `hyperframes` is installed; run it with `npx hyperframes ...` from `{OUT_DIR}/composition`.
  Chromium and ffmpeg are installed. Commands may run up to {settings.VIDEO_RENDER_TIMEOUT}s.

What the person asked for:
{chr(10).join(wishes)}

Done means these exist, made the way brag's step 4 says:
- `{OUT_DIR}/brag.mp4` (the render, poster baked in as frame 0),
- `{OUT_DIR}/brag.jpg` (the poster), `{OUT_DIR}/share-copy.txt` (1-3 postable sentences).
Then reply with one sentence on the creative angle. Keep it short: 15-30 seconds of video.
"""
    parts = [preamble] + [_skill(rel) for rel in PROMPT_SKILLS]
    return "\n\n---\n\n".join(p for p in parts if p)


# -------------------------------------------------------------------- tools
_TOOL_NAMES = ("read_file", "write_file", "edit_file", "list_files", "run_command")
#: Stills the agent looks at, so it reviews the picture the way a person would.
VIEW_FRAMES = {"type": "function", "function": {
    "name": "view_frames",
    "description": ("Look at your video. Give a rendered .mp4 and up to 6 times in seconds "
                    "(stills are taken with ffmpeg), or a .png/.jpg (a snapshot or the poster). "
                    "The images come back to you in the next message. Use it after every draft "
                    "render: at each scene change (cut −0.1 / +0.1), the peaks of the pop-out, "
                    "tilt and morphs, the first and last frames."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "An .mp4, .png or .jpg under the working directory."},
        "times": {"type": "array", "items": {"type": "number"},
                  "description": "Seconds into the .mp4, up to 6."}},
        "required": ["path"]}}}
_FRAME_WIDTH = 960


def _schemas() -> list[dict]:
    return [s for s in tools.SCHEMAS if s["function"]["name"] in _TOOL_NAMES] + [VIEW_FRAMES]


async def _frames(sandbox: Sandbox, args: dict) -> tuple[str, list[str]]:
    """(text for the tool result, data URLs to show the model)."""
    path = str(args.get("path") or "").strip()
    if not path or path.startswith("/") or ".." in path.split("/"):
        return "error: give a path under the working directory", []
    lower = path.lower()
    if lower.endswith((".png", ".jpg", ".jpeg")):
        out = "/tmp/vf-0.jpg"
        result = await sandbox.run(f"ffmpeg -v error -y -i '{path}' -vf scale={_FRAME_WIDTH}:-2 -q:v 4 {out}",
                                   timeout=60)
        shots = [(None, out)] if result.ok else []
    elif lower.endswith(".mp4"):
        times = [float(t) for t in (args.get("times") or [])[:6] if isinstance(t, (int, float))] or [0.0]
        shots = []
        for i, t in enumerate(times):
            out = f"/tmp/vf-{i}.jpg"
            result = await sandbox.run(f"ffmpeg -v error -y -ss {max(t, 0):.3f} -i '{path}' -frames:v 1 "
                                       f"-vf scale={_FRAME_WIDTH}:-2 -q:v 4 {out}", timeout=60)
            if result.ok:
                shots.append((t, out))
    else:
        return "error: view_frames reads an .mp4, .png or .jpg", []
    urls, labels = [], []
    for t, out in shots:
        try:
            data = await sandbox.read_bytes(out)
        except SandboxError:
            continue
        urls.append("data:image/jpeg;base64," + base64.b64encode(data).decode())
        labels.append("image" if t is None else f"t={t:.2f}s")
    if not urls:
        return f"error: no frames could be read from {path}", []
    return f"{len(urls)} still(s) of {path} ({', '.join(labels)}) follow in the next message.", urls


def _drop_old_frames(messages: list[dict]) -> None:
    """Keep only the newest stills in the conversation, so images don't pile up."""
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            if any(p.get("type") == "image_url" for p in m["content"]):
                m["content"] = [{"type": "text", "text": "(stills you looked at earlier; removed)"}]


async def _tool(sandbox: Sandbox, name: str, args: dict) -> str:
    if name == "run_command":
        command = str(args.get("command") or "").strip()
        reason = tools.blocked_reason(command)
        if reason:
            return f"error: that command is not allowed here ({reason})."
        result = await sandbox.run(command, timeout=settings.VIDEO_RENDER_TIMEOUT)
        head = (f"[timed out after {settings.VIDEO_RENDER_TIMEOUT}s]" if result.timed_out
                else f"[exit code {result.exit_code}]")
        return tools.truncate(f"{head}\n{result.output}".strip())
    if name == "list_files":
        prefix = str(args.get("path") or ".").strip().strip("/") or "."
        if prefix.startswith("/") or ".." in prefix.split("/"):
            return "error: list files under the working directory"
        result = await sandbox.run(
            f"find {prefix} -type f -not -path '*/node_modules/*' -not -path '*/.git/*' "
            f"-not -path '*/work/*' | sort | head -400", timeout=30)
        return tools.truncate(result.output.strip() or "(no files)")
    outcome = await tools.execute(name, args, sandbox, typecheck_now=False)
    return outcome.text


# ---------------------------------------------------------------------- job
_tasks: dict[str, asyncio.Task] = {}


def start(video_id: str) -> None:
    """Make the video in the background; the row says how it went."""
    task = asyncio.get_running_loop().create_task(_run(video_id))
    _tasks[video_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(video_id, None))


async def _update(video_id: str, **fields) -> BuilderVideo | None:
    async with async_session() as db:
        video = await db.get(BuilderVideo, video_id)
        if video is None:
            return None
        for key, value in fields.items():
            setattr(video, key, value)
        await db.commit()
        return video


async def _prepare(sandbox: Sandbox, video: BuilderVideo, project: BuilderProject,
                   snapshot: BuilderSnapshot) -> None:
    """The project's files (read only, no install), its uploads, and the skills."""
    await sandbox.write_bytes("/tmp/project.tgz", await blob.get(snapshot.r2_key))
    result = await sandbox.run(
        f"mkdir -p {PROJECT_DIR} {OUT_DIR} && tar -xzf /tmp/project.tgz -C {PROJECT_DIR} "
        f"&& rm -f /tmp/project.tgz {PROJECT_DIR}/.env {PROJECT_DIR}/.env.*", timeout=120)
    if not result.ok:
        raise VideoError("prepare_failed", "The project's files could not be opened.")
    upload_dir = f"{PROJECT_DIR}/{targets.of(project).upload_dir}"
    async with async_session() as db:
        uploads = await assets_mod.list_for(db, project.id)
    for asset in uploads:
        try:
            await sandbox.write_bytes(f"{upload_dir}/{asset.name}", await blob.get(asset.r2_key))
        except (blob.BlobError, SandboxError) as e:
            log.warning("upload %s not copied for video %s: %s", asset.name, video.id, e)
    await sandbox.write_bytes("/tmp/skills.tgz", skills_tarball())
    result = await sandbox.run("tar -xzf /tmp/skills.tgz && rm -f /tmp/skills.tgz", timeout=60)
    if not result.ok:
        raise VideoError("prepare_failed", "The video tools could not be set up.")


async def _probe(sandbox: Sandbox, video: BuilderVideo) -> tuple[float | None, str | None]:
    """(duration, problem): what is wrong with the deliverables, if anything."""
    result = await sandbox.run(
        f"ffprobe -v error -select_streams v:0 -show_entries stream=width,height "
        f"-show_entries format=duration -of json {OUT_DIR}/brag.mp4", timeout=60)
    if not result.ok:
        return None, f"{OUT_DIR}/brag.mp4 is missing or unreadable"
    try:
        info = json.loads(result.stdout)
        stream_ = (info.get("streams") or [{}])[0]
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (ValueError, TypeError):
        return None, "ffprobe could not read brag.mp4"
    w, h = FORMATS[video.format]
    if (stream_.get("width"), stream_.get("height")) != (w, h):
        return duration, f"brag.mp4 is {stream_.get('width')}x{stream_.get('height')}, not {w}x{h}"
    if not 8 <= duration <= 45:
        return duration, f"brag.mp4 is {duration:.1f}s long; make it 15-30s"
    check = await sandbox.run(f"test -s {OUT_DIR}/brag.jpg && test -s {OUT_DIR}/share-copy.txt",
                              timeout=15)
    if not check.ok:
        return duration, "brag.jpg or share-copy.txt is missing"
    return duration, None


async def _agent(sandbox: Sandbox, video: BuilderVideo, project: BuilderProject,
                 calls: list[ModelCall]) -> float:
    """The brag run. Returns the video's duration once the deliverables pass."""
    endpoint = (provider.openrouter_model(video.model, context_tokens=settings.BUILDER_CONTEXT_TOKENS)
                if video.model else routing.endpoint_for(routing.VIDEO))
    fallback = routing.endpoint_for(routing.FALLBACK)
    messages: list[dict] = [{"role": "system", "content": system_prompt(video, project)},
                            {"role": "user", "content": "Make the launch video now."}]
    deadline = time.monotonic() + settings.VIDEO_TIMEOUT_SECONDS
    follow_ups = 1
    for _ in range(settings.VIDEO_MAX_STEPS):
        if time.monotonic() > deadline:
            raise VideoError("timed_out", "Making the video took too long.")
        step = ModelStep(messages, _schemas(), endpoint)
        async for _part in step.run():
            pass
        if step.failed is not None and fallback.configured and fallback.model != endpoint.model:
            endpoint = fallback                             # the next step tries the fallback
            continue
        if step.failed is not None:
            raise VideoError("model_unavailable", "The video model is unavailable. Try again later.")
        calls.append(ModelCall(endpoint.model, f"video:{video.id}", step.usage))   # traceable per video
        if not step.calls:
            messages.append({"role": "assistant", "content": step.text or "Done."})
            duration, problem = await _probe(sandbox, video)
            if problem is None:
                return duration or 0.0
            if follow_ups <= 0:
                raise VideoError("render_failed", "The video could not be finished. Try again; "
                                 "you were not charged.")
            follow_ups -= 1
            messages.append({"role": "user", "content":
                             f"Not done yet: {problem}. Fix it and finish the deliverables."})
            continue
        messages.append({"role": "assistant", "content": step.text or None, "tool_calls": [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
            for c in step.calls]})
        stills: list[str] = []
        for call in step.calls:
            if call.get("error"):
                result = f"error: {call['error']}. Call the tool again with valid JSON."
            elif call["name"] == "view_frames":
                result, urls = await _frames(sandbox, call["arguments"])
                stills += urls
            else:
                if call["name"] == "run_command" and "hyperframes render" in str(
                        call["arguments"].get("command") or ""):
                    await _update(video.id, status=RENDERING)
                result = await _tool(sandbox, call["name"], call["arguments"])
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"],
                             "content": result})
        if stills:
            _drop_old_frames(messages)
            messages.append({"role": "user", "content": [
                {"type": "text", "text": "The stills you asked for. Judge them like a motion designer: "
                                          "readable, the product filling the frame, depth visible, "
                                          "no empty or doubled frames. Fix what's wrong."},
                *({"type": "image_url", "image_url": {"url": u}} for u in stills[:6])]})
    raise VideoError("too_many_steps", "The video could not be finished. Try again; you were not charged.")


async def _run(video_id: str) -> None:
    sandbox: Sandbox | None = None
    calls: list[ModelCall] = []
    started = time.monotonic()
    project_id = None
    try:
        async with async_session() as db:
            video = await db.get(BuilderVideo, video_id)
            project = await db.get(BuilderProject, video.project_id)
            snapshot = await db.get(BuilderSnapshot, video.snapshot_id)
            project_id = project.id
            video.status = COMPOSING
            await db.commit()
        sandbox = await manager.create_fresh(f"video-{video_id}", targets.video(), wait=False)
        await _prepare(sandbox, video, project, snapshot)
        duration = await _agent(sandbox, video, project, calls)

        mp4 = await sandbox.read_bytes(f"{OUT_DIR}/brag.mp4")
        jpg = await sandbox.read_bytes(f"{OUT_DIR}/brag.jpg")
        copy = (await sandbox.read_file(f"{OUT_DIR}/share-copy.txt")).strip()[:2000]
        base = f"{settings.R2_PREFIX}projects/{project.id}/videos/{video_id}"
        await blob.put(f"{base}.mp4", mp4, content_type="video/mp4")
        await blob.put(f"{base}.jpg", jpg, content_type="image/jpeg")
        video = await _update(video_id, status=DONE, video_key=f"{base}.mp4", poster_key=f"{base}.jpg",
                              share_copy=copy, duration_s=round(duration, 2),
                              finished_at=datetime.now(timezone.utc))
        if video is not None:
            await _notify(video, project)
    except asyncio.CancelledError:
        log.info("video %s canceled", video_id)
        raise
    except VideoError as e:
        await _fail(video_id, str(e))
    except (SandboxError, blob.BlobError) as e:
        log.error("video %s failed: %s", video_id, e)
        await _fail(video_id, "The video could not be made. Try again; you were not charged.")
    except Exception:
        log.exception("video %s failed", video_id)
        await _fail(video_id, "The video could not be made. Try again; you were not charged.")
    finally:
        if sandbox is not None:
            seconds = time.monotonic() - started
            try:
                await sandbox.kill()
            except Exception:                              # already gone
                pass
            if project_id:
                await usage.record_sandbox(project_id, sandbox.id, seconds)
        if calls and project_id:
            try:
                async with async_session() as db:
                    await usage.record_model(db, project_id, calls, kind=USAGE_KIND)
                    await db.commit()
            except Exception as e:
                log.warning("video usage not recorded: %s", e)


async def _fail(video_id: str, message: str) -> None:
    async with async_session() as db:
        video = await db.get(BuilderVideo, video_id)
        if video is None or video.status not in ACTIVE:
            return
        video.status, video.error = FAILED, message[:1000]
        video.finished_at = datetime.now(timezone.utc)
        await _refund(db, video, "not made")
        await db.commit()


async def _notify(video: BuilderVideo, project: BuilderProject) -> None:
    push.send_later(video.owner_id, "Your launch video is ready",
                    f"{project.name}: a {video.duration_s or 20:.0f}s video, ready to post.",
                    {"type": "video_ready", "project_id": project.id, "video_id": video.id})
    async with async_session() as db:
        owner = await db.get(User, video.owner_id)
    if owner is None or not owner.profile_email:
        return
    link = f"{settings.WEB_BASE_URL.rstrip('/')}/projects/{project.id}?tab=video"
    poster = blob.presigned_url(video.poster_key, expires_in=7 * 24 * 3600) if video.poster_key else None
    body = (f"<p>The launch video of <b>{project.name}</b> is ready: {video.duration_s or 20:.0f} seconds, "
            "with a caption to post it with.</p>"
            + (f'<p><img src="{poster}" alt="" style="width:100%;border-radius:12px"></p>' if poster else ""))
    await mail.send(owner.profile_email, f"Your launch video of {project.name} is ready",
                    f"The launch video of {project.name} is ready. Watch and download it: {link}\n",
                    mail.layout("Your launch video is ready", body, ("Watch it", link)))


def urls(video: BuilderVideo) -> tuple[str | None, str | None]:
    week = 7 * 24 * 3600
    return (blob.presigned_url(video.video_key, expires_in=week) if video.video_key else None,
            blob.presigned_url(video.poster_key, expires_in=week) if video.poster_key else None)

