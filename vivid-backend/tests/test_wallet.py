"""The wallet: the ledger never double-credits and never goes negative,
deposits come from the providers' APIs (webhooks are only hints) and are
credited once whichever path finds them first, FX conversion keeps its
spread, and the routes hand out one bank account and one address per option."""
import asyncio
import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import Principal, get_db, get_principal
from app.api.routes import webhooks as webhook_routes
from app.api.routes.wallet import router as wallet_router
from app.api.routes.webhooks import router as webhooks_router
from app.core import errors
from app.core.config import settings
from app.db.models import User, WalletEntry, WalletFunding
from app.services.wallet import crypto_options, deposits, dextopus, fx, ledger, pouch
from tests.conftest import FakeRedis
from tests.test_builder_routes import maker  # noqa: F401

RATES = {"USD": 1.0, "NGN": 1500.0, "GHS": 15.0, "EUR": 0.9}


@pytest.fixture(autouse=True)
def fixed_rates(monkeypatch):
    fx.set_rates(RATES)
    monkeypatch.setattr(fx, "TTL", 10 ** 9)


# ------------------------------------------------------------------ ledger
async def test_credit_is_once_per_provider_ref(maker):
    async with maker() as db:
        first = await ledger.credit(db, "u1", 5_000_000, ledger.DEPOSIT_BANK, "pouch", "t1")
        again = await ledger.credit(db, "u1", 5_000_000, ledger.DEPOSIT_BANK, "pouch", "t1")
        await db.commit()
        assert first is not None and again is None
        assert await ledger.balance(db, "u1") == 5_000_000
        assert first.balance_after == 5_000_000


async def test_debit_never_goes_negative(maker):
    async with maker() as db:
        await ledger.credit(db, "u1", 3_000_000, ledger.DEPOSIT_CRYPTO, "dextopus", "d1")
        await ledger.debit(db, "u1", 2_000_000, ledger.CHARGE, "vivid", "build:1")
        with pytest.raises(ledger.InsufficientFunds) as e:
            await ledger.debit(db, "u1", 2_000_000, ledger.CHARGE, "vivid", "build:2")
        assert e.value.balance_micro == 1_000_000
        # The same charge twice is one charge.
        assert await ledger.debit(db, "u1", 2_000_000, ledger.CHARGE, "vivid", "build:1") is None
        await db.commit()
        assert await ledger.balance(db, "u1") == 1_000_000
        kinds = [e.kind for e in await ledger.entries(db, "u1")]
        assert sorted(kinds) == ["charge", "deposit_crypto"]


# ---------------------------------------------------------------------- fx
async def test_bank_deposits_convert_at_the_rate_less_the_spread(monkeypatch):
    monkeypatch.setattr(settings, "WALLET_FX_SPREAD_BPS", 150)
    micro, rate = await fx.minor_to_usd_micro(150_000_00, "NGN")    # ₦150,000
    assert rate == 1500.0 and micro == int(100 * 0.985 * 1_000_000)
    shown = await fx.display(10_000_000, "NGN")
    assert shown["amount"] == 15000.0 and shown["currency"] == "NGN"


# ---------------------------------------------------------------- deposits
async def _funding(maker, **fields):
    async with maker() as db:
        db.add(WalletFunding(user_id="u1", **fields))
        await db.commit()


async def test_a_pouch_transfer_credits_its_owner_once(maker, monkeypatch):
    monkeypatch.setattr(settings, "WALLET_FX_SPREAD_BPS", 0)
    await _funding(maker, provider="pouch", option="bank", external_id="va_1", address="2904364169")
    transfer = {"id": "tr_9", "virtual_account_id": "va_1", "amount": 150_000_00,
                "fee": 10000, "net_amount": 150_000_00 - 10000, "currency": "NGN",
                "payer_name": "Ada Obi"}
    async with maker() as db:
        entry = await deposits.credit_pouch_transfer(db, transfer)
        assert entry is not None and entry.kind == "deposit_bank"
        assert entry.original_currency == "NGN" and entry.original_amount == str(150_000_00 - 10000)
        # ₦149,900 at ₦1,500/$ = $99.9333
        assert entry.amount_micro == int((150_000_00 - 10000) / 100 / 1500 * 1_000_000)
        assert await deposits.credit_pouch_transfer(db, transfer) is None
        # Someone else's account is not ours to credit.
        assert await deposits.credit_pouch_transfer(db, {**transfer, "id": "tr_x",
                                                         "virtual_account_id": "va_other"}) is None


