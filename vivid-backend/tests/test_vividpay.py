"""Vivid Pay: an app's customer pays by transfer into an account made for
their order; the owner's earnings get the money less Vivid's fee, once;
the money is moved to the owner's earnings account on Pouch; withdrawals
need a verified BVN and an account in that name, take the money at once and
give it back if the bank transfer fails; the public API honours a key only
from the app's own origins, and preview checkouts never touch Pouch."""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_db, get_principal
from app.api.routes import webhooks as webhook_routes
from app.api.routes.earnings import router as earnings_router
from app.api.routes.pay import router as pay_router
from app.api.routes.webhooks import router as webhooks_router
from app.builder import secrets as vault
from app.core import errors
from app.core.config import settings
from app.db.models import (BuilderProject, User, VividPayAccount, VividPayCheckout,
                           VividPayEntry, VividPayPayout, VividPayProject)
from app.services.vividpay import (VividPayError, checkouts, earnings, events, fee_for,
                                   key_hash, kyc, payouts)
from app.services.wallet import deposits, pouch
from tests.conftest import FakeRedis
from tests.test_builder_routes import maker  # noqa: F401

PUBLISHED = "https://mamas-kitchen-ab12cd.vivid-apps.pages.dev"


class FakePouch:
    """Stands in for every Pouch call Vivid Pay makes; records them."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.balance = 10**12
        self.refuse_payout: str | None = None
        self.unreachable = False
        self.transfers: dict[str, dict] = {}
        self.payouts: dict[str, dict] = {}
        self.n = 0

    def install(self, monkeypatch):
        monkeypatch.setattr(settings, "POUCH_API_KEY", "sk_test")
        for name in ("ensure_customer_ref", "open_account", "account_balance", "banks",
                     "validate_account", "payout_quote", "create_payout", "get_payout",
                     "find_payout", "kyc_bvn", "find_transfer", "create_static_address"):
            monkeypatch.setattr(pouch, name, getattr(self, name))

    async def ensure_customer_ref(self, ref, first, last, email=None, phone=None):
        self.calls.append(("customer", ref, first, last))
        return f"cus_{ref}"

    async def open_account(self, customer_id, key, funding_limit_kobo=None):
        self.n += 1
        self.calls.append(("account", customer_id, funding_limit_kobo))
        return {"id": f"va_{self.n}", "account_number": f"29000000{self.n:02d}",
                "account_name": "Mamas Kitchen via Vivid", "bank_name": "Paga"}

    async def account_balance(self, va_id):
        return self.balance

    async def banks(self):
        return [{"uuid": "PAGA-UUID", "name": "Paga"}, {"uuid": "GTB-UUID", "name": "GTBank"}]

    async def validate_account(self, number, bank_uuid):
        return {"account_name": "ADA OBI EZE", "bank_name": "GTBank"}

    async def payout_quote(self, amount):
        return 5_000, (5_000 if amount >= 1_000_000 else 0)

    async def create_payout(self, va_id, amount, number, bank_uuid, reference, narration):
        self.calls.append(("payout", va_id, amount, number, bank_uuid, reference))
        if self.unreachable:
            raise pouch.PouchError("could not reach the bank partner", unreachable=True)
        if self.refuse_payout:
            raise pouch.PouchError(self.refuse_payout)
        pid = f"po_{len(self.payouts) + 1}"
        self.payouts[pid] = {"id": pid, "reference": reference, "status": "pending"}
        return self.payouts[pid]

    async def get_payout(self, pid):
        return self.payouts[pid]

    async def find_payout(self, reference, pages=3):
        return next((p for p in self.payouts.values() if p["reference"] == reference), None)

    async def create_static_address(self, va_id, chain_id, refund, kyc):
        self.calls.append(("static_address", va_id, chain_id, refund, kyc["full_name"]))
        return {"id": f"sa_{va_id}", "deposit_address": f"0xdep{va_id}", "network_type": "evm"}

    async def kyc_bvn(self, bvn, first, last, dob, reference):
        self.calls.append(("kyc", bvn))
        if bvn == "22222222222":
            return {"verified": True, "full_name": "ADA OBI EZE", "response_code": "00"}
        return {"verified": False, "response_code": "25"}

    async def find_transfer(self, tid, pages=5):
        return self.transfers.get(tid)


@pytest.fixture
def fake(monkeypatch):
    f = FakePouch()
    f.install(monkeypatch)
    monkeypatch.setattr(settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    if hasattr(vault, "_fernet") and hasattr(vault._fernet, "cache_clear"):
        vault._fernet.cache_clear()
    monkeypatch.setattr(settings, "VIVIDPAY_FEE_BPS", 150)
    monkeypatch.setattr(settings, "VIVIDPAY_MIN_FEE_KOBO", 10_000)
    monkeypatch.setattr(settings, "VIVIDPAY_FIXED_FEE_KOBO", 0)     # the flows below use a plain 1.5%
    monkeypatch.setattr(settings, "VIVIDPAY_FEE_CAP_KOBO", 200_000)
    monkeypatch.setattr(settings, "POUCH_AMOUNTS_IN_KOBO", True)
    monkeypatch.setattr(checkouts, "_BANK_UUIDS", {})

    async def quiet(pay, c):
        pass
    monkeypatch.setattr(checkouts, "notify_app", quiet)
    return f


async def _setup(maker, published=PUBLISHED, earnings_va=True) -> tuple[str, str, str]:
    """A project with Vivid Pay on; returns (project id, publishable, secret)."""
    async with maker() as db:
        p = BuilderProject(owner_id="u1", name="Mama's Kitchen", mode="build",
                           published_url=published)
        db.add(p)
        await db.flush()
        secret = "vsk_test_secret"
        db.add(VividPayProject(project_id=p.id, owner_id="u1", publishable_key="vpk_test",
                               secret_key_enc=vault.encrypt(secret), secret_key_hash=key_hash(secret),
                               webhook_url=None))
        if earnings_va:
            db.add(VividPayAccount(user_id="u1", earnings_va_id="va_earn",
                                   earnings_account_number="2900009999", earnings_bank_name="Paga"))
        await db.commit()
        return p.id, "vpk_test", secret


async def _checkout(maker, pid, amount=1_500_000, reference="order-1", mode="live"):
    async with maker() as db:
        pay = await db.get(VividPayProject, pid)
        project = await db.get(BuilderProject, pid)
        c = await checkouts.create(db, pay, project, amount, reference, {"name": "Tunde"}, None, mode)
        await db.commit()
        return c.id


# ------------------------------------------------------------------- money
def test_fee_is_the_larger_of_the_rate_and_the_minimum_plus_a_flat_part(monkeypatch):
    for name in ("VIVIDPAY_FEE_BPS", "VIVIDPAY_MIN_FEE_KOBO", "VIVIDPAY_FIXED_FEE_KOBO", "VIVIDPAY_FEE_CAP_KOBO"):
        monkeypatch.setattr(settings, name, type(settings).model_fields[name].default)
    assert fee_for(35_000) == 4_500                # ₦350: ₦25 minimum + ₦20
    assert fee_for(100_000) == 4_500               # ₦1,000: 1.5% is ₦15, so ₦25 + ₦20
    assert fee_for(1_000_000) == 17_000            # ₦10,000: ₦150 + ₦20
    assert fee_for(50_000_000) == 200_000          # the ₦2,000 cap
    assert fee_for(3_000) == 3_000                 # never more than the payment


async def test_a_checkout_opens_an_account_limited_to_the_order(maker, fake):
    pid, _, _ = await _setup(maker)
    cid = await _checkout(maker, pid)
    assert await _checkout(maker, pid) == cid                     # same reference, same checkout
    kinds = [c[0] for c in fake.calls]
    assert kinds == ["customer", "account"] and fake.calls[1][2] == 1_500_000
    assert fake.calls[0][2:] == ("Mama s Kitchen", "via Vivid")
    with pytest.raises(VividPayError):
        await _checkout(maker, pid, amount=999_900)               # same order, other amount
    async with maker() as db:
        c = await db.get(VividPayCheckout, cid)
        assert c.va_id == "va_1" and c.account_number == "2900000001" and c.status == "pending"


async def test_a_test_checkout_never_touches_pouch(maker, fake):
    pid, _, _ = await _setup(maker)
    cid = await _checkout(maker, pid, mode="test")
    assert fake.calls == []
    async with maker() as db:
        c = await db.get(VividPayCheckout, cid)
        await checkouts.simulate(db, c)
        await db.commit()
        assert c.status == "paid" and c.account_number == "0000000000"
        assert (await earnings.account_for(db, "u1")).balance_kobo == 0   # no real money


async def test_a_transfer_pays_the_order_once_and_moves_the_money(maker, fake):
    pid, _, _ = await _setup(maker)
    cid = await _checkout(maker, pid)
    transfer = {"id": "tr_1", "virtual_account_id": "va_1", "amount": 1_500_000,
                "net_amount": 1_490_000, "payer_name": "Tunde"}
    async with maker() as db:
        assert (await events.on_transfer(db, transfer)).status == "paid"
        assert await events.on_transfer(db, transfer) is None          # seen twice, paid once
        account = await earnings.account_for(db, "u1")
        # Net of Pouch's own ₦100, less Vivid's 1.5% of the ₦15,000 paid.
        assert account.balance_kobo == 1_490_000 - 22_500
        c = await db.get(VividPayCheckout, cid)
        assert c.fee_kobo == 22_500 and c.sweep_status == "done" and c.swept_kobo == 1_490_000 - 22_500
    sweeps = [c for c in fake.calls if c[0] == "payout"]
    assert sweeps == [("payout", "va_1", 1_467_500, "2900009999", "PAGA-UUID",
                       f"sweep-{cid.replace('-', '')}-0")]


async def test_underpaid_is_partial_and_late_money_is_still_the_owners(maker, fake):
    pid, _, _ = await _setup(maker)
    cid = await _checkout(maker, pid)
    async with maker() as db:
        c = await db.get(VividPayCheckout, cid)
        await checkouts.record_transfer(db, c, {"id": "tr_a", "amount": 1_000_000})
        assert c.status == "partial" and not c.late
        c.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await checkouts.record_transfer(db, c, {"id": "tr_b", "amount": 500_000})
        await db.commit()
        assert c.status == "paid" and c.paid_kobo == 1_500_000


async def test_a_webhook_routes_top_ups_and_order_payments(maker, fake, monkeypatch):
    pid, _, _ = await _setup(maker)
    await _checkout(maker, pid)
    fake.transfers["tr_9"] = {"id": "tr_9", "virtual_account_id": "va_1", "amount": 1_500_000}
    async with maker() as db:
        out = await deposits.on_pouch_event(db, {"event": "virtual_account.credited",
                                                 "data": {"id": "tr_9", "amount": 10**12}})
        assert isinstance(out, VividPayCheckout) and out.status == "paid"
        # A forged transfer the API does not list pays nothing.
        assert await deposits.on_pouch_event(db, {"event": "virtual_account.credited",
                                                  "data": {"id": "tr_forged"}}) is None


# ---------------------------------------------------------------- withdrawals
async def _earned(maker, kobo):
    async with maker() as db:
        await earnings.post(db, "u1", kobo, earnings.PAYMENT, "pouch", f"seed-{kobo}")
        await db.commit()


async def test_kyc_and_the_name_on_the_bank_account(maker, fake):
    await _setup(maker)
    async with maker() as db:
        with pytest.raises(VividPayError) as e:
            await payouts.add_bank_account(db, "u1", "0123456789", "GTB-UUID")
        assert e.value.code == "kyc_required"
        with pytest.raises(VividPayError):
            await kyc.verify(db, "u1", "11111111111", "Ada", "Eze", None)
        account = await kyc.verify(db, "u1", "22222222222", "Ada", "Eze", None)
        await db.commit()
        assert account.kyc_status == "verified" and account.kyc_name == "ADA OBI EZE"
        assert vault.decrypt(account.kyc_bvn_enc) == "22222222222"
        bank = await payouts.add_bank_account(db, "u1", "0123456789", "GTB-UUID")
        assert bank.account_name == "ADA OBI EZE"
    assert kyc.names_match("ADA OBI EZE", "EZE ADA")
    assert not kyc.names_match("ADA OBI EZE", "JOHN DOE EZE")


async def _verified_with_bank(maker, fake) -> str:
    async with maker() as db:
        await kyc.verify(db, "u1", "22222222222", "Ada", "Eze", None)
        bank = await payouts.add_bank_account(db, "u1", "0123456789", "GTB-UUID")
        await db.commit()
        return bank.id


async def test_a_withdrawal_takes_the_money_and_success_clears_pending(maker, fake):
    await _setup(maker)
    bank_id = await _verified_with_bank(maker, fake)
    await _earned(maker, 5_000_000)
    async with maker() as db:
        p = await payouts.withdraw(db, "u1", 2_000_000, bank_id)
        await db.commit()
        account = await earnings.account_for(db, "u1")
        # ₦20,000 + ₦50 fee + ₦50 stamp duty (₦10,000 and above).
        assert account.balance_kobo == 5_000_000 - 2_010_000 and account.pending_kobo == 2_000_000
        assert p.status == "pending" and p.pouch_payout_id == "po_1"
        # As Pouch really answers: latest_status, and the fee it charged
        # (₦20, less than the ₦50 taken up front, which comes back).
        fake.payouts["po_1"].pop("status")
        fake.payouts["po_1"].update(latest_status="success", fee="2000")
        await events.on_payout_event(db, {"event": "payout.success", "data": {"id": "po_1"}})
        await db.commit()
        account = await earnings.account_for(db, "u1")
        assert p.status == "success" and account.pending_kobo == 0
        assert p.fee_kobo == 2_000
        assert account.balance_kobo == 5_000_000 - 2_000_000 - 2_000 - 5_000   # stamp duty stays


async def test_a_refused_or_failed_withdrawal_comes_back_once(maker, fake):
    await _setup(maker)
    bank_id = await _verified_with_bank(maker, fake)
    await _earned(maker, 5_000_000)
    fake.refuse_payout = "INSUFFICIENT_BALANCE"
    async with maker() as db:
        p = await payouts.withdraw(db, "u1", 2_000_000, bank_id)
        await db.commit()
        assert p.status == "failed" and (await earnings.account_for(db, "u1")).balance_kobo == 5_000_000
    fake.refuse_payout = None
    async with maker() as db:
        p = await payouts.withdraw(db, "u1", 1_000_000, bank_id)
        await db.commit()
        fake.payouts[p.pouch_payout_id]["status"] = "failed"
        for _ in range(2):                                         # reported twice
            await events.on_payout_event(db, {"event": "payout.failed",
                                              "data": {"id": p.pouch_payout_id}})
        assert (await earnings.account_for(db, "u1")).balance_kobo == 5_000_000
        reversals = [e for e in await earnings.entries(db, "u1") if e.kind == earnings.REVERSAL]
        assert len(reversals) == 2                                  # one per withdrawal, never more


async def test_an_unanswered_payout_waits_instead_of_paying_back(maker, fake):
    await _setup(maker)
    bank_id = await _verified_with_bank(maker, fake)
    await _earned(maker, 5_000_000)
    fake.unreachable = True
    async with maker() as db:
        p = await payouts.withdraw(db, "u1", 1_000_000, bank_id)
        await db.commit()
        assert p.status == "pending" and p.pouch_payout_id is None
        # Pouch did make it: the reconciler finds it by reference.
        fake.payouts["po_x"] = {"id": "po_x", "reference": payouts.reference_of(p), "status": "success"}
        await payouts.refresh(db, p)
        await db.commit()
        assert p.status == "success" and p.pouch_payout_id == "po_x"


async def test_limits_before_anything_moves(maker, fake):
    await _setup(maker)
    bank_id = await _verified_with_bank(maker, fake)
    await _earned(maker, 150_000)
    async with maker() as db:
        with pytest.raises(VividPayError):
            await payouts.withdraw(db, "u1", 50_000, bank_id)          # under the minimum
        with pytest.raises(earnings.InsufficientEarnings):
            await payouts.withdraw(db, "u1", 150_000, bank_id)         # fees on top
    assert not [c for c in fake.calls if c[0] == "payout"]


# ----------------------------------------------------------------- the API
@pytest.fixture
def api(maker, monkeypatch, fake):
    monkeypatch.setattr(webhook_routes, "async_session", maker)
    app = FastAPI()
    errors.install(app)
    for r in (pay_router, earnings_router, webhooks_router):
        app.include_router(r, prefix="/v1")
    app.state.redis = FakeRedis()

    async def db():
        async with maker() as session:
            yield session

    async def principal():
        async with maker() as session:
            return Principal(user=await session.get(User, "u1"), client_id="vivid_web")
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_principal] = principal
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


def _create(api, origin, key="vpk_test", reference="o-1"):
    return api.post("/v1/pay/checkouts", headers={"origin": origin, "content-type": "text/plain"},
                    content=json.dumps({"key": key, "amount_kobo": 1_500_000, "reference": reference,
                                        "customer": {"name": "Tunde", "email": "t@x.ng"}}))


def test_the_public_api_honours_the_key_only_from_the_apps_origins(api, maker, fake):
    asyncio.run(_setup(maker))
    live = _create(api, PUBLISHED)
    assert live.status_code == 201 and live.json()["mode"] == "live"
    assert live.headers["access-control-allow-origin"] == "*"
    test = _create(api, "https://5173-abc123.e2b.app", reference="o-2")
    assert test.json()["mode"] == "test" and test.json()["account_number"] == "0000000000"
    assert _create(api, "https://evil.example", reference="o-3").status_code == 403
    assert _create(api, PUBLISHED, key="vpk_nope", reference="o-4").status_code == 401

    cid = test.json()["id"]
    assert api.get(f"/v1/pay/checkouts/{cid}?key=vpk_test").json()["status"] == "pending"
    paid = api.post(f"/v1/pay/checkouts/{cid}/simulate", content=json.dumps({"key": "vpk_test"}))
    assert paid.json()["status"] == "paid"
    live_id = live.json()["id"]
    assert api.post(f"/v1/pay/checkouts/{live_id}/simulate",
                    content=json.dumps({"key": "vpk_test"})).status_code == 403

    server = api.get("/v1/pay/checkouts?reference=o-1",
                     headers={"authorization": "Bearer vsk_test_secret"})
    assert server.json()["id"] == live_id
    assert api.get("/v1/pay/checkouts?reference=o-1",
                   headers={"authorization": "Bearer vsk_wrong"}).status_code == 401


def test_the_owner_sees_earnings_and_withdraws(api, maker, fake):
    asyncio.run(_setup(maker))
    asyncio.run(_earned(maker, 5_000_000))
    assert api.post("/v1/earnings/withdrawals", json={"amount_kobo": 1_000_000,
                                                      "bank_account_id": "x"}).status_code == 403
    assert api.post("/v1/earnings/kyc", json={"bvn": "22222222222", "first_name": "Ada",
                                              "last_name": "Eze"}).json()["status"] == "verified"
    bank = api.post("/v1/earnings/bank-accounts", json={"account_number": "0123456789",
                                                        "bank_uuid": "GTB-UUID"}).json()
    quote = api.post("/v1/earnings/withdrawals/quote", json={"amount_kobo": 1_000_000}).json()
    assert quote["total_kobo"] == 1_010_000
    out = api.post("/v1/earnings/withdrawals", json={"amount_kobo": 1_000_000,
                                                     "bank_account_id": bank["id"]})
    assert out.status_code == 201 and out.json()["status"] == "pending"
    me = api.get("/v1/earnings").json()
    assert me["balance_kobo"] == 3_990_000 and me["pending_kobo"] == 1_000_000
    assert me["kyc"]["status"] == "verified"
    listed = api.get("/v1/earnings/withdrawals").json()
    assert [w["status"] for w in listed["items"]] == ["pending"] and listed["has_more"] is False
    assert api.get("/v1/earnings/withdrawals?status=success").json()["items"] == []

    # History: one row per withdrawal, its ₦100 fee folded in; no fee rows.
    history = api.get("/v1/earnings/entries").json()["items"]
    assert [(h["kind"], h["amount_kobo"]) for h in history] == [
        ("withdrawal", -1_010_000), ("payment", 5_000_000)]
    assert history[0]["status"] == "pending" and history[1]["status"] is None


def test_history_folds_fees_filters_and_pages(api, maker, fake):
    pid, _, _ = asyncio.run(_setup(maker))

    async def orders():
        for i in range(3):
            cid = await _checkout(maker, pid, reference=f"MT-000{i}")
            async with maker() as db:
                await events.on_transfer(db, {"id": f"tr_{i}", "virtual_account_id": f"va_{i + 1}",
                                              "amount": 1_500_000, "net_amount": 1_500_000})
        await _checkout(maker, pid, reference="MT-waiting")
    asyncio.run(orders())

    page = api.get("/v1/earnings/entries?limit=2").json()
    assert page["has_more"] is True and len(page["items"]) == 2
    rest = api.get("/v1/earnings/entries?limit=2&offset=2").json()
    assert rest["has_more"] is False and len(rest["items"]) == 1
    rows = page["items"] + rest["items"]
    # Each order is one row of what the owner got (₦15,000 less the 1.5% fee).
    assert {r["kind"] for r in rows} == {"payment"}
    assert all(r["amount_kobo"] == 1_500_000 - 22_500 for r in rows)
    assert {r["title"] for r in rows} == {"MT-0000", "MT-0001", "MT-0002"}
    assert rows[0]["app"] == "Mama's Kitchen" and rows[0]["customer"] == "Tunde"
    assert api.get("/v1/earnings/entries?kind=withdrawals").json()["items"] == []
    assert api.get("/v1/earnings/entries?since=2999-01-01").json()["items"] == []
    assert api.get("/v1/earnings/entries?since=nope").status_code == 422

    orders_ = api.get("/v1/earnings/checkouts").json()["items"]
    assert len(orders_) == 4
    assert [o["reference"] for o in api.get("/v1/earnings/checkouts?status=pending").json()["items"]] == ["MT-waiting"]
    assert len(api.get("/v1/earnings/checkouts?status=paid").json()["items"]) == 3
    assert [o["reference"] for o in api.get("/v1/earnings/checkouts?q=0001").json()["items"]] == ["MT-0001"]
    assert len(api.get("/v1/earnings/checkouts?q=tunde").json()["items"]) == 4
    assert api.get("/v1/earnings/checkouts?mode=test").json()["items"] == []

    # Every app with Vivid Pay is a filter choice, paid or not yet.
    async def quiet_app():
        async with maker() as db:
            p = BuilderProject(owner_id="u1", name="Quiet Shop", mode="build")
            db.add(p)
            await db.flush()
            db.add(VividPayProject(project_id=p.id, owner_id="u1", publishable_key="vpk_q",
                                   secret_key_enc=vault.encrypt("vsk_q"), secret_key_hash=key_hash("vsk_q")))
            await db.commit()
    asyncio.run(quiet_app())
    apps = api.get("/v1/earnings").json()["apps"]
    assert [(a["name"], a["net_kobo"]) for a in apps] == [("Mama's Kitchen", 3 * (1_500_000 - 22_500)),
                                                         ("Quiet Shop", 0)]
    assert [a["orders"] for a in apps] == [3, 0] and apps[1]["last_paid_at"] is None


def test_app_webhook_signature():
    body = b'{"event":"checkout.paid"}'
    assert checkouts.sign("vsk_x", body) == hmac.new(b"vsk_x", body, hashlib.sha256).hexdigest()


def test_enabling_vivid_pay_on_a_project(maker, fake, monkeypatch):
    """Keys made once (secret shown once), the earnings account opened, and
    the app's .env carries the publishable key and the API."""
    from app.api.routes import builder as builder_routes
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.vivid.test")

    async def project():
        async with maker() as db:
            p = BuilderProject(owner_id="u1", name="Shop", mode="build")
            db.add(p)
            await db.commit()
            return p.id
    pid = asyncio.run(project())

    async def check():
        async with maker() as db:
            p = await db.get(BuilderProject, pid)
            user = await db.get(User, "u1")
            await payouts.ensure_earnings_account(db, user)
            await db.commit()
            account = await db.get(VividPayAccount, "u1")
            assert account.earnings_va_id and account.earnings_bank_name == "Paga"
            db.add(VividPayProject(project_id=pid, owner_id="u1", publishable_key="vpk_x",
                                   secret_key_enc=vault.encrypt("vsk_x"), secret_key_hash=key_hash("vsk_x")))
            p.payments_provider = "vividpay"
            await db.commit()
            env = await builder_routes._env_for(p, db)
            assert env["VITE_VIVIDPAY_KEY"] == "vpk_x"
            assert env["VITE_VIVIDPAY_API"] == "https://api.vivid.test/v1/pay"
    asyncio.run(check())
    assert fake.calls[0][1] == "vpo_" + "u1"


