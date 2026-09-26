"""The app builder: /v1/builder.

    POST   /builder/projects                 create
    GET    /builder/projects                 mine
    GET    /builder/projects/{id}
    PATCH  /builder/projects/{id}            rename, edit the spec
    DELETE /builder/projects/{id}            also kills the sandbox
    GET    /builder/projects/{id}/messages   the thread, parts as streamed
    POST   /builder/projects/{id}/chat       one turn; answers as an AI SDK
                                             UI Message Stream (SSE). In plan
                                             mode the turn asks questions or
                                             writes the spec; no sandbox.
    POST   /builder/projects/{id}/build      leave plan mode; spec.md goes
                                             into the sandbox
    POST   /builder/projects/{id}/cancel     stop the running turn
    GET    /builder/projects/{id}/preview    the sandbox URL (starts one)
    GET    /builder/projects/{id}/files      source file list
    GET    /builder/projects/{id}/files/{path}
    PUT    /builder/projects/{id}/files/{path}   replace an image in place (multipart)
    POST   /builder/projects/{id}/images/replace  replace an image seen in the preview
    POST   /builder/projects/{id}/edits      change copy by hand, no chat turn
    GET    /builder/projects/{id}/snapshots  one per turn that changed files
    POST   /builder/projects/{id}/snapshots  take one now (after a failed auto-snapshot)
    POST   /builder/projects/{id}/undo       back to the version before the current one
    GET    /builder/projects/{id}/logs       the dev server's last lines (for a "something broke" panel)
    POST   /builder/projects/{id}/snapshots/{seq}/restore
    GET    /builder/projects/{id}/usage      this project's metered totals
    POST   /builder/projects/{id}/supabase   link a Supabase project (byo)
    DELETE /builder/projects/{id}/supabase   unlink
    POST   /builder/projects/{id}/payments   take payments with the user's Paystack
    DELETE /builder/projects/{id}/payments   stop
    POST   /builder/projects/{id}/assets     upload a logo, photo, font (multipart)
    GET    /builder/projects/{id}/assets
    DELETE /builder/projects/{id}/assets/{asset_id}
    POST   /builder/projects/{id}/auth       the app signs its users in with Decane
    DELETE /builder/projects/{id}/auth       stop (the client and its users are kept)
    POST   /builder/projects/{id}/publish    build and put the app on a live URL (202)
    GET    /builder/projects/{id}/publishes  history, newest first
    GET    /builder/projects/{id}/publishes/{publish_id}
    POST   /builder/projects/{id}/builds     build a mobile app on EAS (202)
    GET    /builder/projects/{id}/builds     history, newest first
    GET    /builder/projects/{id}/builds/{build_id}
    POST   /builder/projects/{id}/builds/{build_id}/cancel
    GET    /builder/app-builds/options       build accounts, prices, what is left

One turn per project at a time (409 otherwise). The stream is the contract
for any client: see docs/builder.md.
"""
import asyncio
import json
import pathlib
import mimetypes
import base64
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.builder import (analytics, app_build, assets, billing, blob, chain as chain_mod,
                         decane_connect, expo, images, pgdirect, planning, publish, routing,
                         secrets, skills, snapshots, stream, supabase, targets, tools, usage,
                         visual)
from app.builder.loop import FEED_DONE, ModelCall, TurnRunner, turns
from app.builder.planning import PlanRunner
from app.builder.sandbox.base import PathError, SandboxError, safe_path
from app.builder.sandbox.manager import manager
from app.core.config import settings
from app.core.errors import APIError
from app.db.models import (BuilderAppBuild, BuilderAsset, BuilderMessage, BuilderProject,
                           BuilderPublish, BuilderSnapshot, Connector, User, VividPayProject)
from app.services.connectors import supabase as supabase_connector
from app.services.plans import gate as plan_gate
from app.services.wallet import ledger
from app.services.connectors import tokens as connector_tokens
from app.db.session import async_session
from app.schemas.builder import (AnalyticsOut, AppBuildIn, AppBuildOut, AssetOut, BuildAccountOut,
                                 BuildOptionsOut, CancelOut, ChatIn, EditsIn, EditsOut, FileOut,
                                 FilesOut, ImageReplaceOut, MessageOut, PreviewOut, ProjectCreate,
                                 ProjectOut, ProjectUpdate, PublishOut, SnapshotOut, SupabaseLinkIn,
                                 TextEditOut, UsageOut)
from app.services import rate_limit
from app.services.vividpay import VividPayError, key_hash, new_key
from app.services.vividpay import payouts as vp_payouts
from app.services.models_gateway import provider

router = APIRouter(prefix="/builder", tags=["builder"])
log = logging.getLogger("vivid.builder")

#: How many turns back a touched file stays in the context block.
RECENT_TURNS = 2


async def _owned(project_id: str, user: User, db: AsyncSession) -> BuilderProject:
    project = await db.get(BuilderProject, project_id)
    if project is None or project.owner_id != user.id:
        raise APIError(404, "not_found", "Project not found")
    return project


async def _latest_seq(project_id: str, db: AsyncSession) -> int:
    row = (await db.execute(
        select(BuilderSnapshot.seq).where(BuilderSnapshot.project_id == project_id)
        .order_by(BuilderSnapshot.seq.desc()).limit(1))).scalar_one_or_none()
    return row or 0


# ------------------------------------------------------------- projects
@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    allowed, account, owned = await plan_gate.can_create_project(db, user.id)
    if not allowed:
        raise APIError(402, "plan_limit",
                       f"The {account.plan.name} plan includes {account.plan.max_apps} apps and you "
                       f"have {owned}.",
                       details={"plan": account.plan.id, "max_apps": account.plan.max_apps,
                                "apps": owned, "options": ["upgrade"]})
    project = BuilderProject(owner_id=user.id, name=body.name.strip() or "Untitled app",
                             mode="build" if body.skip_plan else "plan",
                             target=body.target)
    db.add(project)
    await db.commit()
    return project


def _require_integration(project: BuilderProject, name: str) -> None:
    """Some integrations exist only for websites so far (targets.py)."""
    target = targets.of(project)
    if name not in target.integrations:
        raise APIError(400, "not_supported",
                       f"{name.capitalize()} is not available for {target.name} projects yet.")


def _present(project: BuilderProject) -> BuilderProject:
    """Per-process state the row does not carry: whether a turn is running
    here, and a time-limited URL for the latest screenshot."""
    running = turns.running(project.id)
    project.turn_status = "running" if running else "idle"
    project.turn_started_at = turns.started_at(project.id) if running else None
    project.thumbnail_url = (blob.presigned_url(project.thumbnail_key, expires_in=7 * 24 * 3600)
                             if project.thumbnail_key and blob.configured() else None)
    return project


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(BuilderProject)
                            .where(BuilderProject.owner_id == user.id)
                            .order_by(BuilderProject.updated_at.desc()))
    return [_present(p) for p in rows.scalars()]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    return _present(await _owned(project_id, user, db))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, body: ProjectUpdate,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    if body.name is not None:
        project.name = body.name.strip() or project.name
    if body.spec_md is not None:
        project.spec_md = body.spec_md
    if body.fullstack is not None:
        project.fullstack = body.fullstack
    if body.recipe is not None:
        project.recipe = body.recipe.strip().lower() or None
    await db.commit()
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    turns.cancel(project_id)
    await manager.kill(project_id, request.app.state.redis)
    if project.decane_app_id and decane_connect.configured():
        # Archive the Decane client and revoke its keys. Best effort: an
        # outage there must not keep a project from being deleted.
        try:
            await decane_connect.deprovision(project_id)
        except decane_connect.ConnectError as e:
            log.warning("decane deprovision for %s failed: %s", project_id, e)
    _auth_synced.pop(project_id, None)
    await db.delete(project)
    await db.commit()
    await snapshots.delete_all(project_id)


