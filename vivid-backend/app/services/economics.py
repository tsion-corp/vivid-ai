"""What the builder costs us, measured from the usage ledger, and what each
plan earns at that cost.

Reads builder_usage_events: model rows (tokens, cached tokens, cost from
OpenRouter's price list, stage), image rows and sandbox rows (seconds,
priced by template size), plus app builds. Answers "what is a million
tokens worth to us" with real traffic instead of list prices, and checks
every plan's margin at median and heavy (p90) usage.

Used by `python -m app.scripts.token_economics` and GET /v1/admin/economics.
"""
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder import targets
from app.core.config import settings
from app.db.models import BuilderAppBuild, BuilderProject, BuilderUsageEvent
from app.services.plans import catalog

M = 1_000_000


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = min(len(values) - 1, max(0, int(round(p / 100 * (len(values) - 1)))))
    return values[k]


async def report(db: AsyncSession, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(BuilderUsageEvent, BuilderProject.owner_id, BuilderProject.target)
        .join(BuilderProject, BuilderProject.id == BuilderUsageEvent.project_id)
        .where(BuilderUsageEvent.created_at >= since))).all()

    tokens = prompt = completion = cached = 0
    model_cost = unpriced_tokens = 0.0
    images = 0
    image_cost = 0.0
    sandbox_seconds = 0.0
    sandbox_cost = 0.0
    by_stage: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost": 0.0})
    per_user_tokens: dict[str, int] = defaultdict(int)
    per_user_cost: dict[str, float] = defaultdict(float)
    projects: set[str] = set()

    for ev, owner, target_name in rows:
        projects.add(ev.project_id)
        cost = float(ev.cost_usd) if ev.cost_usd is not None else None
        if ev.kind == "model" and ev.unit == "tokens":
            q = int(ev.quantity or 0)
            meta = ev.meta or {}
            tokens += q
            prompt += int(meta.get("prompt_tokens") or 0)
            completion += int(meta.get("completion_tokens") or 0)
            cached += int(meta.get("cached_tokens") or 0)
            if cost is None:
                unpriced_tokens += q
            else:
                model_cost += cost
            stage = by_stage[str(meta.get("stage") or "unknown")]
            stage["calls"] += 1
            stage["tokens"] += q
            stage["cost"] += cost or 0.0
            per_user_tokens[owner] += q
            per_user_cost[owner] += cost or 0.0
        elif ev.kind == "model" and ev.unit == "images":
            images += int(ev.quantity or 0)
            c = cost if cost is not None else settings.IMAGE_COST_USD * int(ev.quantity or 0)
            image_cost += c
            per_user_cost[owner] += c
        elif ev.kind == "sandbox":
            secs = float(ev.quantity or 0)
            sandbox_seconds += secs
            c = cost if cost is not None else secs * targets.get(target_name).sandbox_cost_per_second()
            sandbox_cost += c
            per_user_cost[owner] += c

    builds = (await db.execute(select(BuilderAppBuild).where(
        BuilderAppBuild.created_at >= since, BuilderAppBuild.status == "finished"))).scalars().all()
    eas_cost = sum(settings.EAS_COST_IOS_USD if b.platform == "ios" else settings.EAS_COST_ANDROID_USD
                   for b in builds if b.account == "vivid")
    eas_revenue = sum(b.price for b in builds if b.account == "vivid") / M

    priced_tokens = max(tokens - unpriced_tokens, 1)
    model_per_m = model_cost / priced_tokens * M
    sandbox_per_m = sandbox_cost / max(tokens, 1) * M
    image_per_m = image_cost / max(tokens, 1) * M
    all_in_per_m = model_per_m + sandbox_per_m + image_per_m

    months = days / 30
    monthly_tokens = [t / months for t in per_user_tokens.values()]
    plans = []
    for plan in catalog.plans().values():
        allowance = plan.month_tokens
        cost_full = allowance / M * all_in_per_m
        p50 = min(_pct(monthly_tokens, 50), allowance)
        p90 = min(_pct(monthly_tokens, 90), allowance)
        price = plan.price_usd
        plans.append({
            "plan": plan.id, "price_usd": price, "month_credits": plan.month_credits,
            "month_tokens": allowance,
            "cost_if_fully_used_usd": round(cost_full, 2),
            "cost_at_p50_usd": round(p50 / M * all_in_per_m, 2),
            "cost_at_p90_usd": round(p90 / M * all_in_per_m, 2),
            "margin_if_fully_used": round(1 - cost_full / price, 3) if price else None,
            "margin_at_p90": round(1 - (p90 / M * all_in_per_m) / price, 3) if price else None,
        })

    return {
        "days": days, "since": since.isoformat(),
        "projects": len(projects), "users": len(per_user_tokens),
        "tokens": tokens, "prompt_tokens": prompt, "completion_tokens": completion,
        "cached_tokens": cached,
        "cache_hit_ratio": round(cached / prompt, 3) if prompt else None,
        "output_share": round(completion / max(prompt + completion, 1), 3),
        "unpriced_tokens": int(unpriced_tokens),
        "cost_usd": {"model": round(model_cost, 4), "sandbox": round(sandbox_cost, 4),
                     "images": round(image_cost, 4), "eas_builds": round(eas_cost, 2)},
        "per_million_tokens_usd": {"model": round(model_per_m, 4),
                                   "sandbox": round(sandbox_per_m, 4),
                                   "images": round(image_per_m, 4),
                                   "all_in": round(all_in_per_m, 4)},
        "sandbox_hours": round(sandbox_seconds / 3600, 2), "images": images,
        "by_stage": {k: {"calls": v["calls"], "tokens": v["tokens"],
                         "avg_tokens": v["tokens"] // max(v["calls"], 1),
                         "cost_usd": round(v["cost"], 4)} for k, v in by_stage.items()},
        "per_user_month": {"tokens_p50": int(_pct(monthly_tokens, 50)),
                           "tokens_p90": int(_pct(monthly_tokens, 90)),
                           "tokens_mean": int(statistics.fmean(monthly_tokens)) if monthly_tokens else 0,
                           "cost_p90_usd": round(_pct([c / months for c in per_user_cost.values()], 90), 4)},
        "cost_per_project_usd": round((model_cost + sandbox_cost + image_cost) / max(len(projects), 1), 4),
        "eas": {"builds": len(builds), "cost_usd": round(eas_cost, 2), "revenue_usd": round(eas_revenue, 2)},
        "plans": plans,
        "credits": {"tokens_per_credit": catalog.tokens_per_credit(),
                    "cost_per_credit_usd": round(all_in_per_m * catalog.tokens_per_credit() / M, 4),
                    "price_per_credit_usd": settings.PLAN_CREDIT_PRICE_USD,
                    "extra_credit_margin": round(
                        1 - all_in_per_m * catalog.tokens_per_credit() / M
                        / settings.PLAN_CREDIT_PRICE_USD, 3)},
    }