async def test_a_waiting_checkout_finds_its_payment_without_the_webhook(maker, fake, monkeypatch):
    """Pouch's webhook has arrived over a minute after the money; while the
    customer waits, the transfer list is read directly."""
    pid, _, _ = await _setup(maker)
    await _checkout(maker, pid)
    listed = [{"id": "tr_fast", "virtual_account_id": "va_1", "amount": 1_500_000},
              {"id": "tr_other", "virtual_account_id": "va_someone_else", "amount": 5}]

    async def inbound(skip=0, take=100):
        return listed
    monkeypatch.setattr(pouch, "inbound_transfers", inbound)
    async with maker() as db:
        assert await events.poll_pending(db) == 1
        assert await events.poll_pending(db) == 0                 # already paid, nothing waiting
        c = (await db.execute(VividPayCheckout.__table__.select())).first()
        assert c.status == "paid"


def test_polling_the_status_pays_a_waiting_checkout(api, maker, fake, monkeypatch):
    asyncio.run(_setup(maker))
    cid = _create(api, PUBLISHED).json()["id"]

    async def inbound(skip=0, take=100):
        return [{"id": "tr_seen", "virtual_account_id": "va_1", "amount": 1_500_000}]
    monkeypatch.setattr(pouch, "inbound_transfers", inbound)
    assert api.get(f"/v1/pay/checkouts/{cid}?key=vpk_test").json()["status"] == "paid"


