"""The waitlist: joining is public and idempotent per email, reading is
behind ADMIN_TOKEN. Runs against SQLite, as the API key tests do, because
the unique email is part of what is under test."""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.api.deps import get_db
from app.api.routes.waitlist import router
from app.core import errors
from app.core.config import settings
from app.db.models import Base

from tests.conftest import FakeRedis


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(Vector, "sqlite")
def _vector_on_sqlite(type_, compiler, **kw):
    return "BLOB"


ADMIN = "test-admin-token"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def client(db_session, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "ADMIN_TOKEN", ADMIN)
    app = FastAPI()
    errors.install(app)
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    app.state.redis = None
    return TestClient(app, raise_server_exceptions=False)


def _form(**overrides) -> dict:
    return {"first_name": "Ada", "last_name": "Obi", "email": "ada@example.com",
            "phone_no": "+234 803 123 4567",
            "use_case": "A booking site for my salon", "heard_from": "Twitter",
            **overrides}


def _admin() -> dict:
    return {"Authorization": f"Bearer {ADMIN}"}


def test_join_stores_the_entry(client):
    res = client.post("/v1/waitlist", json=_form())
    assert res.status_code == 201
    assert res.json() == {"ok": True, "already_joined": False}

    page = client.get("/v1/waitlist", headers=_admin()).json()
    assert page["total"] == 1
    entry = page["entries"][0]
    assert (entry["first_name"], entry["last_name"], entry["email"]) == ("Ada", "Obi", "ada@example.com")
    assert entry["phone_no"] == "+2348031234567"
    assert entry["use_case"] == "A booking site for my salon"
    assert entry["heard_from"] == "Twitter"


def test_joining_twice_updates_rather_than_duplicates(client):
    client.post("/v1/waitlist", json=_form())
    res = client.post("/v1/waitlist", json=_form(email="ADA@Example.com", heard_from="A friend"))
    assert res.status_code == 200
    assert res.json()["already_joined"] is True

    page = client.get("/v1/waitlist", headers=_admin()).json()
    assert page["total"] == 1
    assert page["entries"][0]["heard_from"] == "A friend"


@pytest.mark.parametrize("bad", [
    {"email": "not-an-email"},
    {"first_name": "   "},
    {"use_case": ""},
    {"heard_from": "x" * 161},
    {"phone_no": "call me"},
    {"phone_no": "12345"},
    {"phone_no": "+1234567890123456"},
])
def test_join_rejects_bad_input(client, bad):
    assert client.post("/v1/waitlist", json=_form(**bad)).status_code == 422


def test_join_missing_field(client):
    body = _form()
    del body["heard_from"]
    assert client.post("/v1/waitlist", json=body).status_code == 422


def test_join_requires_a_phone_number(client):
    body = _form()
    del body["phone_no"]
    assert client.post("/v1/waitlist", json=body).status_code == 422


def test_phone_formats_are_normalised(client):
    client.post("/v1/waitlist", json=_form(phone_no="(0803) 123-4567"))
    entry = client.get("/v1/waitlist", headers=_admin()).json()["entries"][0]
    assert entry["phone_no"] == "08031234567"


def test_two_people_may_share_a_number(client):
    assert client.post("/v1/waitlist", json=_form(email="a@example.com")).status_code == 201
    assert client.post("/v1/waitlist", json=_form(email="b@example.com")).status_code == 201
    assert client.get("/v1/waitlist", headers=_admin()).json()["total"] == 2


def test_join_is_rate_limited_per_address(client, monkeypatch):
    class CountingRedis(FakeRedis):
        async def incr(self, key):
            n = int(self.strings.get(key, 0)) + 1
            self.strings[key] = n
            return n

        async def expire(self, key, seconds):
            return True

    client.app.state.redis = CountingRedis()
    monkeypatch.setattr(settings, "WAITLIST_PER_MINUTE", 2)
    codes = [client.post("/v1/waitlist", json=_form(email=f"u{i}@example.com")).status_code
             for i in range(3)]
    assert codes == [201, 201, 429]


def test_reading_needs_the_admin_token(client):
    assert client.get("/v1/waitlist").status_code == 401
    assert client.get("/v1/waitlist", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/waitlist/stats").status_code == 401


def test_reading_is_off_without_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "")
    res = client.get("/v1/waitlist", headers={"Authorization": "Bearer "})
    assert res.status_code == 503


def test_search_filter_and_paging(client):
    client.post("/v1/waitlist", json=_form(email="a@example.com", heard_from="Twitter"))
    client.post("/v1/waitlist", json=_form(email="b@example.com", first_name="Bola",
                                           heard_from="LinkedIn"))
    client.post("/v1/waitlist", json=_form(email="c@example.com", heard_from="twitter"))

    assert client.get("/v1/waitlist?q=bola", headers=_admin()).json()["total"] == 1
    assert client.get("/v1/waitlist?q=8031234", headers=_admin()).json()["total"] == 3
    assert client.get("/v1/waitlist?heard_from=Twitter", headers=_admin()).json()["total"] == 2

    page = client.get("/v1/waitlist?limit=2", headers=_admin()).json()
    assert page["total"] == 3 and len(page["entries"]) == 2


def test_csv_export(client):
    client.post("/v1/waitlist", json=_form())
    res = client.get("/v1/waitlist?format=csv", headers=_admin())
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    lines = res.text.strip().splitlines()
    assert lines[0] == "created_at,first_name,last_name,email,phone_no,use_case,heard_from"
    assert "ada@example.com" in lines[1] and "+2348031234567" in lines[1]


def test_stats_counts_by_source(client):
    client.post("/v1/waitlist", json=_form(email="a@example.com", heard_from="Twitter"))
    client.post("/v1/waitlist", json=_form(email="b@example.com", heard_from="Twitter"))
    client.post("/v1/waitlist", json=_form(email="c@example.com", heard_from="A friend"))
    body = client.get("/v1/waitlist/stats", headers=_admin()).json()
    assert body["total"] == 3
    assert body["heard_from"][0] == {"key": "Twitter", "count": 2}
