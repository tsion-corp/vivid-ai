"""One account, several sign-in methods. Decane gives the emailed code and
Google different ids; a Google sign-in claiming an address someone proved is
held until a code to that address is entered, and a signed-in person can
connect the other method, folding its account into theirs."""
import asyncio

import pytest
from sqlalchemy import select

from app.db.models import BuilderProject, User, UserIdentity
from app.services.wallet import ledger
from tests.test_builder_routes import maker  # noqa: F401
from tests.test_decane_signin import api, fake  # noqa: F401


@pytest.fixture
def decane_ids(fake):  # noqa: F811
    """The emailed code signs in as `e-<address>`; Google as whatever token."""
    real = fake.call

    async def call(method, path, body=None, origin=None):
        if path == "/auth/email/verify":
            fake.calls.append((method, path, body))
            return {"jwt": f"tok-e-{body['email']}", "profile": {}}
        return await real(method, path, body, origin)
    fake.call = call
    import app.services.decane as decane_mod
    decane_mod._call = call
    return fake


def by_email(api, email):
    return api.post("/v1/auth/email/verify", json={"email": email, "code": "123456"}).json()


def google(api, token, email):
    return api.post("/v1/auth/decane", json={"access_token": token, "email": email, "name": "Itachi"})


def run(coro):
    return asyncio.run(coro)


def test_google_with_a_proven_address_links_after_a_code(api, maker, decane_ids):  # noqa: F811
    crumbs = by_email(api, "tem@gmail.com")
    held = google(api, "tok-g1", "Tem@gmail.com")
    assert held.status_code == 409
    err = held.json()["error"]
    assert err["code"] == "link_required" and err["details"]["email"].startswith("te") and err["details"]["code_sent"]
    token = err["details"]["link_token"]

    joined = api.post("/v1/auth/link/confirm", json={"link_token": token, "code": "123456"})
    assert joined.status_code == 200, joined.json()
    assert joined.json()["user"]["id"] == crumbs["user"]["id"]
    # From now on Google goes straight in, to the same account.
    assert google(api, "tok-g1", "tem@gmail.com").json()["user"]["id"] == crumbs["user"]["id"]
    assert api.post("/v1/auth/link/confirm", json={"link_token": token, "code": "123456"}).status_code == 410

    # A Google sign-in claiming nobody's proven address is simply a new account;
    # and choosing to stay separate makes one too.
    assert google(api, "tok-g2", "someone@else.com").status_code == 200
    by_email(api, "b@x.co")
    held = google(api, "tok-g3", "b@x.co").json()["error"]["details"]["link_token"]
    alone = api.post("/v1/auth/link/separate", json={"link_token": held}).json()
    assert alone["user"]["id"] != crumbs["user"]["id"]


def test_connecting_the_other_method_merges_its_account(api, maker, decane_ids):  # noqa: F811
    # The tester's case: two accounts already, one per method.
    itachi = google(api, "tok-g9", "tem@gmail.com").json()                 # nobody proved it yet
    crumbs = by_email(api, "tem@gmail.com")
    assert itachi["user"]["id"] != crumbs["user"]["id"]

    async def seed():
        async with maker() as db:
            db.add(BuilderProject(owner_id=itachi["user"]["id"], name="Invoicing tool", mode="build"))
            await ledger.credit(db, itachi["user"]["id"], 5_000_000, ledger.DEPOSIT_BANK, "t", "f1")
            await db.commit()
    run(seed())

    auth = {"authorization": f"Bearer {crumbs['access_token']}"}
    assert [m["method"] for m in api.get("/v1/auth/me/identities", headers=auth).json()["methods"]] == ["email"]
    out = api.post("/v1/auth/me/identities/google", json={"access_token": "tok-g9"}, headers=auth)
    assert out.status_code == 200, out.json()
    assert out.json()["merged"]["projects"] == 1 and out.json()["merged"]["wallet_micro"] == 5_000_000
    assert sorted(m["method"] for m in out.json()["methods"]) == ["email", "google"]

    async def check():
        async with maker() as db:
            project = (await db.execute(select(BuilderProject).where(BuilderProject.name == "Invoicing tool"))).scalar_one()
            closed = await db.get(User, itachi["user"]["id"])
            return project.owner_id, closed.deleted_at, await ledger.balance(db, crumbs["user"]["id"])
    owner, deleted_at, balance = run(check())
    assert owner == crumbs["user"]["id"] and deleted_at is not None and balance == 5_000_000
    # Google now opens the merged account.
    assert google(api, "tok-g9", "tem@gmail.com").json()["user"]["id"] == crumbs["user"]["id"]


def test_a_paid_plan_or_vivid_pay_blocks_a_merge(api, maker, decane_ids):  # noqa: F811
    from app.services.plans import subscriptions
    other = google(api, "tok-g5", "x@y.co").json()
    me = by_email(api, "me@y.co")

    async def pro():
        async with maker() as db:
            await ledger.credit(db, other["user"]["id"], 100_000_000, ledger.DEPOSIT_BANK, "t", "f2")
            await subscriptions.subscribe(db, other["user"]["id"], "pro")
            await db.commit()
    run(pro())
    out = api.post("/v1/auth/me/identities/google", json={"access_token": "tok-g5"},
                   headers={"authorization": f"Bearer {me['access_token']}"})
    assert out.status_code == 409 and out.json()["error"]["code"] == "merge_blocked"
    assert out.json()["error"]["details"]["blockers"][0]["code"] == "paid_plan"


def test_older_accounts_are_found_by_their_synthetic_address(api, maker, decane_ids):  # noqa: F811
    async def old():
        async with maker() as db:
            db.add(User(id="old1", email="decane_g-old@users.vivid", password_hash="!oauth"))
            await db.commit()
    run(old())
    assert google(api, "tok-g-old", None).json()["user"]["id"] == "old1"

    async def rows():
        async with maker() as db:
            return (await db.get(UserIdentity, "g-old")).user_id
    assert run(rows()) == "old1"