# ------------------------------------------------------------------ mobile
def test_mobile_apps_use_the_test_key_until_built(maker, fake, monkeypatch):
    """The sandbox and Expo Go get the test key; an installable build gets
    the live one, and native requests (no Origin) with it are live."""
    from app.api.routes import builder as builder_routes
    from app.api.routes.pay import key_mode
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.vivid.test")

    async def check():
        async with maker() as db:
            p = BuilderProject(owner_id="u1", name="Shop", mode="build", target="mobile",
                               payments_provider="vividpay")
            db.add(p)
            await db.flush()
            pay = VividPayProject(project_id=p.id, owner_id="u1", publishable_key="vpk_live",
                                  secret_key_enc=vault.encrypt("vsk_x"), secret_key_hash=key_hash("vsk_x"))
            db.add(pay)
            await db.commit()
            env = await builder_routes._env_for(p, db)
            assert env["EXPO_PUBLIC_VIVIDPAY_KEY"].startswith("vpk_test")
            assert env["EXPO_PUBLIC_VIVIDPAY_KEY"] == pay.test_key
            assert env["EXPO_PUBLIC_VIVIDPAY_API"] == "https://api.vivid.test/v1/pay"
            built = await builder_routes._env_for(p, db, for_build=True)
            assert built["EXPO_PUBLIC_VIVIDPAY_KEY"] == "vpk_live"

            assert key_mode(pay.test_key, pay, None, p) == "test"
            assert key_mode("vpk_live", pay, None, p) == "live"
            assert key_mode("vpk_live", pay, "https://evil.example", p) is None
            web = BuilderProject(owner_id="u1", name="Web", mode="build")
            assert key_mode("vpk_live", pay, None, web) is None
    asyncio.run(check())