async def test_a_dextopus_deposit_credits_its_settled_usdc(maker):
    await _funding(maker, provider="dextopus", option="usdt-tron", external_id="addr_1",
                   address="TXYZ", chain_id=crypto_options.TRON)
    dep = {"requestId": "0xabc", "status": "COMPLETED", "staticAddressId": "addr_1",
           "depositAddress": "TXYZ", "userId": "u1", "originAmountFormatted": "25.0",
           "settlementAmount": "24750000"}
    async with maker() as db:
        entry = await deposits.credit_dextopus_deposit(db, dep)
        assert entry.amount_micro == 24_750_000 and entry.original_currency == "USDT"
        assert await deposits.credit_dextopus_deposit(db, dep) is None
        # Still settling: nothing yet.
        assert await deposits.credit_dextopus_deposit(db, {**dep, "requestId": "0xdef",
                                                           "settlementAmount": "0"}) is None
        assert await deposits.credit_dextopus_deposit(db, {**dep, "requestId": "0x1",
                                                           "status": "PENDING"}) is None
        # An address of u1's that claims another user is skipped.
        assert await deposits.credit_dextopus_deposit(db, {**dep, "requestId": "0x2",
                                                           "userId": "u2"}) is None


async def test_the_reconciler_finds_what_webhooks_missed(maker, monkeypatch):
    monkeypatch.setattr(settings, "POUCH_API_KEY", "sk_test")
    monkeypatch.setattr(settings, "DEXTOPUS_API_KEY", "pk_test")
    monkeypatch.setattr(settings, "DEXTOPUS_SETTLEMENT_ADDRESS", "0xtreasury")
    await _funding(maker, provider="pouch", option="bank", external_id="va_1", address="1")
    await _funding(maker, provider="dextopus", option="usdc-base", external_id="addr_b", address="0xdep")

    async def transfers(skip=0, take=100):
        return [{"id": "tr_1", "virtual_account_id": "va_1", "net_amount": 15000_00,
                 "currency": "NGN"}] if skip == 0 else []

    async def deps(**_):
        return [{"requestId": "0xr", "status": "COMPLETED", "staticAddressId": "addr_b",
                 "settlementAmount": "5000000"}]
    monkeypatch.setattr(pouch, "inbound_transfers", transfers)
    monkeypatch.setattr(dextopus, "deposits", deps)
    async with maker() as db:
        assert await deposits.reconcile(db) == 2
        assert await deposits.reconcile(db) == 0
        await db.commit()
        assert len(await ledger.entries(db, "u1")) == 2


