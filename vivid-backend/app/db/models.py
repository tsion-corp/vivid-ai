import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # Display profile. For social sign-ins the account `email` is a synthetic
    # key (the provider's token carries no email); the provider's pass-through
    # name / email / picture live here as display-only data — never used for
    # lookup, since the client reports them.
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    profile_email: Mapped[str | None] = mapped_column(String(320), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Client(Base):
    """One row per API consumer. v1 has a single row: vivid_web. The column on
    every table is the hook for B2B partners later — do not build that flow yet."""
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    system_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    default_voice: Mapped[str | None] = mapped_column(String(64), default=None)
    config_json: Mapped[dict | None] = mapped_column(JSONB, default=None)


class ApiKey(Base):
    """A partner credential. Belongs to a client (which supplies the system
    prompt and tool allowlist) and to a service-account user (which owns the
    chats, attachments and browser sessions the key creates).

    Keying data to a real user row rather than making user_id nullable
    everywhere means every existing ownership check keeps working untouched —
    the alternative was a nullable FK on five tables and an `or` in every
    query.

    Two people are recorded, and they are deliberately not the same one.
    `user_id` is the service account the key acts as, so a partner's chats and
    files never appear in anyone's own sidebar. `owner_user_id` is the human
    who generated it in Settings and is the only one who may list or revoke
    it. Keys minted by the CLI before self-serve existed have no owner, which
    is why the column is nullable: nobody signed in to create them.

    Only the hash is stored. Keys are 32 bytes of urandom, so SHA-256 is the
    right primitive: bcrypt exists to slow down guessing low-entropy
    passwords, and paying its cost on every single API request would be a
    self-inflicted rate limit.
    """
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), default=settings.DEFAULT_CLIENT_ID)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: The human who generated this key. Null for CLI-minted partner keys.
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None)
    name: Mapped[str] = mapped_column(String(128))
    # The visible half, for "which key is this?" without revealing the secret.
    prefix: Mapped[str] = mapped_column(String(24), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Concurrent browser sessions this key may hold. Enforced before the
    # browser pool is asked, so one partner cannot starve the tier.
    max_sessions: Mapped[int] = mapped_column(
        Integer, default=settings.BROWSER_SESSIONS_PER_KEY)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)


class MediaJob(Base):
    """One video render a partner started through the API.

    Video takes minutes, so `POST /videos` returns immediately and the caller
    polls. All this row holds is the mapping from the id we handed out to the
    upstream job id, plus where it got to: the render itself lives upstream,
    so a backend restart loses nothing and there is no worker to run.

    Rows are kept after completion because `GET /videos/{id}` has to keep
    answering, and because "what did this account generate" is a billing
    question.
    """
    __tablename__ = "media_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="video")
    #: pending | completed | failed. Mirrors what the upstream last said.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    #: The upstream's own job id, which is what gets polled.
    upstream_id: Mapped[str] = mapped_column(String(128), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    #: Set once the clip has been fetched and stored, so a second poll after
    #: completion returns the same file instead of downloading it again.
    attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL"), default=None)
    #: Why it failed, in the words a caller may see.
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id"), default=settings.DEFAULT_CLIENT_ID)
    title: Mapped[str | None] = mapped_column(String(200), default=None)
    language: Mapped[str] = mapped_column(String(8), default="en")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    tokens_in: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_out: Mapped[int | None] = mapped_column(Integer, default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    used_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_messages_chat_created", "chat_id", "created_at"),)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), default=None, index=True)
    chat_id: Mapped[str | None] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), default=None, index=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # image | video | file | audio
    filename: Mapped[str | None] = mapped_column(String(256), default=None)
    storage_key: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    extracted_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Connector(Base):
    """A per-user integration (GitHub, ...) whose credentials turn into
    per-user tools in the agent loop. One row per (user, provider).
    TODO: encrypt token at rest before real users arrive."""
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    token: Mapped[str] = mapped_column(String(512), default="")
    config_json: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_connectors_user_provider", "user_id",
                            "provider", unique=True),)