def test_a_build_carries_the_apps_public_env():
    from app.builder.app_build import with_build_env
    out = json.loads(with_build_env(
        json.dumps({"build": {"preview": {"distribution": "internal", "env": {"A": "1"}}}}),
        "preview", {"EXPO_PUBLIC_VIVIDPAY_KEY": "vpk_live", "SECRET": "no"}))
    assert out["build"]["preview"]["env"] == {"A": "1", "EXPO_PUBLIC_VIVIDPAY_KEY": "vpk_live"}
    assert out["build"]["preview"]["distribution"] == "internal"


def test_the_mobile_skill_is_the_native_checkout():
    from app.builder import skills
    text = skills.payments_block("vividpay", mobile=True)
    assert "EXPO_PUBLIC_VIVIDPAY_KEY" in text and "expo-clipboard" in text
    assert skills.payments_block("paystack", mobile=True) == ""


# ------------------------------------------------------------------ crypto
PAYER = {"name": "Tunde Bakare", "email": "t@x.ng", "phone": "+2348030000000",
         "address": "12 Allen Avenue, Ikeja"}


def _fill(event, fill_id="of_1", tid="tr_c1", va="va_1", naira_kobo=1_500_000, usdc=11.02):
    return {"event": f"optimistic_fill.{event}",
            "data": {"id": fill_id, "virtual_account_id": va, "transaction_id": tid,
                     "crypto_amount": usdc, "crypto_currency": "USDC",
                     "local_amount_estimated": naira_kobo, "local_amount_final": naira_kobo}}


