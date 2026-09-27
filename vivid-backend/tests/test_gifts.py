"""Gifts: credits come out of the giver's month and are the recipient's for
30 days, spent before extra credits; a plan is paid by the giver and
granted, extended or upgraded when claimed; unclaimed or cancelled plan
gifts are refunded; a link is claimed once, never by its giver."""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes.gifts import router as gifts_router
from app.core.config import settings
from app.db.models import Gift, Subscription
from app.services import mail
from app.services.plans import gate, gifts, subscriptions, usage
from app.services.wallet import ledger
from tests.test_builder_routes import client, fake_blob, fake_manager, maker  # noqa: F401
from tests.test_plans import _fund, _project, _use, small_plans  # noqa: F401


async def _pro(maker, user="u1"):
    await _fund(maker, 100, user=user, ref="pro")
    async with maker() as db:
        await subscriptions.subscribe(db, user, "pro")
        await db.commit()


async def test_credit_gifts_come_out_of_the_month_and_are_spent_first(maker):
    async with maker() as db:
        with pytest.raises(gifts.GiftError) as e:                          # Free cannot give credits
            await gifts.give_credits(db, "u1", "b@x.co", 5)
        assert e.value.code == "plan_required"
    await _pro(maker)
    async with maker() as db:
        with pytest.raises(gifts.GiftError) as e:
            await gifts.give_credits(db, "u1", "b@x.co", 501)                  # Pro has 500 a month
        assert e.value.code == "not_enough_credits"
        gift = await gifts.give_credits(db, "u1", "b@x.co", 200, "for your shop")
        await db.commit()
        meter = await usage.meter(db, await usage.account_for(db, "u1"))
        assert meter.month_used == 200 * 100                                  # given = used
        token = gift.token

    async with maker() as db:
        with pytest.raises(gifts.GiftError) as e:
            await gifts.claim(db, "u1", token)
        assert e.value.code == "own_gift"
        claimed = await gifts.claim(db, "u2", token)
        await db.commit()
        assert claimed.gift.remaining == 20_000 and await gifts.balance(db, "u2") == 20_000
        with pytest.raises(gifts.GiftError) as e:
            await gifts.claim(db, "u2", token)
        assert e.value.code == "gift_gone" and e.value.status == 410

    # u2 on Free, past the window: the gift lets the turn through, and pays first.
    pid = await _project(maker, owner="u2")
    await _use(maker, pid, tokens=1200)
    async with maker() as db:
        wallet = await ledger.wallet_for(db, "u2")
        wallet.extra_tokens = 1000
        await db.commit()
        check = await gate.can_start_turn(db, "u2", pid)
        assert check.ok and check.body()["gift_credits"] == 200
    await _use(maker, pid, tokens=300)
    async with maker() as db:
        assert await gate.settle_turn(db, check) == 300
        await db.commit()
        assert await gifts.balance(db, "u2") == 19_700 and (await ledger.wallet_for(db, "u2")).extra_tokens == 1000

    # Expired gift credits no longer count.
    async with maker() as db:
        row = await db.get(Gift, claimed.gift.id)
        row.use_by = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        assert await gifts.balance(db, "u2") == 0


async def test_plan_gifts_are_paid_granted_and_refunded(maker):
    async with maker() as db:
        with pytest.raises(ledger.InsufficientFunds):
            await gifts.give_plan(db, "u1", "b@x.co", "pro", False)
    await _fund(maker, 200)
    async with maker() as db:
        gift = await gifts.give_plan(db, "u1", "b@x.co", "pro", False)
        await db.commit()
        assert await ledger.balance(db, "u1") == 168_000_000                  # $200 - $32
        claimed = await gifts.claim(db, "u2", gift.token)
        await db.commit()
        sub = await db.get(Subscription, "u2")
        assert sub.plan == "pro" and not sub.auto_renew and claimed.subscription is sub

        # The same plan again: a month more.
        end = sub.period_end
        again = await gifts.give_plan(db, "u1", "b@x.co", "pro", False)
        await db.commit()
        await gifts.claim(db, "u2", again.token)
        await db.commit()
        assert (await db.get(Subscription, "u2")).period_end > end

        # Max over Pro: upgraded, the unused Pro time back to the recipient.
        up = await gifts.give_plan(db, "u1", "b@x.co", "max", False)
        await db.commit()
        await gifts.claim(db, "u2", up.token)
        await db.commit()
        assert (await db.get(Subscription, "u2")).plan == "max" and await ledger.balance(db, "u2") > 0

        # Pro to someone on Max is refused; the giver cancels for a refund.
        down = await gifts.give_plan(db, "u1", "b@x.co", "pro", False)
        await db.commit()
        down_id = down.id
        with pytest.raises(gifts.GiftError) as e:
            await gifts.claim(db, "u2", down.token)
        assert e.value.code == "already_higher"
        await db.rollback()
        before = await ledger.balance(db, "u1")
        await gifts.cancel(db, "u1", down_id)
        await db.commit()
        assert await ledger.balance(db, "u1") == before + 32_000_000

        # Unclaimed past its date: refunded by the hourly pass.
        late = await gifts.give_plan(db, "u1", "b@x.co", "pro", False)
        late.claim_by = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        before = await ledger.balance(db, "u1")
        assert await gifts.expire_due(db) == 1
        await db.commit()
        assert await ledger.balance(db, "u1") == before + 32_000_000
        assert gifts.status_of(await db.get(Gift, late.id)) == "cancelled"


def test_gift_routes(client, maker, monkeypatch):  # noqa: F811
    import asyncio
    client.app.include_router(gifts_router, prefix="/v1")
    sent = []

    async def send(to, subject, text, html=None, reply_to=None):
        sent.append((to, subject, text))
        return True
    monkeypatch.setattr(mail, "send", send)
    asyncio.run(_fund(maker, 100))

    assert client.post("/v1/me/gifts", json={"kind": "credits", "email": "b@x.co", "credits": 5}).status_code == 402
    r = client.post("/v1/me/gifts", json={"kind": "plan", "email": "b@x.co", "plan": "pro", "message": "Build it!"})
    assert r.status_code == 201, r.json()
    gift = r.json()
    assert gift["status"] == "pending" and gift["emailed"] and gift["amount_usd"] == 32 and gift["url"] in sent[0][2]
    token = gift["url"].rsplit("/", 1)[-1]
    assert client.get(f"/v1/gifts/{token}").json()["message"] == "Build it!"

    client.as_user("u2")
    claimed = client.post(f"/v1/gifts/{token}/claim").json()
    assert claimed["plan"] == "pro" and claimed["plan_until"]
    mine = client.get("/v1/me/gifts").json()
    assert [g["plan"] for g in mine["received"]] == ["pro"] and mine["sent"] == []
    assert mine["received"][0]["email"] == ""                                 # the giver's typed address stays theirs
    assert client.post(f"/v1/gifts/{token}/claim").status_code == 410
    client.as_user("u1")
    assert client.get("/v1/me/gifts").json()["sent"][0]["status"] == "claimed"
    assert client.delete(f"/v1/me/gifts/{gift['id']}").status_code == 409     # claimed: no take-backs
    r = client.post("/v1/me/gifts", json={"kind": "plan", "email": "b@x.co", "plan": "max"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "insufficient_funds"
    assert client.get("/v1/gifts/nope").status_code == 404
