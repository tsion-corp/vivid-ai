"""Files the user gives the builder: a logo, product photos, a font.

Stored in the blob store and copied into the app at public/uploads/<name>,
which Vite serves as /uploads/<name> in the preview and in the published
site. The copy is committed with everything else, so snapshots carry it; a
sandbox that lacks one (restored from an older snapshot, or fresh before
the first snapshot) gets it back from the store on the next start.

The model is told what was uploaded, by path, in every turn. Plan mode also
sees the images themselves.
"""
import logging
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import blob
from app.builder.sandbox.base import Sandbox, SandboxError
from app.core.config import settings
from app.db.models import BuilderAsset

log = logging.getLogger("vivid.builder.assets")

UPLOAD_DIR = "public/uploads"
PUBLIC_PREFIX = "/uploads"

ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml", "image/avif",
    "font/woff", "font/woff2", "font/ttf", "font/otf", "application/font-woff",
    "application/pdf", "video/mp4", "audio/mpeg",
}
IMAGE_MIME = {m for m in ALLOWED_MIME if m.startswith("image/")}

_EXT_FOR = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
            "image/svg+xml": "svg", "image/avif": "avif", "font/woff": "woff",
            "font/woff2": "woff2", "font/ttf": "ttf", "font/otf": "otf",
            "application/pdf": "pdf", "video/mp4": "mp4", "audio/mpeg": "mp3"}


class AssetError(Exception):
    """Refused: type, size or count. The message is for the user."""


def safe_name(filename: str, mime: str) -> str:
    """A URL-safe file name with the right extension: 'Air Max 90.PNG' ->
    'air-max-90.png'."""
    base = (filename or "file").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem, _, ext = base.rpartition(".")
    if not stem:
        stem, ext = ext, ""
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:60] or "file"
    ext = (ext or "").lower()
    wanted = _EXT_FOR.get(mime)
    if wanted and ext not in (wanted, "jpeg" if wanted == "jpg" else wanted):
        ext = wanted
    return f"{stem}.{ext}" if ext else stem


async def add(db: AsyncSession, project_id: str, filename: str, mime: str,
              data: bytes) -> BuilderAsset:
    mime = (mime or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise AssetError("That file type is not supported. Upload images, fonts, a PDF, "
                         "an MP4 or an MP3.")
    if len(data) > settings.BUILDER_ASSET_MAX_BYTES:
        raise AssetError(f"That file is over {settings.BUILDER_ASSET_MAX_BYTES // 1_000_000} MB.")
    count, total = (await db.execute(
        select(func.count(), func.coalesce(func.sum(BuilderAsset.size_bytes), 0))
        .where(BuilderAsset.project_id == project_id))).one()
    if count >= settings.BUILDER_ASSETS_PER_PROJECT:
        raise AssetError("This project has as many files as it can hold.")
    if total + len(data) > settings.BUILDER_ASSETS_MAX_TOTAL_BYTES:
        raise AssetError("This project's uploads are over the size limit.")

    name = safe_name(filename, mime)
    existing = (await db.execute(select(BuilderAsset).where(
        BuilderAsset.project_id == project_id, BuilderAsset.name == name))).scalar_one_or_none()
    if existing is not None:
        # Same name again replaces the file, which is what a re-upload means.
        await blob.put(existing.r2_key, data, mime)
        existing.mime, existing.size_bytes = mime, len(data)
        existing.meta = _meta(data, mime)
        await db.flush()
        return existing
    asset = BuilderAsset(project_id=project_id, name=name, mime=mime, size_bytes=len(data),
                         r2_key="", meta=_meta(data, mime))
    db.add(asset)
    await db.flush()
    asset.r2_key = blob.asset_key(project_id, asset.id, name)
    await blob.put(asset.r2_key, data, mime)
    await db.flush()
    return asset


async def by_sandbox_path(db: AsyncSession, project_id: str, path: str) -> BuilderAsset | None:
    """The asset stored at public/uploads/<name>, if that is one."""
    if not path.startswith(UPLOAD_DIR + "/"):
        return None
    return (await db.execute(select(BuilderAsset).where(
        BuilderAsset.project_id == project_id,
        BuilderAsset.name == path[len(UPLOAD_DIR) + 1:]))).scalar_one_or_none()


async def replace_bytes(db: AsyncSession, asset: BuilderAsset, data: bytes) -> None:
    """New contents under the same name, in the store too: a sandbox that
    starts later copies uploads back from there, and must get these."""
    await blob.put(asset.r2_key, data, asset.mime)
    asset.size_bytes = len(data)
    asset.meta = _meta(data, asset.mime)
    await db.flush()


async def list_for(db: AsyncSession, project_id: str) -> list[BuilderAsset]:
    rows = await db.execute(select(BuilderAsset).where(BuilderAsset.project_id == project_id)
                            .order_by(BuilderAsset.created_at))
    return list(rows.scalars())


def public_path(asset: BuilderAsset) -> str:
    return f"{PUBLIC_PREFIX}/{asset.name}"


def sandbox_path(asset: BuilderAsset) -> str:
    return f"{UPLOAD_DIR}/{asset.name}"


async def write_into(sandbox: Sandbox, asset: BuilderAsset, data: bytes) -> None:
    await sandbox.write_bytes(sandbox_path(asset), data)


async def sync(sandbox: Sandbox, rows: list[BuilderAsset]) -> int:
    """Put every asset the sandbox lacks back from the store. Returns how
    many were written."""
    if not rows:
        return 0
    try:
        present = set(await sandbox.list_files())
    except SandboxError as e:
        log.warning("could not list files to sync assets: %s", e)
        return 0
    written = 0
    for asset in rows:
        if sandbox_path(asset) in present:
            continue
        try:
            await write_into(sandbox, asset, await blob.get(asset.r2_key))
            written += 1
        except (blob.BlobError, SandboxError) as e:
            log.warning("could not sync asset %s: %s", asset.name, e)
    return written


def describe(rows: list[BuilderAsset]) -> str:
    """The list the model sees, in both plan and build mode."""
    if not rows:
        return ""
    lines = ["## Files the user uploaded",
             "Use them by their public path; they are already in public/uploads.",
             "Do not recreate or replace them."]
    for a in rows:
        size = f"{a.size_bytes // 1024} KB" if a.size_bytes >= 1024 else f"{a.size_bytes} B"
        dims = ""
        if a.meta and a.meta.get("width"):
            dims = f", {a.meta['width']}x{a.meta['height']}"
        lines.append(f"- {public_path(a)} ({a.mime}, {size}{dims})")
    return "\n".join(lines)


def image_urls(rows: list[BuilderAsset], limit: int = 4) -> list[str]:
    """Presigned URLs of the newest image assets, for the plan model."""
    images = [a for a in rows if a.mime in IMAGE_MIME and a.mime != "image/svg+xml"]
    return [blob.presigned_url(a.r2_key) for a in images[-limit:]]


def _meta(data: bytes, mime: str) -> dict | None:
    """Width and height for PNG and JPEG without an imaging library."""
    try:
        if mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return {"width": w, "height": h}
        if mime == "image/jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    return None
                marker = data[i + 1]
                seg = int.from_bytes(data[i + 2:i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return {"width": w, "height": h}
                i += 2 + seg
    except Exception:
        return None
    return None