async def test_crypto_opens_one_address_on_the_orders_account(maker, fake, monkeypatch):
    from app.services.vividpay import crypto
    monkeypatch.setattr(settings, "DEXTOPUS_SETTLEMENT_ADDRESS", "0xtreasury")
    pid, _, _ = await _setup(maker)
    cid = await _checkout(maker, pid)
    async with maker() as db:
        c = await db.get(VividPayCheckout, cid)
        with pytest.raises(VividPayError):                       # off until Pouch enables it
            await crypto.open_address(db, c, "evm", PAYER)
        monkeypatch.setattr(settings, "VIVIDPAY_CRYPTO_ENABLED", True)
        with pytest.raises(VividPayError):                       # Pouch needs the payer's details
            await crypto.open_address(db, c, "evm", {"name": "Tunde"})
        await crypto.open_address(db, c, "evm", PAYER)
        await crypto.open_address(db, c, "evm", PAYER)
        await db.commit()
        assert c.crypto_address == "0xdepva_1"
        view = checkouts.view(c)["crypto"]
        # ₦15,000 at ₦1,360 per USDC is 11.03 USDC, plus 1.5%, rounded up.
        assert view["due_usdc"] == "11.20" and view["estimate"] is True
    assert [x for x in fake.calls if x[0] == "static_address"] == [
        ("static_address", "va_1", 8453, "0xtreasury", "Tunde Bakare")]


