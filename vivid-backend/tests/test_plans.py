"""Plans: usage sums over the rolling window and the month, the turn gate
refuses at the limit and lets extra credits through, overshoot is settled
against extra credits, Free stops at two apps, subscriptions are paid from
the wallet (with proration, grace and lapse), Max is for one person (old
"team" rows included), and the economics report prices a million tokens from real rows."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.models import BuilderProject, BuilderUsageEvent, Subscription
from app.services import economics
from app.services.plans import catalog, gate, subscriptions, usage
from app.services.wallet import fx, ledger
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def small_plans(monkeypatch):
    # 100 tokens a credit keeps the numbers small; allowances are in credits.
    monkeypatch.setattr(settings, "PLAN_TOKENS_PER_CREDIT", 100)
    monkeypatch.setattr(settings, "PLAN_FREE_WINDOW_CREDITS", 10)        # 1,000 tokens
    monkeypatch.setattr(settings, "PLAN_FREE_MONTH_CREDITS", 50)         # 5,000
    monkeypatch.setattr(settings, "PLAN_PRO_WINDOW_CREDITS", 100)
    monkeypatch.setattr(settings, "PLAN_PRO_MONTH_CREDITS", 500)         # 50,000
    monkeypatch.setattr(settings, "PLAN_MAX_WINDOW_CREDITS", 30)
    monkeypatch.setattr(settings, "PLAN_MAX_MONTH_CREDITS", 300)
    # Prices pinned so the arithmetic below does not follow launch pricing.
    monkeypatch.setattr(settings, "PLAN_PRO_PRICE_USD", 32.0)
    monkeypatch.setattr(settings, "PLAN_PRO_YEARLY_PRICE_USD", 26.0)
    monkeypatch.setattr(settings, "PLAN_MAX_PRICE_USD", 78.0)
    monkeypatch.setattr(settings, "PLAN_MAX_YEARLY_PRICE_USD", 62.0)
    monkeypatch.setattr(settings, "PLAN_IMAGE_TOKEN_EQUIVALENT", 100)
    fx.set_rates({"USD": 1.0, "NGN": 1500.0})


async def _project(maker, owner="u1", name="App") -> str:
    async with maker() as db:
        p = BuilderProject(owner_id=owner, name=name, mode="build")
        db.add(p)
        await db.commit()
        return p.id


async def _use(maker, project_id, tokens=0, images=0, ago=timedelta(0), cost=None):
    async with maker() as db:
        if tokens:
            db.add(BuilderUsageEvent(project_id=project_id, kind="model", quantity=tokens,
                                     unit="tokens", cost_usd=cost, created_at=NOW - ago,
                                     meta={"stage": "edit", "prompt_tokens": int(tokens * 0.9),
                                           "completion_tokens": tokens - int(tokens * 0.9),
                                           "cached_tokens": int(tokens * 0.6)}))
        if images:
            db.add(BuilderUsageEvent(project_id=project_id, kind="model", quantity=images,
                                     unit="images", created_at=NOW - ago))
        await db.commit()


async def _fund(maker, usd, user="u1", ref="f"):
    async with maker() as db:
        await ledger.credit(db, user, int(usd * 1e6), ledger.DEPOSIT_BANK, "test", f"{ref}-{user}-{usd}")
        await db.commit()


# ------------------------------------------------------------------- usage
async def test_window_and_month_count_tokens_and_images(maker):
    pid = await _project(maker)
    await _use(maker, pid, tokens=600, images=2)                    # 600 + 200
    await _use(maker, pid, tokens=900, ago=timedelta(hours=6))      # outside the window
    async with maker() as db:
        account = await usage.account_for(db, "u1")
        m = await usage.meter(db, account)
    assert account.plan.id == "free"
    assert (m.window_used, m.window_limit) == (800, 1000)
    assert m.month_used >= 800 and m.month_limit == 5000
    assert m.window_resets_at > NOW


# -------------------------------------------------------------------- gate
async def test_the_gate_refuses_past_the_window_and_extra_tokens_let_it_through(maker):
    pid = await _project(maker)
    await _use(maker, pid, tokens=1200)
    async with maker() as db:
        check = await gate.can_start_turn(db, "u1", pid)
    assert not check.ok and not check.read_only
    # Shown in credits: 1,200 tokens at 100 a credit.
    assert check.body()["window_used"] == 12 and check.body()["window_limit"] == 10
    assert "buy_credits" in check.body()["options"]

    await _fund(maker, 10)
    async with maker() as db:
        assert await subscriptions.buy_pack(db, "u1", settings.PLAN_CREDIT_PACKS[0]) == 10
        await db.commit()
        check = await gate.can_start_turn(db, "u1", pid)
    assert check.ok and check.extra_tokens == 1000 and check.body()["extra_credits"] == 10
    async with maker() as db:                                        # 10 credits at $0.30
        assert await ledger.balance(db, "u1") == 7_000_000

    # The turn uses 500 more, all beyond the allowance: 500 extra tokens go.
    await _use(maker, pid, tokens=500)
    async with maker() as db:
        taken = await gate.settle_turn(db, check)
        await db.commit()
        assert taken == 500
        assert (await ledger.wallet_for(db, "u1")).extra_tokens == 500      # 5 credits left


async def test_a_turn_that_crosses_the_limit_pays_only_the_overshoot(maker):
    pid = await _project(maker)
    await _use(maker, pid, tokens=900)
    async with maker() as db:
        wallet = await ledger.wallet_for(db, "u1")
        wallet.extra_tokens = 1000
        await db.commit()
        check = await gate.can_start_turn(db, "u1", pid)
    await _use(maker, pid, tokens=300)                              # 1200: 200 over
    async with maker() as db:
        assert await gate.settle_turn(db, check) == 200


async def test_free_has_two_apps_and_the_third_is_read_only_after_a_downgrade(maker):
    a = await _project(maker, name="a")
    b = await _project(maker, name="b")
    async with maker() as db:
        ok, account, owned = await gate.can_create_project(db, "u1")
    assert not ok and owned == 2 and account.plan.max_apps == 2
    c = await _project(maker, name="c")                             # made while on Pro
    async with maker() as db:
        (await db.get(BuilderProject, a)).updated_at = NOW - timedelta(days=3)
        await db.commit()
        oldest = await gate.can_start_turn(db, "u1", a)
        newest = await gate.can_start_turn(db, "u1", c)
    assert oldest.read_only and not oldest.ok
    assert newest.ok and b


# ---------------------------------------------------------- subscriptions
async def test_subscribing_is_paid_from_the_wallet(maker):
    async with maker() as db:
        with pytest.raises(ledger.InsufficientFunds):
            await subscriptions.subscribe(db, "u1", catalog.PRO)
        await db.rollback()
    await _fund(maker, 40)
    async with maker() as db:
        sub = await subscriptions.subscribe(db, "u1", catalog.PRO)
        await db.commit()
        assert sub.plan == "pro" and sub.status == "active"
        assert await ledger.balance(db, "u1") == 8_000_000          # $40 - $32
        account = await usage.account_for(db, "u1")
        assert account.plan.id == "pro" and account.plan.max_apps is None


async def test_an_upgrade_credits_the_unused_period(maker):
    await _fund(maker, 200)
    async with maker() as db:
        await subscriptions.subscribe(db, "u1", catalog.PRO)
        sub = await db.get(Subscription, "u1")
        # Halfway through the month.
        sub.period_start = NOW - timedelta(days=15)
        sub.period_end = NOW + timedelta(days=15)
        await db.commit()
        await subscriptions.subscribe(db, "u1", catalog.MAX)
        await db.commit()
        # 200 - 32 + ~16 back - 78 for Max
        balance = await ledger.balance(db, "u1")
    assert 105_500_000 < balance < 106_500_000


async def test_renewal_grace_and_lapse(maker):
    await _fund(maker, 32)
    async with maker() as db:
        await subscriptions.subscribe(db, "u1", catalog.PRO)
        sub = await db.get(Subscription, "u1")
        sub.period_end = NOW - timedelta(minutes=1)
        await db.commit()
        result = await subscriptions.renew_due(db)
        await db.commit()
        assert result == {"renewed": 0, "grace": 1, "lapsed": 0}
        assert (await usage.account_for(db, "u1")).plan.id == "pro"   # still Pro in grace
    await _fund(maker, 32, ref="g")
    async with maker() as db:
        assert (await subscriptions.renew_due(db))["renewed"] == 1
        await db.commit()
        sub = await db.get(Subscription, "u1")
        assert sub.status == "active" and sub.period_end.replace(tzinfo=timezone.utc) > NOW
        # Cancelled: kept to the end of the period, then gone.
        await subscriptions.cancel(db, "u1")
        sub.period_end = NOW - timedelta(minutes=1)
        await db.commit()
        assert (await subscriptions.renew_due(db))["lapsed"] == 1
        await db.commit()
        assert (await usage.account_for(db, "u1")).plan.id == "free"


async def test_max_is_one_persons_plan_and_old_team_rows_are_max(maker):
    await _fund(maker, 200)
    async with maker() as db:
        await subscriptions.subscribe(db, "u1", catalog.MAX)
        # A row written when the $1 plan was still called "team".
        db.add(Subscription(user_id="u2", plan="team", seats=3,
                            period_start=NOW, period_end=NOW + timedelta(days=30)))
        await db.commit()
    mine = await _project(maker, owner="u1")
    theirs = await _project(maker, owner="u2")
    await _use(maker, mine, tokens=2000)
    await _use(maker, theirs, tokens=3000)
    async with maker() as db:
        me = await usage.account_for(db, "u1")
        m = await usage.meter(db, me)
        legacy = await usage.account_for(db, "u2")
    assert me.plan.id == "max" and me.plan.name == "Max"
    # Only my own usage counts, against one person's allowance.
    assert m.window_used == 2000 and m.window_limit == 3000
    assert legacy.plan.id == "max" and legacy.owner_id == "u2"
    with pytest.raises(subscriptions.PlanError):
        async with maker() as db:
            await subscriptions.subscribe(db, "u1", "team")


# --------------------------------------------------------------- economics
async def test_the_report_prices_a_million_tokens(maker):
    pid = await _project(maker)
    await _use(maker, pid, tokens=2_000_000, cost=0.16)             # $0.08/M model
    await _use(maker, pid, images=10)
    async with maker() as db:
        db.add(BuilderUsageEvent(project_id=pid, kind="sandbox", quantity=3600, unit="seconds",
                                 cost_usd=0.13))
        await db.commit()
        r = await economics.report(db, days=30)
    per_m = r["per_million_tokens_usd"]
    assert per_m["model"] == pytest.approx(0.08)
    assert per_m["sandbox"] == pytest.approx(0.065)
    assert per_m["images"] == pytest.approx(10 * settings.IMAGE_COST_USD / 2)
    assert r["cache_hit_ratio"] == pytest.approx(0.6 / 0.9, abs=0.01)
    pro = next(p for p in r["plans"] if p["plan"] == "pro")
    assert pro["cost_if_fully_used_usd"] == pytest.approx(50_000 / 1e6 * per_m["all_in"], abs=0.01)
    assert r["credits"]["tokens_per_credit"] == 100
    assert r["credits"]["cost_per_credit_usd"] == pytest.approx(per_m["all_in"] * 100 / 1e6, abs=1e-4)
    assert pro["month_credits"] == 500


# ------------------------------------------------------------------ routes
def test_routes_enforce_the_plan(client, maker):
    import asyncio
    first = client.post("/v1/builder/projects", json={"skip_plan": True}).json()["id"]
    client.post("/v1/builder/projects", json={"skip_plan": True})
    third = client.post("/v1/builder/projects", json={"skip_plan": True})
    assert third.status_code == 402 and third.json()["error"]["code"] == "plan_limit"

    asyncio.run(_use(maker, first, tokens=1500))
    r = client.post(f"/v1/builder/projects/{first}/chat", json={"text": "add a page"})
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "limit_reached" and "Free" in err["message"]
    assert err["details"]["window_used"] == 15 and err["details"]["window_limit"] == 10
    assert "credits" in err["message"]
    assert err["details"]["window_resets_at"]
