"""What a million builder tokens costs us, from real usage, and each plan's
margin at that cost.

    python -m app.scripts.token_economics [--days 30] [--json]

Run on the server inside the backend container (it reads the production
database). Re-tune the PLAN_* settings from its output.
"""
import argparse
import asyncio
import json

from app.db.session import async_session
from app.services.economics import report


def _print(r: dict) -> None:
    per_m = r["per_million_tokens_usd"]
    print(f"Last {r['days']} days: {r['users']} users, {r['projects']} projects, "
          f"{r['tokens']:,} tokens")
    print(f"  cache hit {r['cache_hit_ratio']}, output share {r['output_share']}, "
          f"unpriced tokens {r['unpriced_tokens']:,}")
    print(f"  cost per 1M tokens: model ${per_m['model']:.4f} + sandbox ${per_m['sandbox']:.4f} "
          f"+ images ${per_m['images']:.4f} = ${per_m['all_in']:.4f}")
    print(f"  cost per project ${r['cost_per_project_usd']:.4f}; sandbox {r['sandbox_hours']} h; "
          f"{r['images']} images")
    u = r["per_user_month"]
    print(f"  per user per month: p50 {u['tokens_p50']:,} tokens, p90 {u['tokens_p90']:,} "
          f"(${u['cost_p90_usd']:.2f})")
    print("  by stage:")
    for stage, v in sorted(r["by_stage"].items(), key=lambda kv: -kv[1]["tokens"]):
        print(f"    {stage:<12} {v['calls']:>6} calls  {v['avg_tokens']:>9,} avg tokens  ${v['cost_usd']:.4f}")
    print("  plans:")
    for p in r["plans"]:
        print(f"    {p['plan']:<5} ${p['price_usd']:>5.2f}  {p['month_tokens'] / 1e6:>5.0f}M/mo  "
              f"cost if all used ${p['cost_if_fully_used_usd']:.2f}  margin {p['margin_if_fully_used']}  "
              f"at p90 {p['margin_at_p90']}")
    print(f"  extra tokens at ${r['extra_tokens']['price_per_million_usd']}/M: margin {r['extra_tokens']['margin']}")
    print(f"  EAS: {r['eas']['builds']} builds, cost ${r['eas']['cost_usd']}, revenue ${r['eas']['revenue_usd']}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    async with async_session() as db:
        r = await report(db, args.days)
    print(json.dumps(r, indent=2, default=str)) if args.json else _print(r)


if __name__ == "__main__":
    asyncio.run(main())
