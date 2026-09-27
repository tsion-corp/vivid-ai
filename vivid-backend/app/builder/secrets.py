"""Per-project secrets at rest: Supabase tokens, service keys, anything the
orchestrator holds for a project. Fernet (AES-128-CBC with HMAC) under
SECRETS_ENCRYPTION_KEY. A value goes into the database encrypted and comes
out only through `get`; nothing here ever logs one.
"""
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import BuilderSecret


class SecretsUnavailable(Exception):
    """SECRETS_ENCRYPTION_KEY is missing or not a Fernet key."""


def _fernet() -> Fernet:
    key = settings.SECRETS_ENCRYPTION_KEY
    if not key:
        raise SecretsUnavailable("SECRETS_ENCRYPTION_KEY is not set")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise SecretsUnavailable("SECRETS_ENCRYPTION_KEY is not a valid Fernet key") from e


def configured() -> bool:
    try:
        _fernet()
        return True
    except SecretsUnavailable:
        return False


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretsUnavailable("a stored secret does not decrypt with this key") from e


async def set_secret(db: AsyncSession, project_id: str, key: str, value: str) -> None:
    row = await db.get(BuilderSecret, (project_id, key))
    if row is None:
        db.add(BuilderSecret(project_id=project_id, key=key, encrypted_value=encrypt(value)))
    else:
        row.encrypted_value = encrypt(value)
    await db.flush()


async def get_secret(db: AsyncSession, project_id: str, key: str) -> str | None:
    row = await db.get(BuilderSecret, (project_id, key))
    return decrypt(row.encrypted_value) if row else None


async def list_keys(db: AsyncSession, project_id: str) -> list[str]:
    rows = await db.execute(select(BuilderSecret.key)
                            .where(BuilderSecret.project_id == project_id)
                            .order_by(BuilderSecret.key))
    return list(rows.scalars())


async def delete_secret(db: AsyncSession, project_id: str, key: str) -> None:
    await db.execute(delete(BuilderSecret).where(BuilderSecret.project_id == project_id,
                                                 BuilderSecret.key == key))


# ------------------------------------------------------------ user secrets
#: Keys the person added in the project's settings, beside the platform's
#: own (SUPABASE_*, DECANE_*...). Server secrets go to the backend's edge
#: functions; public ones into the app's .env as VITE_<NAME>.
USER_SERVER, USER_PUBLIC = "user:", "user-public:"


@dataclass
class UserSecret:
    name: str
    public: bool
    value: str
    updated_at: object


async def user_secrets(db: AsyncSession, project_id: str) -> list[UserSecret]:
    rows = await db.execute(select(BuilderSecret).where(BuilderSecret.project_id == project_id)
                            .order_by(BuilderSecret.key))
    out = []
    for row in rows.scalars():
        for prefix, public in ((USER_PUBLIC, True), (USER_SERVER, False)):
            if row.key.startswith(prefix):
                out.append(UserSecret(row.key[len(prefix):], public, decrypt(row.encrypted_value),
                                      row.updated_at))
                break
    return out