async def test_a_crypto_payment_is_credited_from_the_transfer_pouch_lists(maker, fake, monkeypatch):
    """The fill webhook only points at the transfer; the transfer the API
    lists is what pays, once, whichever event comes first."""
    pid, _, _ = await _setup(maker)
    cid = await _checkout(maker, pid)
    async with maker() as db:
        assert await deposits.on_pouch_event(db, _fill("crypto_received")) is None
        assert await deposits.on_pouch_event(db, _fill("credited")) is None   # not listed yet
        fake.transfers["tr_c1"] = {"id": "tr_c1", "virtual_account_id": "va_1",
                                   "amount": 1_500_000, "net_amount": 1_500_000}
        out = await deposits.on_pouch_event(db, _fill("settled"))
        assert isinstance(out, VividPayCheckout) and out.status == "paid"
        assert await deposits.on_pouch_event(db, _fill("credited")) is None   # paid once
        assert (await earnings.account_for(db, "u1")).balance_kobo == 1_500_000 - 22_500
        c = await db.get(VividPayCheckout, cid)
        assert c.sweep_status == "done"
        # A forged fill naming a transfer the API does not list pays nothing.
        assert await deposits.on_pouch_event(db, _fill("credited", "of_x", "tr_forged")) is None
        assert await deposits.on_pouch_event(db, _fill("settlement_failed")) is None


