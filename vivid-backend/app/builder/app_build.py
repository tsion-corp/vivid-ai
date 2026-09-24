"""Installable builds of mobile projects on EAS (Expo's cloud).

Starting a build means uploading the project with eas-cli, which needs an
Expo token. The token never enters the project's own sandbox, where the
model runs commands and the app's packages run install scripts: each build
gets a throwaway sandbox from the mobile template, the snapshot is restored
into it, dynamic config files (app.config.*, code that eas-cli would run with
the token in its environment) are removed, app.json gets the store ids, and
only then do `eas init` and `eas build --no-wait` run with the token in their
own environment. The sandbox is killed as soon as the build is queued.

From then on the build is followed from here through Expo's API (expo.py):
`poll_once` runs on a timer, so a restart loses nothing, updates statuses and
artifacts, and refunds builds that fail or are cancelled.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import billing, expo, snapshots, targets
from app.builder.sandbox.base import Sandbox, SandboxError
from app.builder.sandbox.manager import manager
from app.core.config import settings
from app.db.models import BuilderAppBuild, BuilderProject, BuilderSnapshot, Connector
from app.db.session import async_session
from app.services.connectors import tokens as connector_tokens

log = logging.getLogger("vivid.builder.app_build")

PLATFORMS = ("android", "ios")
PROFILES = ("preview", "production")
STARTING, QUEUED, BUILDING, CANCELING = "starting", "queued", "building", "canceling"
FINISHED, FAILED, CANCELED = "finished", "failed", "canceled"
ACTIVE = (STARTING, QUEUED, BUILDING, CANCELING)
DONE = (FINISHED, FAILED, CANCELED)

#: EAS statuses as ours.
_STATUS = {expo.NEW: QUEUED, expo.IN_QUEUE: QUEUED, expo.IN_PROGRESS: BUILDING,
           expo.PENDING_CANCEL: CANCELING, expo.FINISHED: FINISHED,
           expo.ERRORED: FAILED, expo.CANCELED: CANCELED}

#: Config files eas-cli would execute with the token in its environment.
_DYNAMIC_CONFIG = "rm -f app.config.js app.config.ts app.config.mjs app.config.cjs"


class BuildError(Exception):
    """A build could not start; `str()` is safe to show the user."""


# ------------------------------------------------------------ accounts
async def user_connector(db: AsyncSession, user_id: str) -> Connector | None:
    return (await db.execute(select(Connector).where(
        Connector.user_id == user_id, Connector.provider == "expo"))).scalar_one_or_none()


async def credentials(db: AsyncSession, build: BuilderAppBuild,
                      owner_id: str) -> tuple[str, str]:
    """(token, Expo account) the build runs on."""
    if build.account == billing.VIVID:
        return settings.EXPO_TOKEN, settings.EXPO_OWNER
    connector = await user_connector(db, owner_id)
    if connector is None:
        raise BuildError("Connect your Expo account first, or build on Vivid's.")
    config = connector.config_json or {}
    owner = config.get("owner") or config.get("username") or ""
    return connector_tokens.read(connector.token), owner


# ------------------------------------------------------------- app ids
def _slug_part(name: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", (name or "").lower())[:20] or "app"
    return base if base[0].isalpha() else "a" + base


def app_id_for(project: BuilderProject) -> str:
    """app.vivid.<name><6 hex>: a valid iOS bundle identifier and Android
    package (segments start with a letter), unique per project."""
    return f"app.vivid.{_slug_part(project.name)}{project.id.replace('-', '')[:6]}"


def slug_for(project: BuilderProject) -> str:
    """The EAS project slug: unique, so linking never lands on another app."""
    return f"{_slug_part(project.name)}-{project.id.replace('-', '')[:6]}"


def with_store_ids(app_json: str, project: BuilderProject, owner: str,
                   eas_project_id: str | None) -> str:
    """app.json with the name, ids and owner the build needs."""
    data = json.loads(app_json or "{}")
    exp = data.setdefault("expo", {})
    exp["name"] = (project.name or exp.get("name") or "App")[:30]
    exp["slug"] = slug_for(project)
    exp["owner"] = owner
    exp.setdefault("ios", {})["bundleIdentifier"] = project.app_id
    exp.setdefault("android", {})["package"] = project.app_id.replace("-", "_")
    extra = exp.setdefault("extra", {})
    if eas_project_id:
        extra.setdefault("eas", {})["projectId"] = eas_project_id
    else:
        extra.get("eas", {}).pop("projectId", None)
    return json.dumps(data, indent=2) + "\n"


def with_build_env(eas_json: str, profile: str, env: dict[str, str]) -> str:
    """eas.json with the app's public env on the build profile."""
    data = json.loads(eas_json or "{}")
    prof = data.setdefault("build", {}).setdefault(profile, {})
    prof["env"] = {**(prof.get("env") or {}),
                   **{k: v for k, v in env.items() if k.startswith("EXPO_PUBLIC_")}}
    return json.dumps(data, indent=2) + "\n"


