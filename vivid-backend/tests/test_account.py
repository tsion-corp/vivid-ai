"""Deleting an account: refused while money is owed, otherwise the person's
things go now, the money records stay for seven years on an anonymised row,
and every token stops working. Plus the web handoff a store app uses to pay
on the web, and read_only on projects a plan no longer lets take turns."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db, get_session_user
from app.api.routes.auth import router as auth_router
from app.core import errors
from app.core.config import settings
from app.core.security import decode_token
from app.db.models import (ApiKey, BuilderProject, PushDevice, User, VividPayAccount,
                           VividPayCheckout, VividPayEntry, VividPayPayout, Wallet, WalletEntry)
from app.services import account, decane
from app.services.wallet import ledger
from tests.conftest import FakeRedis
from tests.test_builder_routes import maker  # noqa: F401


@pytest.fixture
def api(maker, monkeypatch):  # noqa: F811
    from app.api.routes import builder as builder_routes
    app = FastAPI()
    errors.install(app)
    app.include_router(auth_router, prefix="/v1")
    app.state.redis = FakeRedis()

    async def db():
        async with maker() as session:
            yield session

    # The user comes from the request's own session, as in production, so the
    # route's changes to the row are what gets committed.
    from fastapi import Depends

    async def user(session=Depends(get_db)):
        return await session.get(User, "u1")
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_session_user] = user

    async def no_kill(project_id, redis):
        pass
    monkeypatch.setattr(builder_routes.manager, "kill", no_kill)
    monkeypatch.setattr(builder_routes.snapshots, "delete_all", _none)
    monkeypatch.setattr(settings, "DECANE_APP_ID", "app-1")
    monkeypatch.setattr(settings, "DECANE_API_KEY", "dck_live_x")

    async def verify(email, code):
        if code != "123456":
            raise decane.DecaneError("INVALID_CODE", "bad", 400)
        return {"jwt": "tok", "userId": "u1", "profile": {"email": email}}
    monkeypatch.setattr(decane, "verify_email", verify)
    monkeypatch.setattr(decane, "start_email", _none)
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


async def _none(*a, **k):
    return None


async def _seed(maker, wallet_micro=0, earnings_kobo=0, pending_payout=False):  # noqa: F811
    async with maker() as db:
        u = await db.get(User, "u1")
        u.profile_email = "Ada@Example.com"
        u.name = "Ada"
        for name in ("Shop", "Blog"):
            db.add(BuilderProject(owner_id="u1", name=name, mode="build"))
        db.add(ApiKey(user_id="u1", owner_user_id="u1", client_id="vivid_web", name="k",
                      prefix="vivid_x", key_hash="h"))
        db.add(PushDevice(user_id="u1", token="ExponentPushToken[abcdefghij0123456789]"))
        if wallet_micro:
            await ledger.credit(db, "u1", wallet_micro, ledger.DEPOSIT_BANK, "test", "seed")
        db.add(VividPayAccount(user_id="u1", balance_kobo=earnings_kobo, kyc_status="verified",
                               kyc_name="ADA OBI"))
        await db.flush()
        pid = (await db.execute(select(BuilderProject.id).where(BuilderProject.name == "Shop"))).scalar()
        c = VividPayCheckout(project_id=pid, owner_id="u1", reference="MT-1", amount_kobo=100_000,
                             status="paid", paid_kobo=100_000, expires_at=datetime.now(timezone.utc))
        db.add(c)
        await db.flush()
        db.add(VividPayEntry(owner_id="u1", kind="payment", amount_kobo=95_000, balance_after=95_000,
                             provider="pouch", provider_ref="tr_1", checkout_id=c.id, project_id=pid))
        if pending_payout:
            db.add(VividPayPayout(owner_id="u1", amount_kobo=50_000, fee_kobo=2_000, stamp_duty_kobo=0,
                                  status="pending", account_number="0123456789", bank_name="GTB",
                                  recipient_name="ADA OBI", bank_account_id="b"))
        await db.commit()


def test_refused_while_money_is_owed(api, maker):
    asyncio.run(_seed(maker, earnings_kobo=95_000, pending_payout=True))
    pre = api.get("/v1/auth/me/deletion").json()
    assert [b["code"] for b in pre["blockers"]] == ["pending_withdrawal", "earnings_unwithdrawn"]
    assert pre["projects"] == 2 and pre["confirm_email"] == "ad*@example.com"
    r = api.request("DELETE", "/v1/auth/me", json={"code": "123456"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_delete"
    assert r.json()["error"]["details"]["blockers"][0]["code"] == "pending_withdrawal"


def test_deletion_needs_the_emailed_code_then_keeps_only_the_money_records(api, maker):
    asyncio.run(_seed(maker, wallet_micro=2_000_000))            # $2: forfeited
    sent = api.post("/v1/auth/me/deletion-code")
    assert sent.status_code == 202 and sent.json()["sent_to"] == "ad*@example.com"
    bad = api.request("DELETE", "/v1/auth/me", json={"code": "000000"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_code"
    assert api.get("/v1/auth/me/deletion").json()["wallet_outcome"] == "forfeited"

    r = api.request("DELETE", "/v1/auth/me", json={"code": "123456"})
    assert r.status_code == 200, r.json()
    assert r.json() == {"deleted": True, "projects_deleted": 2, "wallet_outcome": "forfeited"}

    async def after():
        async with maker() as db:
            u = await db.get(User, "u1")
            projects = (await db.execute(select(BuilderProject).where(BuilderProject.owner_id == "u1"))).all()
            keys = (await db.execute(select(ApiKey).where(ApiKey.user_id == "u1"))).all()
            phones = (await db.execute(select(PushDevice).where(PushDevice.user_id == "u1"))).all()
            checkouts = (await db.execute(select(VividPayCheckout).where(VividPayCheckout.owner_id == "u1"))).scalars().all()
            entries = (await db.execute(select(VividPayEntry).where(VividPayEntry.owner_id == "u1"))).all()
            wallet = await db.get(Wallet, "u1")
            kyc = await db.get(VividPayAccount, "u1")
            return u, projects, keys, phones, checkouts, entries, wallet, kyc
    u, projects, keys, phones, checkouts, entries, wallet, kyc = asyncio.run(after())
    assert u.deleted_at is not None and u.email == "deleted_u1@users.vivid"
    assert u.name is None and u.profile_email is None and u.password_hash == "!deleted"
    assert projects == [] and keys == [] and phones == []
    # Money and KYC records stay, the checkout now without its project.
    assert len(checkouts) == 1 and checkouts[0].project_id is None and checkouts[0].paid_kobo == 100_000
    assert len(entries) == 1 and kyc.kyc_name == "ADA OBI"
    assert wallet.balance_micro == 0


async def test_a_deleted_user_is_refused_and_a_large_balance_waits_for_support(maker, monkeypatch):
    from app.api import deps
    from app.core.security import create_token_pair
    await _seed(maker, wallet_micro=20_000_000)                    # $20: refunded by support
    async with maker() as db:
        u = await db.get(User, "u1")
        out = await account.delete_account(db, u, _none)
        await db.commit()
        assert out["wallet_outcome"] == "refund_by_support"
        assert (await db.get(Wallet, "u1")).balance_micro == 20_000_000
        token = create_token_pair("u1")["access_token"]
        with pytest.raises(errors.APIError) as e:
            await deps._from_access_token(token, db)
        assert e.value.status == 401


async def test_records_are_purged_after_seven_years(maker):
    await _seed(maker, wallet_micro=1_000_000)
    async with maker() as db:
        u = await db.get(User, "u1")
        await account.delete_account(db, u, _none)
        await db.commit()
    async with maker() as db:
        assert await account.purge_expired(db) == 0                # too soon
        u = await db.get(User, "u1")
        u.deleted_at = datetime.now(timezone.utc) - timedelta(days=7 * 365 + 1)
        await db.commit()
    async with maker() as db:
        assert await account.purge_expired(db) == 1
        await db.commit()
        assert await db.get(User, "u1") is None
        assert (await db.execute(select(VividPayEntry))).all() == []
        assert (await db.execute(select(WalletEntry))).all() == []


def test_handoff_opens_the_web_signed_in_once(api, monkeypatch):
    monkeypatch.setattr(settings, "WEB_BASE_URL", "https://vividbuild.ai")
    out = api.post("/v1/auth/handoff", json={"next": "/settings/billing"}).json()
    assert out["url"].startswith("https://vividbuild.ai/auth/handoff?token=") and out["url"].endswith("&next=/settings/billing")
    assert decode_token(out["token"], "handoff") == "u1" and out["expires_in"] == 120
    # An outside URL as `next` is ignored.
    assert api.post("/v1/auth/handoff", json={"next": "//evil.example"}).json()["url"].endswith("&next=/settings/billing")
    pair = api.post("/v1/auth/handoff/exchange", json={"token": out["token"]})
    assert pair.status_code == 200 and pair.json()["user"]["id"] == "u1"
    again = api.post("/v1/auth/handoff/exchange", json={"token": out["token"]})
    assert again.status_code == 401 and again.json()["error"]["code"] == "handoff_used"
    assert api.post("/v1/auth/handoff/exchange", json={"token": "nope"}).json()["error"]["code"] == "handoff_expired"
