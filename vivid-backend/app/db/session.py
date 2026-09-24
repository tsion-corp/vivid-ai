from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base, Client

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    from app.services.prompt import DEFAULT_PROMPTS

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_messages_fts ON messages "
            "USING gin (to_tsvector('english', content))"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_message_embeddings_hnsw ON message_embeddings "
            "USING hnsw (embedding vector_cosine_ops)"))
        # create_all never alters existing tables; columns added after the
        # first deploy are applied idempotently here until real migrations.
        for column in ("name VARCHAR(120)", "avatar_url VARCHAR(1024)",
                       "profile_email VARCHAR(320)"):
            await conn.execute(text(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column}"))
        await conn.execute(text(
            "ALTER TABLE chats ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE"))
        # Self-serve keys record who generated them. Existing partner keys
        # keep a null owner: they were minted from the CLI by nobody.
        await conn.execute(text(
            "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS "
            "owner_user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_api_keys_owner_user_id "
            "ON api_keys (owner_user_id)"))
        # Builder projects made before plan mode existed skip it.
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "mode VARCHAR(8) NOT NULL DEFAULT 'build'"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "target VARCHAR(8) NOT NULL DEFAULT 'web'"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS app_id VARCHAR(160)"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS eas_projects JSONB"))
        # Build prices are micro-USD now (debited from the wallet).
        await conn.execute(text(
            "ALTER TABLE builder_app_builds ALTER COLUMN price TYPE BIGINT"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "payments_provider VARCHAR(16) NOT NULL DEFAULT 'none'"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS brief_md TEXT"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "fullstack BOOLEAN NOT NULL DEFAULT FALSE"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS recipe VARCHAR(32)"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "maps_provider VARCHAR(16) NOT NULL DEFAULT 'none'"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS thumbnail_key VARCHAR(512)"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "chain VARCHAR(16) NOT NULL DEFAULT 'none'"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS deployer_address VARCHAR(64)"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS "
            "auth_provider VARCHAR(16) NOT NULL DEFAULT 'none'"))
        await conn.execute(text(
            "ALTER TABLE builder_projects ADD COLUMN IF NOT EXISTS decane_app_id VARCHAR(36)"))
        # Projects published before the column existed: date them from their
        # latest live publish, so clients keying "is live" on it keep them.
        await conn.execute(text(
            "UPDATE builder_projects p SET published_at = ("
            " SELECT max(b.updated_at) FROM builder_publishes b"
            " WHERE b.project_id = p.id AND b.status = 'live')"
            " WHERE p.published_at IS NULL AND EXISTS ("
            " SELECT 1 FROM builder_publishes b"
            " WHERE b.project_id = p.id AND b.status = 'live')"))
        await conn.execute(text(
            "ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS phone_no VARCHAR(16)"))
        # The $1 plan was "team" (per seat, pooled); it is "max" now, for one
        # person. Existing subscribers keep it under the new name.
        await conn.execute(text(
            "UPDATE subscriptions SET plan = 'max', seats = 1 WHERE plan = 'team'"))

    async with async_session() as db:
        # Prompts are product config and deploy with the backend: upsert so a
        # prompt change in code reaches the DB-backed client row on restart.
        stmt = pg_insert(Client).values(
            id=settings.DEFAULT_CLIENT_ID, name="Vivid Web",
            config_json={"prompts": DEFAULT_PROMPTS})
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"config_json": stmt.excluded.config_json}))
        await db.commit()