class ModelUsage(Base):
    """One row per completed /v1/chat/completions call through the proxy.

    This table is the whole point of making developer tools go through the
    backend: a pod hit directly serves traffic nobody can attribute, bill or
    cut off. Written after the reply finishes — including after a stream
    closes — so `completion_tokens` is the real figure rather than an estimate.

    Both credential kinds are recorded. `user_id` is always the human (a
    partner key resolves to its service account); `api_key_id` is set only when
    a key was used, which is what separates "Timi in the editor" from "Timi's
    CI job" in the same user's totals.
    """
    __tablename__ = "model_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    api_key_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), default=None, index=True)
    client_id: Mapped[str] = mapped_column(String(64), default=settings.DEFAULT_CLIENT_ID)
    #: The public alias asked for (`vivid-code`), not the vendor model id — the
    #: vendor string changes when a pod is re-provisioned and would break
    #: any usage history keyed on it.
    model: Mapped[str] = mapped_column(String(64), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class MessageEmbedding(Base):
    __tablename__ = "message_embeddings"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ----------------------------------------------------------------- builder
# The app builder (app/builder). Its own tables, prefixed builder_, so the
# assistant's chats and messages are untouched: the two products have
# different rows and different lifecycles. All of them exist from phase 1
# even where only projects and messages are used yet; usage rows in
# particular are cheap to write now and painful to retrofit.

class BuilderProject(Base):
    __tablename__ = "builder_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    #: plan | build. New projects plan first; `POST .../build` moves them on.
    #: Rows from before plan mode existed default to build (see init_db).
    mode: Mapped[str] = mapped_column(String(8), default="plan")
    #: The brief the prompt builder wrote from the first message.
    brief_md: Mapped[str | None] = mapped_column(Text, default=None)
    #: spec.md as agreed in plan mode; injected into every turn.
    spec_md: Mapped[str | None] = mapped_column(Text, default=None)
    #: The snapshot the preview is on. Plain string, not an FK: the row is
    #: written before its first snapshot and a restore points it back.
    current_snapshot_id: Mapped[str | None] = mapped_column(String(36), default=None)
    #: none | byo | cloud
    backend_mode: Mapped[str] = mapped_column(String(8), default="none")
    supabase_project_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    #: none | paystack. The user's connector supplies the keys.
    payments_provider: Mapped[str] = mapped_column(String(16), default="none")
    #: "google" when the project uses the user's Google Maps key.
    maps_provider: Mapped[str] = mapped_column(String(16), default="none")
    #: Storage key of the latest desktop screenshot (the project card).
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), default=None)
    #: "ark-devnet" when the app is a dApp; the deployer key is a secret,
    #: its address is public.
    chain: Mapped[str] = mapped_column(String(16), default="none")
    deployer_address: Mapped[str | None] = mapped_column(String(64), default=None)
    # Accounts, roles and server-side data are built only when asked for:
    # set by the plan (write_spec) or the client, never assumed.
    fullstack: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The design recipe the plan chose (a file under skills/design).
    recipe: Mapped[str | None] = mapped_column(String(32), default=None)
    published_url: Mapped[str | None] = mapped_column(String(512), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Files touched in the last two turns, newest turn first, for the
    #: context block. A list of lists of project-relative paths.
    recent_files: Mapped[list | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)


class BuilderMessage(Base):
    """One message in a project's thread. `parts` is the AI SDK UI message
    parts list exactly as streamed (text, tool-*, step-start, data-*), so a
    client reloads a thread into the same shape it watched live."""
    __tablename__ = "builder_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("builder_projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    parts: Mapped[list] = mapped_column(JSONB, default=list)
    #: Vendor slug that produced an assistant message; analytics only.
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_builder_messages_project_created",
                            "project_id", "created_at"),)


class BuilderSnapshot(Base):
    """A project's files after one turn: a tarball in object storage. The
    snapshot is the truth; any sandbox can be rebuilt from it."""
    __tablename__ = "builder_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("builder_projects.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    r2_key: Mapped[str] = mapped_column(String(512))
    commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("project_id", "seq",
                                       name="uq_builder_snapshots_project_seq"),)


class BuilderSecret(Base):
    """A per-project secret (Supabase tokens, service keys), Fernet-encrypted
    at rest. Values never appear in a tool result or the stream."""
    __tablename__ = "builder_secrets"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("builder_projects.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)


class BuilderPageview(Base):
    """One visit to a published app, reported by the snippet the publish
    step puts in the page. No personal data: the visitor id is a daily
    salted hash, kept only to count unique visitors."""
    __tablename__ = "builder_pageviews"
    __table_args__ = (Index("ix_builder_pageviews_project_time", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("builder_projects.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    referrer: Mapped[str | None] = mapped_column(String(512), default=None)
    device: Mapped[str] = mapped_column(String(16), default="desktop")
    country: Mapped[str | None] = mapped_column(String(2), default=None)
    visitor: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BuilderPublish(Base):
    __tablename__ = "builder_publishes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("builder_projects.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), default=None)
    url: Mapped[str | None] = mapped_column(String(512), default=None)
    #: pending | building | live | failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)


class BuilderUsageEvent(Base):
    """One metered thing: a model call, a sandbox session, a stored
    snapshot, a Supabase project. Billing is built on these later."""
    __tablename__ = "builder_usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("builder_projects.id", ondelete="CASCADE"), index=True)
    #: model | sandbox | storage | supabase
    kind: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    #: tokens | seconds | bytes | projects
    unit: Mapped[str] = mapped_column(String(16))
    #: Null when the price was not known at write time; never a guess.
    cost_usd: Mapped[float | None] = mapped_column(Numeric(14, 8), default=None)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    #: Token breakdown, sandbox id, snapshot seq: whatever explains the row.
    meta: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class BuilderAsset(Base):
    """A file the user gave the builder (logo, product photos, a font). The
    bytes live in the blob store; a copy sits in the app at
    public/uploads/<name>, so the site serves it at /uploads/<name> and
    snapshots carry it."""
    __tablename__ = "builder_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("builder_projects.id", ondelete="CASCADE"), index=True)
    #: Safe file name, unique within the project.
    name: Mapped[str] = mapped_column(String(160))
    mime: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    r2_key: Mapped[str] = mapped_column(String(512))
    #: Width x height for images, when known.
    meta: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_builder_assets_name"),)


class WaitlistEntry(Base):
    """Someone who asked to be let in. One row per email, stored lowercased,
    so signing up twice updates the row rather than adding another."""
    __tablename__ = "waitlist_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    #: WhatsApp / phone number, digits with an optional leading "+". Not
    #: unique: the row is keyed by email, and a household may share a number.
    #: Null for entries made before the form asked for it.
    phone_no: Mapped[str | None] = mapped_column(String(16), nullable=True)
    use_case: Mapped[str] = mapped_column(Text)
    #: Where they heard about Vivid: free text, or whatever the form's
    #: dropdown sends ("twitter", "a friend", ...).
    heard_from: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)