def test_the_estimate_rate_follows_pouch_but_not_far():
    from app.services.vividpay import crypto
    crypto._last_rate = None
    assert crypto.rate() == settings.VIVIDPAY_CRYPTO_NGN_RATE
    crypto.note_rate({"crypto_amount": 10, "crypto_currency": "USDC", "local_amount_final": 1_400_000})
    assert crypto.rate() == 1400
    crypto.note_rate({"crypto_amount": 10, "crypto_currency": "USDC", "local_amount_final": 100_000})
    assert crypto.rate() == 1400                                    # implausible: ignored
    crypto._last_rate = None


def test_the_crypto_route_in_test_mode_never_calls_pouch(api, maker, fake, monkeypatch):
    monkeypatch.setattr(settings, "VIVIDPAY_CRYPTO_ENABLED", True)
    asyncio.run(_setup(maker))
    test = _create(api, "https://5173-abc123.e2b.app", reference="o-c")
    assert test.json()["crypto_enabled"] is True and test.json()["crypto"] is None
    cid = test.json()["id"]
    out = api.post(f"/v1/pay/checkouts/{cid}/crypto",
                   content=json.dumps({"key": "vpk_test", "network": "evm", "payer": PAYER}))
    assert out.status_code == 200 and out.json()["crypto"]["address"].startswith("0x0000")
    assert fake.calls == []
    assert api.options(f"/v1/pay/checkouts/{cid}/crypto").status_code == 204
    api.post(f"/v1/pay/checkouts/{cid}/simulate", content=json.dumps({"key": "vpk_test"}))
    again = api.post(f"/v1/pay/checkouts/{cid}/crypto",
                     content=json.dumps({"key": "vpk_test", "network": "evm", "payer": PAYER}))
    assert again.status_code == 409                                 # already paid