def _json_out(stdout: str):
    """The JSON eas-cli prints with --json (other output goes to stderr, but
    a stray line before it is skipped)."""
    text = stdout.strip()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                return json.loads(text[i:])
            except ValueError:
                continue
    raise BuildError("Expo's build tool gave no result. Try again.")


# ---------------------------------------------------------------- start
async def start(build_id: str) -> None:
    """Upload the build to EAS. A background task; the row says how it went."""
    sandbox: Sandbox | None = None
    try:
        async with async_session() as db:
            build = await db.get(BuilderAppBuild, build_id)
            project = await db.get(BuilderProject, build.project_id)
            snapshot = await db.get(BuilderSnapshot, build.snapshot_id)
            token, owner = await credentials(db, build, project.owner_id)
            if not project.app_id:
                project.app_id = app_id_for(project)
            build.eas_owner = owner
            await db.commit()
            eas_project_id = (project.eas_projects or {}).get(owner)
            # The app's public env, as the installed app needs it (Vivid Pay's
            # live key, not the sandbox's test key). Local import: the routes
            # module imports this one.
            from app.api.routes.builder import _env_for
            build_env = await _env_for(project, db, for_build=True) or {}

        sandbox = await manager.create_fresh(f"build-{build_id}",
                                             targets.get(targets.MOBILE), wait=False)
        await snapshots.restore(sandbox, snapshot)
        await _run(sandbox, _DYNAMIC_CONFIG, "prepare the project")
        app_json = await sandbox.read_file("app.json")
        await sandbox.write_file("app.json", with_store_ids(app_json, project, owner,
                                                            eas_project_id))
        if build_env:
            # .env is not in the snapshot or the upload; EXPO_PUBLIC_* values
            # are inlined at bundle time from the build profile's env.
            eas_json = await sandbox.read_file("eas.json")
            await sandbox.write_file("eas.json", with_build_env(eas_json, build.profile, build_env))
        env = {"EXPO_TOKEN": token, "EAS_NO_VCS": "1", "EAS_BUILD_NO_EXPO_GO_WARNING": "true"}
        if not eas_project_id:
            out = await _run(sandbox, f"eas init --non-interactive --force --json --account {owner}",
                             "create the app on Expo", env)
            eas_project_id = str(_json_out(out).get("projectId") or "")
            if not eas_project_id:
                raise BuildError("Expo did not create the app. Try again.")
            async with async_session() as db:
                row = await db.get(BuilderProject, project.id)
                row.eas_projects = {**(row.eas_projects or {}), owner: eas_project_id}
                await db.commit()
        out = await _run(sandbox,
                         f"eas build --platform {build.platform} --profile {build.profile} "
                         "--non-interactive --no-wait --json",
                         "start the build", env, timeout=settings.EAS_START_TIMEOUT)
        started = _json_out(out)
        started = started[0] if isinstance(started, list) and started else started
        eas_id = (started or {}).get("id") if isinstance(started, dict) else None
        if not eas_id:
            raise BuildError("Expo did not start the build. Try again.")
        async with async_session() as db:
            row = await db.get(BuilderAppBuild, build_id)
            row.eas_build_id = eas_id
            if row.status == CANCELED:
                # Cancelled while uploading: stop it on Expo too.
                await expo.cancel(token, eas_id)
            else:
                row.status = _STATUS.get((started or {}).get("status"), QUEUED)
            await db.commit()
        log.info("app build %s started on EAS as %s (%s)", build_id, eas_id, owner)
    except (BuildError, expo.ExpoError) as e:
        await _fail(build_id, str(e))
    except (SandboxError, snapshots.SnapshotError) as e:
        log.error("app build %s could not start: %s", build_id, e)
        await _fail(build_id, "The build could not be prepared. Try again.")
    except Exception:
        log.exception("app build %s failed to start", build_id)
        await _fail(build_id, "The build could not be started. Try again.")
    finally:
        if sandbox is not None:
            await sandbox.kill()