# ------------------------------------------------------------- messages
@router.get("/projects/{project_id}/messages", response_model=list[MessageOut])
async def list_messages(project_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    rows = await db.execute(select(BuilderMessage)
                            .where(BuilderMessage.project_id == project_id)
                            .order_by(BuilderMessage.created_at))
    return list(rows.scalars())


def _history(messages: list[BuilderMessage]) -> list[dict]:
    """Past turns as the model sees them: prose only. Tool calls from
    earlier turns are not replayed; the context block carries the files
    they touched, and the model re-reads what it needs."""
    out = []
    for m in messages:
        text = stream.text_of(m.parts or [])
        if text:
            out.append({"role": m.role, "content": text})
    return out


def _recent(project: BuilderProject) -> list[str]:
    seen: list[str] = []
    for turn in (project.recent_files or [])[:RECENT_TURNS]:
        for path in turn:
            if path not in seen:
                seen.append(path)
    return seen


@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatIn, request: Request,
               user: User = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    """One turn. The response is `text/event-stream` in the AI SDK UI
    Message Stream (v1) shape; the user message is stored before the model
    is called and the assistant message when the stream ends."""
    project = await _owned(project_id, user, db)
    redis = request.app.state.redis
    if not await rate_limit.check_bucket(redis, f"builder:{user.id}",
                                         settings.BUILDER_RATE_LIMIT_PER_MINUTE):
        raise APIError(429, "rate_limited",
                       "Too many builder messages this minute. Please wait a moment.")
    if not routing.endpoint_for(routing.BUILD).configured:
        raise APIError(503, "not_configured", "The app builder is not configured.")
    plan_check = await plan_gate.can_start_turn(db, user.id, project_id)
    if not plan_check.ok:
        if plan_check.read_only:
            raise APIError(402, "plan_limit",
                           f"Your {plan_check.account.plan.name} plan runs "
                           f"{plan_check.account.plan.max_apps} apps at a time, and this is not "
                           "one of your most recent.",
                           details={"plan": plan_check.account.plan.id,
                                    "max_apps": plan_check.account.plan.max_apps,
                                    "read_only": True, "options": ["upgrade"]})
        raise APIError(429, "limit_reached", _limit_message(plan_check),
                       details=plan_check.body())

    rows = await db.execute(select(BuilderMessage)
                            .where(BuilderMessage.project_id == project_id)
                            .order_by(BuilderMessage.created_at))
    stored = list(rows.scalars())
    planning_mode = project.mode == "plan"
    history = planning.history_from_parts(stored) if planning_mode else _history(stored)
    stage = routing.stage_for(await _latest_seq(project_id, db))

    feed = turns.start(project_id)
    if feed is None:
        raise APIError(409, "busy", "A turn is already running for this project.")
    cancel = feed.cancel

    user_parts = [{"type": "text", "text": body.text}]
    user_parts += [{"type": "file", "mediaType": "image/*", "url": u} for u in body.images]
    user_msg = BuilderMessage(project_id=project_id, role="user", parts=user_parts)
    db.add(user_msg)
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()

    spec_md, recent = project.spec_md, _recent(project)
    payments = project.payments_provider if project.payments_provider != "none" else None
    maps = project.maps_provider if project.maps_provider != "none" else None
    auth = project.auth_provider if project.auth_provider != "none" else None
    chain = None if planning_mode else await _chain_for(project, db)
    if not planning_mode and project.recipe is None and (spec_md or project.brief_md):
        # A project that skipped plan mode still gets a recipe, chosen once.
        project.recipe = await skills.pick_recipe(spec_md or project.brief_md or "",
                                                  mobile=targets.of(project).is_mobile)
        await db.commit()
    backend = None if planning_mode else await _backend_for(project, user, db)
    env_vars = None if planning_mode else await _env_for(project, db)
    uploaded = await assets.list_for(db, project_id)
    assets_block = assets.describe(uploaded, targets.of(project))
    plan_images = list(body.images)
    if planning_mode and uploaded:
        for url in assets.image_urls(uploaded):
            if len(plan_images) < planning.MAX_IMAGES:
                plan_images.append(url)

    async def run_turn():
        """The whole turn, as a task: it outlives the HTTP connection, so a
        closed tab or a proxy timeout never loses the work or the message.
        Everything it produces goes to the feed; the response below and any
        later /chat/stream reader follow the feed."""
        collector = stream.PartsCollector()
        runner = None
        try:
            if planning_mode:
                runner = PlanRunner(history, body.text, plan_images, cancelled=cancel.is_set,
                                    assets_block=assets_block,
                                    mobile=targets.of(project).is_mobile)
                async for part in runner.run():
                    collector.add(part)
                    await feed.push(part)
                await _persist_plan_turn(project_id, collector, runner)
                turns.finish(project_id)
                await feed.push(FEED_DONE)
                return
            try:
                sandbox = await _start_sandbox(project_id, redis, targets.of(project))
                await _sync_spec(sandbox, spec_md)
                await _sync_env(sandbox, env_vars)
                await assets.sync(sandbox, uploaded)
            except (SandboxError, snapshots.SnapshotError) as e:
                log.error("sandbox for project %s failed: %s", project_id, e)
                await feed.push(stream.error(
                    "The workspace could not be started. Please try again."))
                turns.finish(project_id)
                return
            runner = TurnRunner(sandbox, stage, history, body.text, spec_md, recent,
                                cancelled=cancel.is_set, backend=backend,
                                assets_block=assets_block, payments=payments, maps=maps,
                                chain=chain, auth=auth,
                                fullstack=project.fullstack, recipe=project.recipe,
                                backend_env=bool(env_vars and targets.of(project).env("SUPABASE_URL")
                                                 in env_vars),
                                keepalive=lambda: manager.touch(project_id),
                                project_id=project_id,
                                images=(images.ImageMaker(
                                    project_id, sandbox,
                                    limit=(settings.BUILDER_IMAGES_FIRST_BUILD
                                           if stage == routing.BUILD else None))
                                        if images.available() else None))
            async for part in runner.run():
                collector.add(part)
                await feed.push(part)
        except Exception as e:                     # never a half-open stream
            log.exception("builder turn failed for project %s", project_id)
            await feed.push(stream.error(provider.scrub(str(e))))
        finally:
            if not planning_mode:
                # Stored BEFORE the terminator: a client that fetches the
                # thread the moment it sees [DONE] must find the message.
                await manager.touch(project_id)
                snapshot = await _persist_turn(project_id, collector, runner)
                if snapshot is not None:
                    await feed.push(stream.data("snapshot", {
                        "id": snapshot.id, "seq": snapshot.seq}))
                turns.finish(project_id)
                await feed.push(FEED_DONE)
            else:
                turns.finish(project_id)
                if not feed.done:
                    await feed.push(FEED_DONE)
            await _settle_plan(plan_check)
            await feed.close()

    feed.task = asyncio.create_task(run_turn())
    return StreamingResponse(_follow(feed), media_type=stream.MEDIA_TYPE,
                             headers=stream.HEADERS)


def _limit_message(check) -> str:
    m = check.meter
    if m.month_used >= m.month_limit:
        when = f"your allowance renews {m.month_resets_at:%d %b}"
    else:
        minutes = max(int((m.window_resets_at - datetime.now(timezone.utc)).total_seconds() // 60), 1)
        when = f"more credits free up in {minutes // 60}h {minutes % 60:02d}m"
    # What happened and when it frees up, nothing more: ways to get more are
    # `details.options`, which each client shows or not (a store app may not
    # point at payments outside the store).
    return f"You've used your {check.account.plan.name} plan's credits for now: {when}."


async def _settle_plan(check) -> None:
    """Tokens this turn used beyond the plan come off the extra tokens."""
    try:
        async with async_session() as db:
            await plan_gate.settle_turn(db, check)
            await db.commit()
    except Exception as e:                            # never fail a finished turn
        log.warning("could not settle plan usage: %s", e)


async def _follow(feed, start: int = 0):
    """SSE frames for a feed's parts. Ends when the feed closes; a reader
    that disconnects just stops reading, the turn keeps going."""
    async for part in feed.follow(start):
        if part is FEED_DONE:
            yield stream.DONE
            continue
        yield stream.frame(part)


@router.get("/projects/{project_id}/chat/stream")
async def chat_stream(project_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Attach to the running turn: every part it has produced so far, then
    the rest as it goes, ending with [DONE]. 204 when nothing is running
    (fetch the thread instead)."""
    await _owned(project_id, user, db)
    feed = turns.get(project_id)
    if feed is None:
        return Response(status_code=204)
    return StreamingResponse(_follow(feed), media_type=stream.MEDIA_TYPE,
                             headers=stream.HEADERS)


async def _persist_turn(project_id: str, collector: stream.PartsCollector,
                        runner: TurnRunner | None):
    """The assistant message, the usage rows and the snapshot, in one
    transaction on its own session (the request's session may be torn down
    before a streaming response finishes). Returns the snapshot row, if the
    turn changed any file."""
    if not collector.parts:
        return None
    snapshot = None
    try:
        async with async_session() as db:
            project = await db.get(BuilderProject, project_id)
            if project is None:
                return None
            db.add(BuilderMessage(project_id=project_id, role="assistant",
                                  parts=collector.parts,
                                  model=runner.result.model if runner else None))
            if runner is not None:
                if runner.result.touched:
                    recent = [runner.result.touched] + list(project.recent_files or [])
                    project.recent_files = recent[:RECENT_TURNS]
                if runner.result.thumbnail_key:
                    project.thumbnail_key = runner.result.thumbnail_key
                await usage.record_model(db, project_id, runner.result.calls)
                if runner.result.touched:
                    # A turn that changed nothing gets no version: "saved as
                    # version 1" of an untouched template misleads.
                    try:
                        # The closing summary labels the version; the turn's
                        # first words ("I'll start by reading...") do not.
                        snapshot = await snapshots.take(db, runner.sandbox, project,
                                                        runner.result.summary or collector.text())
                    except (snapshots.SnapshotError, SandboxError, Exception) as e:
                        # The message and usage still land; the next turn that
                        # changes a file snapshots this one's work too.
                        log.error("snapshot for %s failed: %s", project_id, e)
            await db.commit()
    except Exception as e:
        log.error("could not store the turn for %s: %s", project_id, e)
    return snapshot


async def _persist_plan_turn(project_id: str, collector: stream.PartsCollector,
                             runner: PlanRunner) -> None:
    if not collector.parts:
        return
    try:
        async with async_session() as db:
            project = await db.get(BuilderProject, project_id)
            if project is None:
                return
            db.add(BuilderMessage(project_id=project_id, role="assistant",
                                  parts=collector.parts, model=runner.result.model))
            if runner.result.spec_md:
                project.spec_md = runner.result.spec_md
                project.fullstack = runner.result.fullstack
                project.recipe = runner.result.recipe
                if runner.result.onchain and project.chain == "none":
                    await _enable_chain(db, project)
            if runner.result.brief_md:
                project.brief_md = runner.result.brief_md
            if planning.auto_named(project.name):
                # The plan knows the app's name; a placeholder gives way to it
                # (and the publish alias follows the name).
                name = planning.name_from_spec(runner.result.spec_md or project.spec_md,
                                               runner.result.brief_md or project.brief_md)
                if name:
                    project.name = name
            await usage.record_model(db, project_id, [
                ModelCall(model, routing.PLAN, u) for model, u in runner.result.calls])
            await db.commit()
    except Exception as e:
        log.error("could not store the plan turn for %s: %s", project_id, e)


async def _sync_spec(sandbox, spec_md: str | None) -> None:
    """spec.md in the sandbox mirrors the project's spec, so the file the
    model can read and the text in its prompt never disagree, and the next
    snapshot carries it."""
    if not spec_md:
        return
    try:
        current = await sandbox.read_file("spec.md")
    except FileNotFoundError:
        current = None
    if current != spec_md:
        await sandbox.write_file("spec.md", spec_md)


async def _sync_env(sandbox, env_vars: dict[str, str] | None) -> None:
    """The app's .env mirrors the linked backend. Not in git (the template
    ignores it), so it is rewritten on every build turn and never lands in
    a snapshot."""
    if not env_vars:
        return
    wanted = "".join(f"{k}={v}\n" for k, v in env_vars.items())
    try:
        current = await sandbox.read_file(".env")
    except FileNotFoundError:
        current = None
    if current != wanted:
        await sandbox.write_file(".env", wanted)


async def _env_for(project: BuilderProject, db: AsyncSession,
                   for_build: bool = False) -> dict[str, str] | None:
    """The app's .env: the backend's URL and publishable key, and the
    payments public key. Only values safe in a browser. `for_build`: the
    env baked into an installable mobile build, which takes real payments
    (the sandbox and Expo Go get Vivid Pay's test key)."""
    env: dict[str, str] = {}
    if project.backend_mode != "none":
        url = await secrets.get_secret(db, project.id, "SUPABASE_URL")
        anon = await secrets.get_secret(db, project.id, "SUPABASE_ANON_KEY")
        if url and anon:
            env.update({"VITE_SUPABASE_URL": url, "VITE_SUPABASE_ANON_KEY": anon})
    if project.payments_provider == "vividpay":
        pay = await db.get(VividPayProject, project.id)
        if pay is not None and pay.enabled:
            test = targets.of(project).is_mobile and not for_build
            if test and not pay.test_key:
                pay.test_key = new_key("vpk_test")
                await db.commit()
            env["VITE_VIVIDPAY_KEY"] = pay.test_key if test else pay.publishable_key
            env["VITE_VIVIDPAY_API"] = _vividpay_api()
    if project.payments_provider == "paystack":
        public = await secrets.get_secret(db, project.id, "PAYSTACK_PUBLIC_KEY")
        if public:
            env["VITE_PAYSTACK_PUBLIC_KEY"] = public
    if project.maps_provider == "google":
        key = await secrets.get_secret(db, project.id, "GOOGLE_MAPS_KEY")
        if key:
            env["VITE_GOOGLE_MAPS_KEY"] = key
    if project.chain in chain_mod.CHAINS:
        env.update(chain_mod.env_for(chain_mod.CHAINS[project.chain], project.deployer_address))
    if project.auth_provider == "decane" and project.decane_app_id:
        # Browser-public by design: the key is authorised by its origin
        # allowlist, not by secrecy.
        key = await secrets.get_secret(db, project.id, "DECANE_CLIENT_API_KEY")
        if key:
            env.update({"VITE_DECANE_APP_ID": project.decane_app_id, "VITE_DECANE_API_KEY": key})
    return _prefixed(env, targets.of(project)) or None


def _prefixed(env: dict[str, str], target: targets.Target) -> dict[str, str]:
    """Env names are written the web way (VITE_*); another target's bundler
    reads its own prefix (EXPO_PUBLIC_* for Expo)."""
    if target.env_prefix == "VITE_":
        return env
    return {(target.env_prefix + k[len("VITE_"):] if k.startswith("VITE_") else k): v
            for k, v in env.items()}


async def _supabase_connector(user_id: str, db: AsyncSession) -> Connector | None:
    return (await db.execute(
        select(Connector).where(Connector.user_id == user_id,
                                Connector.provider == "supabase"))).scalar_one_or_none()


async def _backend_for(project: BuilderProject, user: User,
                       db: AsyncSession) -> tools.Backend | None:
    """The Management API context for this turn's tools: the user's own
    connector for a byo project. A project linked with pasted keys but no
    connector gets the client env only, and no tools."""
    if project.backend_mode != "byo" or not project.supabase_project_ref:
        return None
    connector = await _supabase_connector(user.id, db)
    if connector is None:
        # No account link: a pasted connection string still gives the
        # migration tool (SQL over Postgres); functions and secrets stay off.
        dsn = await secrets.get_secret(db, project.id, "SUPABASE_DATABASE_URL")
        if dsn:
            return tools.Backend(ref=project.supabase_project_ref, database_url=dsn)
        return None
    try:
        token = await supabase_connector.access_token(db, connector)
    except supabase.SupabaseError as e:
        log.warning("supabase token refresh failed for %s: %s", user.id, e.public)
        return None
    return tools.Backend(ref=project.supabase_project_ref, token=token)


# -------------------------------------------------------------- supabase
@router.post("/projects/{project_id}/supabase", response_model=ProjectOut)
async def link_supabase(project_id: str, body: SupabaseLinkIn, request: Request,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Point this project at a Supabase project of the user's.

    With a Supabase connector, `project_ref` is enough: the keys are read
    through the Management API and the builder's migration, function and
    secret tools become available. Without one, `url` and `anon_key` can
    be pasted: the app gets its client env, the tools stay off.
    """
    project = await _owned(project_id, user, db)
    if not secrets.configured():
        raise APIError(503, "not_configured", "Secrets storage is not configured.")
    connector = await _supabase_connector(user.id, db)
    if connector is not None and not body.anon_key:
        try:
            token = await supabase_connector.access_token(db, connector)
            api = supabase.Management(token)
            known = {p.ref for p in await api.projects()}
            if body.project_ref not in known:
                raise APIError(404, "not_found",
                               "That Supabase project is not in the connected account.")
            keys = await api.api_keys(body.project_ref)
        except supabase.SupabaseError as e:
            raise APIError(502, "upstream_error", f"Supabase: {e.public}")
        url, anon = keys["url"], keys["anon"]
    else:
        if not body.anon_key:
            raise APIError(400, "bad_request",
                           "Connect Supabase first, or pass url and anon_key.")
        url = body.url or f"https://{body.project_ref}.supabase.co"
        anon = body.anon_key
    if body.database_url:
        try:
            await pgdirect.verify(body.database_url)
        except pgdirect.DirectError as e:
            raise APIError(400, "bad_request", f"Could not connect to the database: {e}")
        await secrets.set_secret(db, project_id, "SUPABASE_DATABASE_URL", body.database_url)
    await secrets.set_secret(db, project_id, "SUPABASE_URL", url)
    await secrets.set_secret(db, project_id, "SUPABASE_ANON_KEY", anon)
    project.backend_mode = "byo"
    project.supabase_project_ref = body.project_ref
    await db.commit()
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        await _sync_env(sandbox, _prefixed({"VITE_SUPABASE_URL": url, "VITE_SUPABASE_ANON_KEY": anon},
                                           targets.of(project)))
    return project


# -------------------------------------------------------------- payments
async def _paystack_connector(user_id: str, db: AsyncSession) -> Connector | None:
    return (await db.execute(
        select(Connector).where(Connector.user_id == user_id,
                                Connector.provider == "paystack"))).scalar_one_or_none()


def _not_vividpay(project: BuilderProject) -> None:
    """The Paystack routes never touch a project that takes Vivid Pay:
    switching providers is turning Vivid Pay off first, on purpose."""
    if project.payments_provider == "vividpay":
        raise APIError(409, "vividpay_enabled",
                       "This app takes payments with Vivid Pay. Turn Vivid Pay off first to use Paystack.")


@router.post("/projects/{project_id}/payments", response_model=ProjectOut)
async def enable_payments(project_id: str, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Take payments with the user's connected Paystack account. The public
    key goes into the app's .env; with a Supabase backend the secret key
    goes into that project's edge-function secrets, never into the app."""
    project = await _owned(project_id, user, db)
    _require_integration(project, "payments")
    _not_vividpay(project)
    if not secrets.configured():
        raise APIError(503, "not_configured", "Secrets storage is not configured.")
    connector = await _paystack_connector(user.id, db)
    if connector is None:
        raise APIError(400, "bad_request", "Connect a Paystack account first.")
    public = (connector.config_json or {}).get("public_key")
    if not public:
        raise APIError(400, "bad_request", "The Paystack connector has no public key.")
    await secrets.set_secret(db, project_id, "PAYSTACK_PUBLIC_KEY", public)
    project.payments_provider = "paystack"
    await db.commit()
    backend = await _backend_for(project, user, db)
    if backend is not None and backend.can_functions:
        # Only a management token can set function secrets; a database-only
        # link leaves the secret to the README the build writes.
        try:
            await backend.api.set_secrets(
                backend.ref, {"PAYSTACK_SECRET_KEY": connector_tokens.read(connector.token)})
        except supabase.SupabaseError as e:
            log.warning("could not set PAYSTACK_SECRET_KEY on %s: %s", backend.ref, e.public)
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        await _sync_env(sandbox, await _env_for(project, db))
    return project


@router.delete("/projects/{project_id}/payments", response_model=ProjectOut)
async def disable_payments(project_id: str, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    _not_vividpay(project)
    project.payments_provider = "none"
    await secrets.delete_secret(db, project_id, "PAYSTACK_PUBLIC_KEY")
    await db.commit()
    return project


# -------------------------------------------------------------- vivid pay
def _vividpay_api() -> str:
    return (settings.VIVIDPAY_API_BASE or settings.PUBLIC_BASE_URL).rstrip("/") + "/v1/pay"


class VividPayIn(BaseModel):
    #: The app's server side (a Supabase edge function) told about paid
    #: checkouts, signed with the secret key. Optional.
    webhook_url: str | None = Field(default=None, max_length=512)


def _vividpay_out(pay: VividPayProject, secret_key: str | None = None) -> dict:
    out = {"enabled": pay.enabled, "publishable_key": pay.publishable_key, "test_key": pay.test_key,
           "webhook_url": pay.webhook_url, "api": _vividpay_api(),
           "fee_bps": settings.VIVIDPAY_FEE_BPS, "min_fee_kobo": settings.VIVIDPAY_MIN_FEE_KOBO,
           "fee_cap_kobo": settings.VIVIDPAY_FEE_CAP_KOBO, "fixed_fee_kobo": settings.VIVIDPAY_FIXED_FEE_KOBO, "crypto": settings.VIVIDPAY_CRYPTO_ENABLED}
    if secret_key:
        out["secret_key"] = secret_key                 # shown once, when it is made
    return out


@router.get("/projects/{project_id}/vivid-pay")
async def get_vivid_pay(project_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    pay = await db.get(VividPayProject, project_id)
    if pay is None:
        return {"enabled": False, "fee_bps": settings.VIVIDPAY_FEE_BPS,
                "min_fee_kobo": settings.VIVIDPAY_MIN_FEE_KOBO,
                "fee_cap_kobo": settings.VIVIDPAY_FEE_CAP_KOBO, "fixed_fee_kobo": settings.VIVIDPAY_FIXED_FEE_KOBO, "crypto": settings.VIVIDPAY_CRYPTO_ENABLED}
    return _vividpay_out(pay)


@router.post("/projects/{project_id}/vivid-pay")
async def enable_vivid_pay(project_id: str, body: VividPayIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """Take payments by bank transfer with Vivid Pay: the owner's earnings
    account is opened, the app gets a publishable key in its .env, and the
    secret key (returned once) goes to the Supabase project when linked."""
    project = await _owned(project_id, user, db)
    _require_integration(project, "vividpay")
    if not settings.VIVIDPAY_ENABLED or not secrets.configured():
        raise APIError(503, "not_configured", "Payments are not set up on this server.")
    if body.webhook_url and not body.webhook_url.startswith("https://"):
        raise APIError(400, "bad_request", "The webhook URL must be https.")
    try:
        await vp_payouts.ensure_earnings_account(db, user)
    except VividPayError as e:
        raise APIError(e.status, e.code, str(e))
    pay = await db.get(VividPayProject, project_id)
    secret_key = None
    if pay is None:
        secret_key = new_key("vsk")
        pay = VividPayProject(project_id=project_id, owner_id=user.id,
                              publishable_key=new_key("vpk"), test_key=new_key("vpk_test"),
                              secret_key_enc=secrets.encrypt(secret_key),
                              secret_key_hash=key_hash(secret_key))
        db.add(pay)
    pay.enabled = True
    pay.test_key = pay.test_key or new_key("vpk_test")
    if body.webhook_url is not None:
        pay.webhook_url = body.webhook_url or None
    project.payments_provider = "vividpay"
    await db.commit()
    backend = await _backend_for(project, user, db)
    if backend is not None and backend.can_functions:
        try:
            await backend.api.set_secrets(backend.ref, {
                "VIVIDPAY_SECRET_KEY": secret_key or secrets.decrypt(pay.secret_key_enc)})
        except supabase.SupabaseError as e:
            log.warning("could not set VIVIDPAY_SECRET_KEY on %s: %s", backend.ref, e.public)
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        await _sync_env(sandbox, await _env_for(project, db))
    return _vividpay_out(pay, secret_key)


@router.delete("/projects/{project_id}/vivid-pay", status_code=204)
async def disable_vivid_pay(project_id: str, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Stop taking new payments. Keys and earnings are kept; checkouts
    already open can still be paid, and that money is still the owner's."""
    project = await _owned(project_id, user, db)
    pay = await db.get(VividPayProject, project_id)
    if pay is not None:
        pay.enabled = False
    if project.payments_provider == "vividpay":
        project.payments_provider = "none"
    await db.commit()


# ----------------------------------------------------------------- chain
async def _chain_for(project: BuilderProject, db: AsyncSession) -> chain_mod.Chain | None:
    if project.chain not in chain_mod.CHAINS or not project.deployer_address:
        return None
    key = await secrets.get_secret(db, project.id, "CHAIN_DEPLOYER_KEY")
    if not key:
        return None
    return chain_mod.Chain(key=project.chain, deployer_key=key,
                           deployer_address=project.deployer_address)


async def _enable_chain(db: AsyncSession, project: BuilderProject) -> None:
    """A deployer wallet for the project, funded from the faucet when it
    answers; the app's .env gets the chain values on the next turn."""
    spec = chain_mod.ARK
    key, address = chain_mod.generate_deployer()
    await secrets.set_secret(db, project.id, "CHAIN_DEPLOYER_KEY", key)
    project.chain = spec["key"]
    project.deployer_address = address
    try:
        await chain_mod.fund(spec, address)
    except ValueError as e:
        log.warning("faucet for %s did not fund %s: %s", project.id, address, e)


@router.post("/projects/{project_id}/chain", response_model=ProjectOut)
async def enable_chain(project_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Make the project a dApp on Ark Constellation: a deployer wallet is
    created and funded, the deploy tools and the web3 skill switch on."""
    project = await _owned(project_id, user, db)
    _require_integration(project, "chain")
    if not secrets.configured():
        raise APIError(503, "not_configured", "Secrets storage is not configured.")
    if project.chain == "none":
        await _enable_chain(db, project)
    await db.commit()
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        await _sync_env(sandbox, await _env_for(project, db))
    return _present(project)


@router.post("/projects/{project_id}/chain/faucet", response_model=ProjectOut)
async def fund_chain(project_id: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    if project.chain not in chain_mod.CHAINS or not project.deployer_address:
        raise APIError(400, "bad_request", "The project is not on-chain.")
    try:
        await chain_mod.fund(chain_mod.CHAINS[project.chain], project.deployer_address)
    except ValueError as e:
        raise APIError(502, "upstream_error", f"The faucet refused: {e}")
    return _present(project)


@router.delete("/projects/{project_id}/chain", response_model=ProjectOut)
async def disable_chain(project_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    project.chain = "none"
    project.deployer_address = None
    await secrets.delete_secret(db, project_id, "CHAIN_DEPLOYER_KEY")
    await db.commit()
    return _present(project)


# ------------------------------------------------------------------ auth
#: The project's Decane key, its id and the client ref (the project id).
_AUTH_SECRETS = ("DECANE_CLIENT_API_KEY", "DECANE_CLIENT_KEY_ID", "DECANE_CLIENT_REF")
#: Preview hosts on the key, newest first; the published host comes from the row.
_AUTH_HOSTS = "DECANE_CLIENT_HOSTS"
#: The preview host each project's key was last synced for, in this process,
#: so a sandbox is synced once rather than on every request that starts it.
_auth_synced: dict[str, str] = {}


def _connect_error(e: decane_connect.ConnectError) -> APIError:
    if e.kind == "bad_request":
        return APIError(400, "bad_request", f"Decane: {e}")
    if e.kind == "not_configured":
        return APIError(503, "not_configured", str(e))
    return APIError(502, "upstream_error", str(e))


async def _sync_auth_origins(db: AsyncSession, project: BuilderProject,
                             preview_host: str | None = None) -> bool:
    """Tell the project's key which hosts may sign in: the published one,
    this preview and the previous preview. A new sandbox is a new preview
    host, and publishing adds the published one and moves the Google
    callback to it. Never raises: a failure only means sign-in answers
    "origin not allowed" until the next sync."""
    if project.auth_provider != "decane" or not decane_connect.configured():
        return True
    key_id = await secrets.get_secret(db, project.id, "DECANE_CLIENT_KEY_ID")
    if not key_id:
        return True
    ref = await secrets.get_secret(db, project.id, "DECANE_CLIENT_REF") or project.id
    previews = json.loads(await secrets.get_secret(db, project.id, _AUTH_HOSTS) or "[]")
    if preview_host:
        previews = [preview_host] + [h for h in previews if h != preview_host]
    previews = previews[:2]
    origins, callback = decane_connect.origins_for(project.published_url, previews)
    if not origins:
        return True
    try:
        await decane_connect.update_key(ref, key_id, origins, callback)
    except decane_connect.ConnectError as e:
        log.warning("decane origins for %s not updated: %s", project.id, e)
        return False
    await secrets.set_secret(db, project.id, _AUTH_HOSTS, json.dumps(previews))
    await db.commit()
    return True


async def _sync_auth_for_sandbox(project_id: str, sandbox) -> None:
    host = decane_connect.host_of(sandbox.preview_url())
    if not host or _auth_synced.get(project_id) == host:
        return
    try:
        async with async_session() as db:
            project = await db.get(BuilderProject, project_id)
            ok = project is None or await _sync_auth_origins(db, project, host)
    except Exception:                               # never fails a request
        log.exception("decane origin sync for %s failed", project_id)
        return
    if ok:
        _auth_synced[project_id] = host


@router.post("/projects/{project_id}/auth", response_model=ProjectOut)
async def enable_auth(project_id: str, request: Request,
                      user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Give the app its own sign-in: a Decane client for this project (its
    own user pool) and a key allowed on the preview and the published site.
    The app's .env gets the app id and key; the auth skill rides every turn."""
    project = await _owned(project_id, user, db)
    _require_integration(project, "auth")
    if not secrets.configured() or not decane_connect.configured():
        raise APIError(503, "not_configured", "Decane sign-in is not configured.")
    if (project.auth_provider == "decane"
            and await secrets.get_secret(db, project_id, "DECANE_CLIENT_API_KEY")):
        return _present(project)

    sandbox = manager.peek(project_id)
    if sandbox is None and not project.published_url:
        sandbox = await _sandbox(project_id, request)   # the key needs at least one host
    preview = decane_connect.host_of(sandbox.preview_url()) if sandbox is not None else None
    previews = [preview] if preview else []
    origins, callback = decane_connect.origins_for(project.published_url, previews)
    try:
        app_id, minted = await decane_connect.create_client(project_id, project.name, origins, callback)
        if minted is None:
            # The client exists (a retry, or re-enabling): its first key
            # cannot be read back, so this project gets a new one.
            minted = await decane_connect.mint_key(project_id, origins, callback)
    except decane_connect.ConnectError as e:
        raise _connect_error(e)
    try:
        await secrets.set_secret(db, project_id, "DECANE_CLIENT_API_KEY", minted.key)
        await secrets.set_secret(db, project_id, "DECANE_CLIENT_KEY_ID", minted.id)
        await secrets.set_secret(db, project_id, "DECANE_CLIENT_REF", project_id)
        await secrets.set_secret(db, project_id, _AUTH_HOSTS, json.dumps(previews))
        project.auth_provider = "decane"
        project.decane_app_id = app_id
        await db.commit()
    except Exception:
        # The key is shown once. Unrecorded, it would be a live credential
        # nobody holds, and the next attempt would mint another.
        await db.rollback()
        try:
            await decane_connect.revoke_key(project_id, minted.id)
        except decane_connect.ConnectError as e:
            log.error("could not revoke unrecorded decane key for %s: %s", project_id, e)
        log.exception("storing the decane key for %s failed", project_id)
        raise APIError(503, "storage_unavailable", "Sign-in could not be saved. Try again.")
    if preview:
        _auth_synced[project_id] = preview
    if sandbox is not None:
        await _sync_env(sandbox, await _env_for(project, db))
    return _present(project)


@router.delete("/projects/{project_id}/auth", response_model=ProjectOut)
async def disable_auth(project_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Stop the app's sign-in: its key is revoked. The client and its users
    stay (Connect has no un-archive), so turning it back on finds them."""
    project = await _owned(project_id, user, db)
    key_id = await secrets.get_secret(db, project_id, "DECANE_CLIENT_KEY_ID")
    ref = await secrets.get_secret(db, project_id, "DECANE_CLIENT_REF") or project_id
    if key_id and decane_connect.configured():
        try:
            await decane_connect.revoke_key(ref, key_id)
        except decane_connect.ConnectError as e:
            log.warning("revoking the decane key for %s failed: %s", project_id, e)
    for name in (*_AUTH_SECRETS, _AUTH_HOSTS):
        await secrets.delete_secret(db, project_id, name)
    project.auth_provider = "none"
    await db.commit()
    _auth_synced.pop(project_id, None)
    return _present(project)


# ------------------------------------------------------------------ maps
async def _maps_connector(user_id: str, db: AsyncSession) -> Connector | None:
    return (await db.execute(
        select(Connector).where(Connector.user_id == user_id,
                                Connector.provider == "google_maps"))).scalar_one_or_none()


@router.post("/projects/{project_id}/maps", response_model=ProjectOut)
async def enable_maps(project_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Address autocomplete, maps and distance with the user's Google Maps
    key. It is a browser key, so it goes into the app's .env."""
    project = await _owned(project_id, user, db)
    _require_integration(project, "maps")
    if not secrets.configured():
        raise APIError(503, "not_configured", "Secrets storage is not configured.")
    connector = await _maps_connector(user.id, db)
    if connector is None:
        raise APIError(400, "bad_request", "Connect a Google Maps key first.")
    await secrets.set_secret(db, project_id, "GOOGLE_MAPS_KEY",
                             connector_tokens.read(connector.token))
    project.maps_provider = "google"
    await db.commit()
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        await _sync_env(sandbox, await _env_for(project, db))
    return project


@router.delete("/projects/{project_id}/maps", response_model=ProjectOut)
async def disable_maps(project_id: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    project.maps_provider = "none"
    await secrets.delete_secret(db, project_id, "GOOGLE_MAPS_KEY")
    await db.commit()
    return project


@router.delete("/projects/{project_id}/supabase", response_model=ProjectOut)
async def unlink_supabase(project_id: str, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    project.backend_mode = "none"
    project.supabase_project_ref = None
    await secrets.delete_secret(db, project_id, "SUPABASE_URL")
    await secrets.delete_secret(db, project_id, "SUPABASE_ANON_KEY")
    await db.commit()
    return project


# ---------------------------------------------------------------- assets
def _asset_out(asset: BuilderAsset, target: targets.Target | None = None) -> AssetOut:
    out = AssetOut.model_validate(asset)
    out.path = assets.public_path(asset, target)
    try:
        out.url = blob.presigned_url(asset.r2_key)
    except Exception as e:                       # the store is down; the row still lists
        log.warning("could not presign asset %s: %s", asset.id, e)
    return out


@router.post("/projects/{project_id}/assets", response_model=AssetOut, status_code=201)
async def upload_asset(project_id: str, request: Request, file: UploadFile = File(...),
                       user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Give the builder a file. It lands in the app at /uploads/<name> (a
    live sandbox gets it at once; a fresh one on start), and the model is
    told about it in every turn."""
    project = await _owned(project_id, user, db)
    data = await file.read()
    try:
        asset = await assets.add(db, project_id, file.filename or "file",
                                 file.content_type or "", data)
    except assets.AssetError as e:
        raise APIError(400, "bad_asset", str(e))
    except blob.BlobError as e:
        log.error("asset upload to the store failed: %s", e)
        raise APIError(503, "storage_unavailable", "The file could not be stored. Try again.")
    await db.commit()
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        try:
            await assets.write_into(sandbox, asset, data)
        except SandboxError as e:
            log.warning("asset %s not written to the live sandbox: %s", asset.name, e)
    return _asset_out(asset, targets.of(project))


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
async def list_assets(project_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    project = await _owned(project_id, user, db)
    return [_asset_out(a, targets.of(project)) for a in await assets.list_for(db, project_id)]


@router.delete("/projects/{project_id}/assets/{asset_id}", status_code=204)
async def delete_asset(project_id: str, asset_id: str,
                       user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    asset = await db.get(BuilderAsset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise APIError(404, "not_found", "No such file")
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        await sandbox.run(f"rm -f {assets.sandbox_path(asset, sandbox.target)}", timeout=15)
    await db.delete(asset)
    await db.commit()
    await blob.delete_prefix(asset.r2_key)


# ------------------------------------------------------------ app builds
#: Build starts in flight (the upload to EAS), kept so they are not collected.
_app_builds: dict[str, asyncio.Task] = {}


async def _build_account(db: AsyncSession, user: User, wanted: str) -> str:
    """auto: the user's connected Expo account if there is one, else Vivid's."""
    if wanted != "auto":
        return wanted
    return (billing.USER if await app_build.user_connector(db, user.id) is not None
            else billing.VIVID)


@router.get("/app-builds/options", response_model=BuildOptionsOut)
async def build_options(user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """The accounts a mobile build can run on, what each costs and whether it
    is available: for the build button and its price."""
    connector = await app_build.user_connector(db, user.id)
    used = await billing.vivid_builds_this_month(db, user.id)
    cap = settings.EAS_VIVID_BUILDS_PER_MONTH
    capped = cap > 0 and used >= cap
    vivid_ready = bool(settings.EXPO_TOKEN and settings.EXPO_OWNER)
    balance = await ledger.balance(db, user.id)
    await db.commit()
    vivid = BuildAccountOut(
        id="vivid", available=vivid_ready and not capped,
        price_android=billing.price_for("android", billing.VIVID),
        price_ios=billing.price_for("ios", billing.VIVID),
        currency="USD", remaining=max(cap - used, 0) if cap > 0 else None,
        balance=balance,
        reason=None if vivid_ready and not capped else
        ("not_configured" if not vivid_ready else "payment_required"))
    mine = BuildAccountOut(
        id="user", available=connector is not None,
        currency="USD",
        owner=((connector.config_json or {}).get("owner") if connector else None),
        reason=None if connector else "not_connected")
    return BuildOptionsOut(default="user" if connector else "vivid", accounts=[vivid, mine])


@router.post("/projects/{project_id}/builds", response_model=AppBuildOut, status_code=202)
async def start_app_build(project_id: str, body: AppBuildIn,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Build the mobile app's current version on EAS. The row comes back
    `starting`; poll it until `finished` (with `artifact_url`), `failed` or
    `canceled`. On Vivid's account the build is charged, and refunded if it
    fails."""
    project = await _owned(project_id, user, db)
    if not targets.of(project).is_mobile:
        raise APIError(400, "not_supported", "Only mobile projects have app builds. "
                                             "Publish a website instead.")
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    snapshot = await snapshots.current(db, project)
    if snapshot is None:
        raise APIError(409, "no_snapshot", "Build the app in the chat before making an installable build.")
    account = await _build_account(db, user, body.account)
    if account == billing.USER and await app_build.user_connector(db, user.id) is None:
        raise APIError(400, "not_connected", "Connect your Expo account first.")
    if body.platform == "ios" and body.profile == "production" and account != billing.USER:
        raise APIError(400, "needs_own_account",
                       "iOS store builds need your own Expo account with your Apple developer "
                       "credentials set up there. Connect it, or make an iOS preview build.")
    running = (await db.execute(select(BuilderAppBuild.id).where(
        BuilderAppBuild.project_id == project_id, BuilderAppBuild.platform == body.platform,
        BuilderAppBuild.status.in_(app_build.ACTIVE)))).first()
    if running is not None:
        raise APIError(409, "busy", f"An {body.platform} build is already running for this app.")
    decision = await billing.can_start_build(db, user.id, body.platform, account)
    if not decision.ok:
        raise APIError(503 if decision.code == "not_configured" else 402,
                       decision.code, decision.message)
    build = BuilderAppBuild(project_id=project_id, snapshot_id=snapshot.id,
                            platform=body.platform, profile=body.profile, account=account)
    db.add(build)
    await db.flush()
    try:
        await billing.charge(db, build, user.id)
    except ledger.InsufficientFunds:
        await db.rollback()
        raise APIError(402, "insufficient_funds", "Your wallet no longer covers this build.")
    await db.commit()
    task = asyncio.create_task(app_build.start(build.id))
    _app_builds[build.id] = task
    task.add_done_callback(lambda _t, bid=build.id: _app_builds.pop(bid, None))
    return build


@router.get("/projects/{project_id}/builds", response_model=list[AppBuildOut])
async def list_app_builds(project_id: str, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    rows = await db.execute(select(BuilderAppBuild)
                            .where(BuilderAppBuild.project_id == project_id)
                            .order_by(BuilderAppBuild.created_at.desc()).limit(50))
    return list(rows.scalars())


async def _owned_build(project_id: str, build_id: str, user: User,
                       db: AsyncSession) -> BuilderAppBuild:
    await _owned(project_id, user, db)
    build = await db.get(BuilderAppBuild, build_id)
    if build is None or build.project_id != project_id:
        raise APIError(404, "not_found", "No such build")
    return build


@router.get("/projects/{project_id}/builds/{build_id}", response_model=AppBuildOut)
async def get_app_build(project_id: str, build_id: str,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """The build as last seen; a build in flight is refreshed from Expo first,
    so polling this is enough without waiting for the timer."""
    build = await _owned_build(project_id, build_id, user, db)
    if build.status in app_build.ACTIVE and build.eas_build_id:
        try:
            await app_build.refresh(db, build, user.id)
            await db.commit()
        except (expo.ExpoError, app_build.BuildError) as e:
            log.warning("could not refresh app build %s: %s", build_id, e)
    return build


@router.post("/projects/{project_id}/builds/{build_id}/cancel", response_model=AppBuildOut)
async def cancel_app_build(project_id: str, build_id: str,
                           user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    build = await _owned_build(project_id, build_id, user, db)
    try:
        await app_build.cancel(db, build, user.id)
    except (expo.ExpoError, app_build.BuildError) as e:
        raise APIError(502, "upstream_error", f"Could not cancel the build: {e}")
    await db.commit()
    return build


# --------------------------------------------------------------- publish
#: Publish jobs in flight, so a crash in one is logged and a second click
#: while one runs is refused.
_publishing: dict[str, asyncio.Task] = {}


@router.post("/projects/{project_id}/publish", response_model=PublishOut, status_code=202)
async def start_publish(project_id: str, request: Request,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Build the current files and put them on the project's live URL. The
    row comes back `pending`; poll it until `live` or `failed`."""
    project = await _owned(project_id, user, db)
    if targets.of(project).is_mobile:
        raise APIError(400, "not_supported",
                       "Mobile apps are not published as websites. Start a build instead "
                       "(POST /builds).")
    if not publish.configured():
        raise APIError(503, "not_configured", "Publishing is not configured.")
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    if project_id in _publishing and not _publishing[project_id].done():
        raise APIError(409, "busy", "A publish is already running for this project.")
    # current(), not the column: projects built before the column was kept
    # up to date have snapshots but a null current_snapshot_id.
    snapshot = await snapshots.current(db, project)
    if snapshot is None:
        # Nothing has been built: publishing the empty template would put
        # "Your app starts here" on a real URL and call the project live.
        raise APIError(409, "nothing_to_publish", "Build the app before publishing it.")
    row = BuilderPublish(project_id=project_id, snapshot_id=snapshot.id, status="pending")
    db.add(row)
    await db.commit()
    alias = publish.alias_for(project.name, project.id)
    _publishing[project_id] = asyncio.create_task(
        _run_publish(project_id, row.id, alias, request.app.state.redis))
    return row


async def _run_publish(project_id: str, publish_id: str, alias: str, redis) -> None:
    async def update(**fields):
        async with async_session() as db:
            row = await db.get(BuilderPublish, publish_id)
            if row is None:
                return
            for k, v in fields.items():
                setattr(row, k, v)
            if fields.get("status") == "live":
                project = await db.get(BuilderProject, project_id)
                if project is not None:
                    project.published_url = fields.get("url")
                    project.published_at = datetime.now(timezone.utc)
            await db.commit()

    try:
        await update(status="building")
        sandbox = await _start_sandbox(project_id, redis)
        site = await publish.build_site(sandbox, project_id)
        await manager.touch(project_id)
        pages = publish.Pages()
        await pages.deploy(site, alias, f"vivid publish {publish_id[:8]}")
        url = publish.public_url(alias)
        await publish.wait_until_live(url)
        await update(status="live", url=url)
        log.info("project %s published at %s", project_id, url)
        try:
            async with async_session() as db:
                project = await db.get(BuilderProject, project_id)
                if project is not None:
                    await _sync_auth_origins(db, project)   # the published host, and the callback
        except Exception:
            log.exception("decane origin sync after publish of %s failed", project_id)
    except (publish.PublishError, SandboxError, snapshots.SnapshotError) as e:
        await update(status="failed", error=str(e)[:2000])
    except Exception as e:                          # never a stuck "building"
        log.exception("publish %s failed", publish_id)
        await update(status="failed", error=provider.scrub(str(e))[:500])
    finally:
        _publishing.pop(project_id, None)


@router.get("/projects/{project_id}/publishes", response_model=list[PublishOut])
async def list_publishes(project_id: str, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    rows = await db.execute(select(BuilderPublish)
                            .where(BuilderPublish.project_id == project_id)
                            .order_by(BuilderPublish.created_at.desc()))
    return list(rows.scalars())


@router.get("/projects/{project_id}/publishes/{publish_id}", response_model=PublishOut)
async def get_publish(project_id: str, publish_id: str,
                      user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    row = await db.get(BuilderPublish, publish_id)
    if row is None or row.project_id != project_id:
        raise APIError(404, "not_found", "No such publish")
    return row


@router.post("/projects/{project_id}/build", response_model=ProjectOut)
async def start_build(project_id: str, request: Request,
                      user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Leave plan mode. The spec, if any, is what the builder works to; a
    project may also start building with no spec at all."""
    project = await _owned(project_id, user, db)
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    if project.mode != "build":
        project.mode = "build"
        await db.commit()
    return project


@router.post("/projects/{project_id}/cancel", response_model=CancelOut)
async def cancel_turn(project_id: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    return CancelOut(cancelled=turns.cancel(project_id))


# -------------------------------------------------------------- preview
@router.get("/projects/{project_id}/preview", response_model=PreviewOut)
async def preview(project_id: str, request: Request,
                  user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    sandbox = await _sandbox(project_id, request)
    try:
        await visual.ensure_editor(sandbox)
    except SandboxError as e:                       # the preview works without it
        log.warning("editor not placed in %s: %s", project_id, e)
    return PreviewOut(url=sandbox.preview_url(), sandbox_id=sandbox.id,
                      driver=sandbox.driver, target=sandbox.target.name,
                      device_url=_device_url(sandbox))


@router.get("/projects/{project_id}/files", response_model=FilesOut)
async def list_files(project_id: str, request: Request,
                     user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    sandbox = await _sandbox(project_id, request)
    return FilesOut(files=await sandbox.list_files())


@router.get("/projects/{project_id}/files/{path:path}", response_model=FileOut)
async def read_file(project_id: str, path: str, request: Request,
                    user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    try:
        clean = safe_path(path)
    except PathError as e:
        raise APIError(400, "bad_path", str(e))
    sandbox = await _sandbox(project_id, request)
    raw = request.query_params.get("raw") in ("1", "true")
    try:
        data = await sandbox.read_bytes(clean)
    except FileNotFoundError:
        raise APIError(404, "not_found", "File not found")
    binary = _is_binary(clean, data)
    ctype = mimetypes.guess_type(clean)[0] or ("application/octet-stream" if binary else "text/plain")
    if raw:
        return Response(content=data, media_type=ctype)
    if binary:
        return FileOut(path=clean, content="", binary=True,
                       content_base64=base64.b64encode(data).decode(), content_type=ctype)
    return FileOut(path=clean, content=data.decode("utf-8", errors="replace"),
                   content_type=ctype)


# ---------------------------------------------------------- visual edits
#: One hand edit at a time per project, so two never race a snapshot.
_editing: dict[str, asyncio.Lock] = {}


async def _hand_edit_target(project_id: str, user: User, db: AsyncSession) -> BuilderProject:
    project = await _owned(project_id, user, db)
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    if await snapshots.current(db, project) is None:
        raise APIError(409, "nothing_to_edit", "Build the app before editing it.")
    return project


async def _save_hand_edit(db: AsyncSession, sandbox, project: BuilderProject,
                          summary: str) -> BuilderSnapshot | None:
    """A version for the edit, like a turn's. A failure to store it does not
    undo the edit, which is already in the preview; the client is told."""
    try:
        row = await snapshots.take(db, sandbox, project, summary)
        await db.commit()
    except (snapshots.SnapshotError, SandboxError) as e:
        log.error("snapshot after a hand edit in %s failed: %s", project.id, e)
        await db.rollback()
        return None
    await manager.touch(project.id)
    return row or await snapshots.latest(db, project.id)


async def _write_image(db: AsyncSession, project_id: str, sandbox, path: str, data: bytes) -> None:
    """The picture at `path` becomes `data`. Generated pictures and uploads
    (public/uploads) are also stored outside the sandbox and copied back in
    when one starts, so the stored copy changes too or the old one returns."""
    asset = await assets.by_sandbox_path(db, project_id, path)
    if asset is not None:
        try:
            await assets.replace_bytes(db, asset, data)
        except blob.BlobError as e:
            log.error("replacing stored asset %s failed: %s", asset.name, e)
            raise APIError(503, "storage_unavailable", "The image could not be stored. Try again.")
    await sandbox.write_bytes(path, data)


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(visual.MAX_IMAGE_BYTES + 1)
    if not data:
        raise APIError(400, "bad_image", "The file is empty.")
    return data


@router.put("/projects/{project_id}/files/{path:path}", response_model=ImageReplaceOut)
async def replace_file(project_id: str, path: str, request: Request,
                       file: UploadFile = File(...),
                       user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Swap the picture at `path` for another, generated pictures and uploads
    included. It keeps its path, re-encoded into the file's own format when
    the upload is a different one, so every use of it keeps working."""
    project = await _hand_edit_target(project_id, user, db)
    try:
        clean = safe_path(path)
    except PathError as e:
        raise APIError(400, "bad_path", str(e))
    if not visual.is_image_path(clean):
        raise APIError(400, "not_an_image", "Only images can be replaced here. Ask Vivid to change other files.")
    data = await _read_upload(file)
    async with _editing.setdefault(project_id, asyncio.Lock()):
        sandbox = await _sandbox(project_id, request)
        if clean not in await sandbox.list_files():
            raise APIError(404, "not_found", "File not found")
        try:
            fitted = visual.fit_to(data, clean)
        except visual.VisualError as e:
            raise APIError(400, "bad_image", str(e))
        if fitted is None:
            ext = pathlib.PurePosixPath(clean).suffix
            raise APIError(400, "bad_image", f"Upload a {ext} image to replace this file.")
        await _write_image(db, project_id, sandbox, clean, fitted)
        row = await _save_hand_edit(db, sandbox, project, f"Replaced {clean}")
    return ImageReplaceOut(path=clean, snapshot=row)


@router.post("/projects/{project_id}/images/replace", response_model=ImageReplaceOut)
async def replace_image(project_id: str, request: Request,
                        src: str = Form(..., max_length=4096),
                        file: UploadFile = File(...),
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Swap a picture picked in the preview, named by the URL the page loaded
    it from. One of the app's files (generated pictures and uploads
    included) is replaced in place; a picture that is not (a stock photo
    URL) gets a new file under public/images and the source is repointed."""
    project = await _hand_edit_target(project_id, user, db)
    data = await _read_upload(file)
    async with _editing.setdefault(project_id, asyncio.Lock()):
        sandbox = await _sandbox(project_id, request)
        files = await sandbox.list_files()
        mobile = sandbox.target.is_mobile
        try:
            target = visual.resolve_src(src, sandbox.preview_url(), files, mobile=mobile)
            fitted = visual.fit_to(data, target.path) if target.path else None
        except visual.VisualError as e:
            raise APIError(400, "bad_image", str(e))
        if fitted is not None:
            await _write_image(db, project_id, sandbox, target.path, fitted)
            row = await _save_hand_edit(db, sandbox, project, f"Replaced {target.path}")
            return ImageReplaceOut(path=target.path, snapshot=row)

        # A new file, and every reference moved to it.
        refs = target.refs
        if target.path and not refs:
            # An import (./assets/logo.svg) cannot be repointed by URL.
            ext = pathlib.PurePosixPath(target.path).suffix
            raise APIError(400, "bad_image", f"Upload a {ext} image to replace this picture.")
        sources = await visual.read_sources(sandbox, files)
        if not any(ref in content for ref in refs for content in sources.values()):
            raise APIError(404, "not_found",
                           "Could not find where the app uses that picture. Ask Vivid to change it.")
        new_path = visual.new_image_path(file.filename or "image", visual.upload_ext(data),
                                         mobile=mobile)
        if mobile:
            # A remote picture becomes a required file; only `{ uri }` uses move.
            changed = visual.relink_uri(sources, src, new_path)
            if not changed:
                raise APIError(404, "not_found",
                               "Could not find where the app uses that picture. Ask Vivid to change it.")
            await sandbox.write_bytes(new_path, data)
        else:
            await sandbox.write_bytes(new_path, data)
            changed = visual.relink(sources, refs, "/" + new_path.removeprefix("public/"))
        for path in changed:
            await sandbox.write_file(path, sources[path])
        row = await _save_hand_edit(db, sandbox, project, f"Replaced an image with {new_path}")
    return ImageReplaceOut(path=new_path, relinked=changed, snapshot=row)


@router.post("/projects/{project_id}/edits", response_model=EditsOut)
async def edit_text(project_id: str, body: EditsIn, request: Request,
                    user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    """Change copy the way the page shows it: each edit names the text as
    seen and what it should say. It is found in the source however the
    source spells it; one match is changed, several need `all`, none (text
    the page builds from data) is reported, never guessed at. The edits that
    applied are saved as one version."""
    project = await _hand_edit_target(project_id, user, db)
    async with _editing.setdefault(project_id, asyncio.Lock()):
        sandbox = await _sandbox(project_id, request)
        sources = await visual.read_sources(sandbox, await sandbox.list_files())
        before = dict(sources)
        results = []
        for edit in body.edits:
            try:
                r = visual.apply_text_edit(sources, edit.old, edit.new, edit.all)
            except visual.VisualError as e:
                raise APIError(400, "bad_edit", str(e))
            results.append(TextEditOut(old=edit.old, new=edit.new, status=r.status,
                                       files=r.files, count=r.count))
        changed = [p for p in sources if sources[p] != before[p]]
        for path in changed:
            await sandbox.write_file(path, sources[path])
        row = None
        if changed:
            first = next(r for r in results if r.status == "applied")
            label = " ".join(first.new.split())
            label = label if len(label) <= 60 else label[:57] + "..."
            row = await _save_hand_edit(db, sandbox, project, f"Edited text: {label}")
    return EditsOut(results=results, snapshot=row)


_BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2",
               ".ttf", ".otf", ".mp4", ".mp3", ".zip", ".gz", ".tgz"}


def _is_binary(path: str, data: bytes) -> bool:
    if pathlib.Path(path).suffix.lower() in _BINARY_EXT:
        return True
    return b"\x00" in data[:8000]


async def _target_of(project_id: str) -> targets.Target:
    async with async_session() as db:
        value = (await db.execute(select(BuilderProject.target)
                                  .where(BuilderProject.id == project_id))).scalar_one_or_none()
    return targets.get(value)


async def _start_sandbox(project_id: str, redis, target: targets.Target | None = None):
    """The project's sandbox. A fresh one is restored from the current
    snapshot and then given everything that lives outside git or may have
    changed since: spec.md, the backend .env, the uploaded files. Own
    session: the manager may call this long after the request's session
    was used, and from any route. `target` saves the lookup when the caller
    has the row."""
    if target is None:
        target = await _target_of(project_id)
    async def restore(sandbox):
        async with async_session() as db:
            project = await db.get(BuilderProject, project_id)
            if project is None:
                return
            row = await snapshots.current(db, project)
            spec_md = project.spec_md
            env_vars = await _env_for(project, db)
            uploaded = await assets.list_for(db, project_id)
        if row is not None:
            await snapshots.restore(sandbox, row)
        await _sync_spec(sandbox, spec_md)
        await _sync_env(sandbox, env_vars)
        await assets.sync(sandbox, uploaded)
    sandbox = await manager.get_or_create(project_id, redis, restore=restore, target=target)
    await manager.touch(project_id)
    await _sync_auth_for_sandbox(project_id, sandbox)
    return sandbox


def _device_url(sandbox) -> str | None:
    """What Expo Go opens on the user's phone (shown as a QR code): the same
    Metro server as the web preview. Through the http relay when one is
    configured (React Native's dev tooling needs plain http), else exps://
    straight to E2B. Local sandboxes are on this host only, so a phone cannot
    reach them."""
    if not sandbox.target.is_mobile:
        return None
    relay = settings.EXPO_DEVICE_RELAY_DOMAIN
    if relay and sandbox.driver == "e2b":
        return f"exp://{sandbox.id}.{relay}"
    url = sandbox.preview_url()
    if url.startswith("https://"):
        return "exps://" + url.removeprefix("https://")
    return None


async def _sandbox(project_id: str, request: Request):
    try:
        return await _start_sandbox(project_id, request.app.state.redis)
    except (SandboxError, snapshots.SnapshotError) as e:
        log.error("sandbox for project %s failed: %s", project_id, e)
        raise APIError(503, "sandbox_unavailable",
                       "The workspace could not be started. Please try again.")


# ------------------------------------------------------------ snapshots
@router.get("/projects/{project_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(project_id: str, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    rows = await db.execute(select(BuilderSnapshot)
                            .where(BuilderSnapshot.project_id == project_id)
                            .order_by(BuilderSnapshot.seq))
    return list(rows.scalars())


@router.post("/projects/{project_id}/snapshots", response_model=SnapshotOut)
async def take_snapshot(project_id: str, request: Request,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Store the sandbox's files now. Normally every changing turn does
    this; this is for when that failed (a timed-out read) and the work
    exists only in the sandbox. 204 would hide the answer, so an unchanged
    tree returns the latest snapshot instead."""
    project = await _owned(project_id, user, db)
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    sandbox = await _sandbox(project_id, request)
    try:
        row = await snapshots.take(db, sandbox, project, "manual snapshot")
    except (snapshots.SnapshotError, SandboxError) as e:
        log.error("manual snapshot for %s failed: %s", project_id, e)
        raise APIError(503, "snapshot_failed", "The files could not be stored. Try again.")
    await db.commit()
    if row is None:
        row = await snapshots.latest(db, project_id)
        if row is None:
            raise APIError(409, "nothing_to_snapshot", "Nothing has changed since the template.")
    return row


@router.post("/projects/{project_id}/undo", response_model=SnapshotOut)
async def undo_last_turn(project_id: str, request: Request,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """One click back: restore the version before the current one. Nothing
    is deleted; the next turn's version continues the sequence, and
    `restore` can go forward again."""
    project = await _owned(project_id, user, db)
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    current = await snapshots.current(db, project)
    if current is None or current.seq <= 1:
        raise APIError(409, "nothing_to_undo", "There is no earlier version to go back to.")
    row = (await db.execute(select(BuilderSnapshot)
                            .where(BuilderSnapshot.project_id == project_id,
                                   BuilderSnapshot.seq == current.seq - 1))).scalar_one_or_none()
    if row is None:
        raise APIError(409, "nothing_to_undo", "There is no earlier version to go back to.")
    project.current_snapshot_id = row.id
    await db.commit()
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        try:
            await snapshots.restore(sandbox, row)
        except (snapshots.SnapshotError, SandboxError) as e:
            log.error("undo into live sandbox for %s failed: %s", project_id, e)
            await manager.kill(project_id, request.app.state.redis)
    await manager.touch(project_id)
    return row


@router.get("/projects/{project_id}/logs")
async def dev_server_logs(project_id: str, request: Request, lines: int = 100,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """The dev server's recent output: what a client shows when the preview
    is blank or an error overlay is up, next to a "Fix this" button that
    sends the text as a chat turn."""
    await _owned(project_id, user, db)
    sandbox = await _sandbox(project_id, request)
    return {"lines": (await sandbox.dev_server_logs(max(1, min(lines, 500)))).splitlines()}


@router.post("/projects/{project_id}/snapshots/{seq}/restore", response_model=SnapshotOut)
async def restore_snapshot(project_id: str, seq: int, request: Request,
                           user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """Make an older version current. A live sandbox gets the files now;
    otherwise the next sandbox starts from it. The next turn's snapshot
    continues the sequence, so nothing is lost by going back."""
    project = await _owned(project_id, user, db)
    if turns.running(project_id):
        raise APIError(409, "busy", "Wait for the running turn to finish first.")
    row = (await db.execute(select(BuilderSnapshot)
                            .where(BuilderSnapshot.project_id == project_id,
                                   BuilderSnapshot.seq == seq))).scalar_one_or_none()
    if row is None:
        raise APIError(404, "not_found", "No such version")
    project.current_snapshot_id = row.id
    await db.commit()
    sandbox = manager.peek(project_id)
    if sandbox is not None:
        try:
            await snapshots.restore(sandbox, row)
        except (snapshots.SnapshotError, SandboxError) as e:
            log.error("restore of %s seq %d into live sandbox failed: %s", project_id, seq, e)
            # Replace the sandbox rather than leave it half-restored.
            await manager.kill(project_id, request.app.state.redis)
    await manager.touch(project_id)
    return row


@router.get("/projects/{project_id}/analytics", response_model=AnalyticsOut)
async def project_analytics(project_id: str, days: int = 30,
                            user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Visits to the published app: totals, per day, top pages, referrers,
    devices and countries, for the last `days` (1 to 365)."""
    await _owned(project_id, user, db)
    return AnalyticsOut(**await analytics.rollup(db, project_id, days))


@router.get("/projects/{project_id}/usage", response_model=UsageOut)
async def project_usage(project_id: str, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _owned(project_id, user, db)
    return UsageOut(**await usage.rollup(db, project_id=project_id))