# ---------------------------------------------------------------- webhooks
def test_dextopus_signature():
    body = json.dumps({"event": "deposit.completed", "data": {"requestId": "0x1"}}).encode()
    ts = str(int(time.time() * 1000))
    sig = hmac.new(b"whsec", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert dextopus.verify_signature(body, ts, sig, "whsec")
    assert not dextopus.verify_signature(body, ts, sig, "other")
    assert not dextopus.verify_signature(body + b" ", ts, "0" * 64, "whsec")
    old = str(int(time.time() * 1000) - 10 * 60 * 1000)
    old_sig = hmac.new(b"whsec", f"{old}.".encode() + body, hashlib.sha256).hexdigest()
    assert not dextopus.verify_signature(body, old, old_sig, "whsec")


def test_pouch_signature_accepts_sha256_and_sha512():
    body = b'{"event":"virtual_account.credited"}'
    for algo in (hashlib.sha256, hashlib.sha512):
        sig = hmac.new(b"s3cret", body, algo).hexdigest()
        assert deposits.verify_pouch_signature(body, sig, "s3cret")
        assert deposits.verify_pouch_signature(body, "sha256=" + sig, "s3cret")
    assert not deposits.verify_pouch_signature(body, "nope", "s3cret")


@pytest.fixture
def app_client(maker, monkeypatch):
    monkeypatch.setattr(webhook_routes, "async_session", maker)
    app = FastAPI()
    errors.install(app)
    app.include_router(wallet_router, prefix="/v1")
    app.include_router(webhooks_router, prefix="/v1")
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


def test_a_webhook_credits_only_what_the_api_confirms(app_client, maker, monkeypatch):
    monkeypatch.setattr(settings, "POUCH_API_KEY", "sk_test")
    asyncio.run(_funding(maker, provider="pouch", option="bank", external_id="va_1", address="1"))
    real = {"id": "tr_7", "virtual_account_id": "va_1", "net_amount": 30000_00, "currency": "NGN"}

    async def find(transfer_id, pages=5):
        return real if transfer_id == "tr_7" else None
    monkeypatch.setattr(pouch, "find_transfer", find)
    # The webhook claims a huge amount; the API's figure is what counts.
    hook = {"event": "virtual_account.credited",
            "data": {"id": "tr_7", "virtual_account_id": "va_1", "amount": 999_999_999_00}}
    assert app_client.post("/v1/webhooks/pouch", json=hook).json()["credited"] is True
    assert app_client.post("/v1/webhooks/pouch", json=hook).json()["credited"] is False
    fake = {"event": "virtual_account.credited", "data": {"id": "tr_forged"}}
    assert app_client.post("/v1/webhooks/pouch", json=fake).json()["credited"] is False
    wallet = app_client.get("/v1/wallet?currency=NGN").json()
    expected = int(30000 / 1500 * (1 - settings.WALLET_FX_SPREAD_BPS / 10_000) * 1_000_000)
    assert wallet["balance_micro"] == expected
    assert wallet["display"]["currency"] == "NGN"


def test_a_dextopus_webhook_needs_its_signature(app_client, monkeypatch):
    monkeypatch.setattr(settings, "DEXTOPUS_WEBHOOK_SECRET", "whsec")
    r = app_client.post("/v1/webhooks/dextopus", json={"event": "deposit.completed"})
    assert r.status_code == 401


# ------------------------------------------------------------------ routes
def test_one_bank_account_per_user(app_client, monkeypatch):
    monkeypatch.setattr(settings, "POUCH_API_KEY", "sk_test")
    made = []

    async def ensure_customer(user_id, name, email, phone=None, bvn=None):
        return "cus_1"

    async def create_va(user_id, customer_id):
        made.append(user_id)
        return {"id": "va_1", "account_number": "2904364169", "account_name": "Ada Obi",
                "bank_name": "Paga"}
    monkeypatch.setattr(pouch, "ensure_customer", ensure_customer)
    monkeypatch.setattr(pouch, "create_virtual_account", create_va)
    first = app_client.post("/v1/wallet/bank-account").json()
    second = app_client.post("/v1/wallet/bank-account").json()
    assert first["account_number"] == second["account_number"] == "2904364169"
    assert made == ["u1"]


def test_crypto_addresses_are_made_once_per_option(app_client, monkeypatch):
    monkeypatch.setattr(settings, "DEXTOPUS_API_KEY", "pk_test")
    monkeypatch.setattr(settings, "DEXTOPUS_SETTLEMENT_ADDRESS", "0xtreasury")
    calls = []

    async def static_address(user_id, option):
        calls.append(option.key)
        return {"id": f"addr_{option.key}", "depositAddress": f"dep-{option.key}"}
    monkeypatch.setattr(dextopus, "static_address", static_address)
    a = app_client.post("/v1/wallet/crypto/address", json={"option": "usdt-tron"}).json()
    b = app_client.post("/v1/wallet/crypto/address", json={"option": "usdt-tron"}).json()
    assert a["address"] == b["address"] == "dep-usdt-tron" and calls == ["usdt-tron"]
    opts = app_client.get("/v1/wallet/crypto/options").json()
    assert {o["key"]: o["address"] for o in opts["options"]}["usdt-tron"] == "dep-usdt-tron"
    bad = app_client.post("/v1/wallet/crypto/address", json={"option": "doge-moon"})
    assert bad.status_code == 400


def test_unconfigured_providers_say_so(app_client):
    assert app_client.post("/v1/wallet/bank-account").json()["error"]["code"] == "not_configured"
    r = app_client.post("/v1/wallet/crypto/address", json={"option": "usdc-base"})
    assert r.json()["error"]["code"] == "not_configured"
    assert app_client.get("/v1/wallet/entries").json() == []


async def test_deposits_before_the_entry_table_is_unique(maker):
    """The unique (provider, provider_ref) index is what makes it safe."""
    cols = {tuple(c.columns.keys()) for c in WalletEntry.__table__.constraints
            if hasattr(c, "columns") and len(c.columns) == 2}
    assert ("provider", "provider_ref") in cols