async def _run(sandbox: Sandbox, cmd: str, what: str, env: dict | None = None,
               timeout: float = 300) -> str:
    result = await sandbox.run(cmd, timeout=timeout, env=env)
    if not result.ok:
        tail = _scrub(result.output)[-400:].strip()
        log.warning("app build could not %s: %s", what, tail)
        raise BuildError(f"Could not {what}: {tail.splitlines()[-1] if tail else 'no output'}")
    return result.stdout


def _scrub(text: str) -> str:
    """eas-cli never prints the token, but a log line is no place to find out."""
    for secret in (settings.EXPO_TOKEN,):
        if secret:
            text = text.replace(secret, "***")
    return text


async def _fail(build_id: str, message: str) -> None:
    async with async_session() as db:
        row = await db.get(BuilderAppBuild, build_id)
        if row is None:
            return
        row.status, row.error = FAILED, message[:1000]
        row.finished_at = datetime.now(timezone.utc)
        await billing.refund(db, row)
        await db.commit()


# ------------------------------------------------------------ following
async def refresh(db: AsyncSession, build: BuilderAppBuild, owner_id: str) -> None:
    """Bring one row up to date from Expo; the caller commits."""
    if build.eas_build_id is None or build.status in DONE:
        return
    token, _ = await credentials(db, build, owner_id)
    info = await expo.build(token, build.eas_build_id)
    status = _STATUS.get(info.status, build.status)
    build.logs_url = info.logs_url or build.logs_url
    build.artifact_url = info.artifact_url or build.artifact_url
    if status != build.status:
        log.info("app build %s: %s -> %s", build.id, build.status, status)
        build.status = status
    if status in DONE:
        build.finished_at = datetime.now(timezone.utc)
        if status == FAILED:
            build.error = info.error or "The build failed on Expo. Open the logs for details."
        if status in (FAILED, CANCELED):
            await billing.refund(db, build)


async def poll_once() -> int:
    """Every build still in flight, refreshed. Returns how many were looked at."""
    stale = datetime.now(timezone.utc) - timedelta(seconds=settings.EAS_START_TIMEOUT * 2)
    async with async_session() as db:
        rows = (await db.execute(
            select(BuilderAppBuild, BuilderProject.owner_id)
            .join(BuilderProject, BuilderProject.id == BuilderAppBuild.project_id)
            .where(BuilderAppBuild.status.in_(ACTIVE)))).all()
        for build, owner_id in rows:
            if build.eas_build_id is None:
                # Still uploading, or the process that was uploading died.
                created = build.created_at if build.created_at.tzinfo else \
                    build.created_at.replace(tzinfo=timezone.utc)
                if build.status == STARTING and created < stale:
                    build.status, build.error = FAILED, "The build never started. Try again."
                    build.finished_at = datetime.now(timezone.utc)
                    await billing.refund(db, build)
                continue
            try:
                await refresh(db, build, owner_id)
            except (expo.ExpoError, BuildError) as e:
                log.warning("could not refresh app build %s: %s", build.id, e)
        await db.commit()
    return len(rows)


_POLL_LOCK = "builder:app-builds:poll"


async def poller(redis, interval: float | None = None) -> None:
    """Run forever; the app's lifespan owns the task. With several API
    processes one polls per interval (a Redis lock), so a refund is never
    written twice."""
    interval = interval or settings.EAS_POLL_SECONDS
    while True:
        await asyncio.sleep(interval)
        try:
            if not await redis.set(_POLL_LOCK, "1", nx=True, ex=max(int(interval) - 1, 1)):
                continue
        except Exception:
            pass                        # no redis: this process polls alone
        try:
            await poll_once()
        except Exception as e:                           # keep polling
            log.warning("app build poll failed: %s", e)


async def cancel(db: AsyncSession, build: BuilderAppBuild, owner_id: str) -> None:
    """Ask Expo to stop it; the poller sees it end and refunds it."""
    if build.status in DONE:
        return
    if build.eas_build_id is None:
        build.status, build.finished_at = CANCELED, datetime.now(timezone.utc)
        await billing.refund(db, build)
        return
    token, _ = await credentials(db, build, owner_id)
    status = await expo.cancel(token, build.eas_build_id)
    build.status = _STATUS.get(status, CANCELING)
    if build.status in DONE:
        build.finished_at = datetime.now(timezone.utc)
        await billing.refund(db, build)
