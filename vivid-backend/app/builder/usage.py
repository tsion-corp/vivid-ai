"""The usage ledger: one row per model call, sandbox session and stored
snapshot, priced where the price is known. Billing is built on these rows
later; the rollups here are what a usage page or a plan check reads.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import pricing
from app.builder.loop import ModelCall
from app.db.models import BuilderProject, BuilderUsageEvent
from app.db.session import async_session

log = logging.getLogger("vivid.builder.usage")

MODEL, SANDBOX, STORAGE, SUPABASE = "model", "sandbox", "storage", "supabase"


async def record_model(db: AsyncSession, project_id: str, calls: list[ModelCall]) -> None:
    for call in calls:
        usage = call.usage or {}
        tokens = int(usage.get("total_tokens") or
                     (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
        db.add(BuilderUsageEvent(
            project_id=project_id, kind=MODEL, quantity=tokens, unit="tokens",
            cost_usd=await pricing.cost_of(call.model, usage), model=call.model,
            meta={"stage": call.stage,
                  "prompt_tokens": usage.get("prompt_tokens"),
                  "completion_tokens": usage.get("completion_tokens"),
                  "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens")}))


async def record_storage(db: AsyncSession, project_id: str, nbytes: int, seq: int) -> None:
    db.add(BuilderUsageEvent(project_id=project_id, kind=STORAGE, quantity=nbytes,
                             unit="bytes", meta={"seq": seq}))


async def record_sandbox(project_id: str, sandbox_id: str, seconds: float) -> None:
    """Called by the manager when a sandbox dies; its own session because
    the manager has no request. Best effort."""
    try:
        async with async_session() as db:
            project = await db.get(BuilderProject, project_id)
            if project is None:
                return                           # the project was deleted
            from app.builder import targets
            target = targets.of(project)
            db.add(BuilderUsageEvent(project_id=project_id, kind=SANDBOX,
                                     quantity=round(seconds, 1), unit="seconds",
                                     cost_usd=round(seconds * target.sandbox_cost_per_second(), 8),
                                     meta={"sandbox_id": sandbox_id, "target": target.name}))
            await db.commit()
    except Exception as e:
        log.warning("could not record sandbox usage for %s: %s", project_id, e)


async def rollup(db: AsyncSession, project_id: str | None = None,
                 user_id: str | None = None, since: datetime | None = None) -> dict:
    """Totals by kind. Either one project, or every project a user owns."""
    q = select(BuilderUsageEvent.kind,
               func.count(), func.coalesce(func.sum(BuilderUsageEvent.quantity), 0),
               func.coalesce(func.sum(BuilderUsageEvent.cost_usd), 0))
    if project_id:
        q = q.where(BuilderUsageEvent.project_id == project_id)
    if user_id:
        q = q.join(BuilderProject, BuilderProject.id == BuilderUsageEvent.project_id)
        q = q.where(BuilderProject.owner_id == user_id)
    if since:
        q = q.where(BuilderUsageEvent.created_at >= since)
    rows = (await db.execute(q.group_by(BuilderUsageEvent.kind))).all()
    by_kind = {kind: {"events": n, "quantity": float(qty), "cost_usd": float(cost)}
               for kind, n, qty, cost in rows}
    model = by_kind.get(MODEL, {})
    return {
        "since": since.isoformat() if since else None,
        "model_calls": model.get("events", 0),
        "tokens": int(model.get("quantity", 0)),
        "sandbox_seconds": by_kind.get(SANDBOX, {}).get("quantity", 0.0),
        "storage_bytes": int(by_kind.get(STORAGE, {}).get("quantity", 0)),
        "cost_usd": round(sum(v["cost_usd"] for v in by_kind.values()), 6),
        "by_kind": by_kind,
    }


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)
