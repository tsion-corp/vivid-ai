"""A new project from any version of another: the files, the plan and the
uploads, and none of the services it was connected to.

The copy starts at version 1 with the source version's files (its .env left
out: those values belong to the source's database, payments and sign-in),
and its own copies of the uploads. Connections are the source's accounts, so
they are not carried over; `reset` names them for the person to reconnect.
"""
import io
import tarfile

from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import blob, usage
from app.db.models import BuilderAsset, BuilderProject, BuilderSnapshot

#: Plan and build fields a copy keeps.
COPIED = ("target", "brief_md", "spec_md", "recipe", "fullstack", "maps_provider")

#: Files a copy never carries: the source's connection values.
DROPPED_FILES = {".env", ".env.local"}


def without_env(data: bytes) -> bytes:
    """A snapshot tarball with the .env files taken out (as it is, when it
    is not a tarball at all: nothing could restore it either)."""
    try:
        src = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError:
        return data
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as dst:
        for member in src.getmembers():
            if member.name.removeprefix("./") in DROPPED_FILES:
                continue
            dst.addfile(member, src.extractfile(member) if member.isfile() else None)
    return out.getvalue()


def reset_of(source: BuilderProject) -> list[str]:
    """What the source was connected to that the copy is not."""
    reset = []
    if source.backend_mode != "none" or source.supabase_project_ref:
        reset.append("database")
    if source.payments_provider != "none":
        reset.append("payments")
    if source.auth_provider != "none":
        reset.append("sign-in")
    if source.chain != "none":
        reset.append("blockchain")
    if source.maps_provider != "none":
        reset.append("maps key")
    if source.published_url:
        reset.append("published site")
    return reset


async def copy(db: AsyncSession, source: BuilderProject, snapshot: BuilderSnapshot,
               owner_id: str, name: str | None = None) -> BuilderProject:
    """The new project, committed by the caller."""
    project = BuilderProject(owner_id=owner_id, mode="build",
                             name=(name or f"{source.name} (copy)")[:120])
    for field in COPIED:
        setattr(project, field, getattr(source, field))
    # A maps key is the source's secret: the copy asks for its own.
    project.maps_provider = "none"
    db.add(project)
    await db.flush()

    data = without_env(await blob.get(snapshot.r2_key))
    key = blob.snapshot_key(project.id, 1)
    await blob.put(key, data)
    row = BuilderSnapshot(project_id=project.id, seq=1, r2_key=key, commit_sha=None,
                          summary=f"Copied from {source.name} (version {snapshot.seq})"[:500],
                          size_bytes=len(data))
    db.add(row)
    await db.flush()
    project.current_snapshot_id = row.id
    await usage.record_storage(db, project.id, len(data), 1)

    for asset in (await db.execute(
            BuilderAsset.__table__.select().where(BuilderAsset.project_id == source.id))).all():
        new = BuilderAsset(project_id=project.id, name=asset.name, mime=asset.mime,
                           size_bytes=asset.size_bytes, meta=asset.meta, r2_key="")
        db.add(new)
        await db.flush()
        new.r2_key = blob.asset_key(project.id, new.id, asset.name)
        await blob.put(new.r2_key, await blob.get(asset.r2_key), content_type=asset.mime)
    return project
