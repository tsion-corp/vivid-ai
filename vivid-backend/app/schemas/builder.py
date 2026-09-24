from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled app", max_length=120)
    #: Start in build mode with no spec (a developer who knows what they want).
    skip_plan: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    spec_md: str | None = None
    fullstack: bool | None = None
    recipe: str | None = Field(default=None, max_length=32)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    mode: str
    brief_md: str | None = None
    spec_md: str | None
    current_snapshot_id: str | None
    backend_mode: str
    supabase_project_ref: str | None
    payments_provider: str = "none"
    maps_provider: str = "none"
    chain: str = "none"
    deployer_address: str | None = None
    fullstack: bool = False
    recipe: str | None = None
    published_url: str | None
    published_at: datetime | None = None
    #: "running" while a turn is in flight in the backend, else "idle".
    turn_status: str = "idle"
    turn_started_at: datetime | None = None
    #: The latest desktop screenshot from the critique, a time-limited URL.
    thumbnail_url: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    parts: list
    model: str | None
    created_at: datetime


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    #: Reference screenshots for plan mode: https or data URLs, at most four.
    images: list[str] = Field(default_factory=list, max_length=4)


class PreviewOut(BaseModel):
    url: str
    sandbox_id: str
    driver: str


class FileOut(BaseModel):
    path: str
    #: Text files: the content. Binary files: "" with `binary` true and the
    #: bytes in `content_base64`.
    content: str
    binary: bool = False
    content_base64: str | None = None
    content_type: str | None = None


class FilesOut(BaseModel):
    files: list[str]


class CancelOut(BaseModel):
    cancelled: bool


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    commit_sha: str | None
    summary: str | None
    size_bytes: int
    created_at: datetime


class UsageOut(BaseModel):
    since: str | None
    model_calls: int
    tokens: int
    sandbox_seconds: float
    storage_bytes: int
    cost_usd: float
    by_kind: dict


class AnalyticsOut(BaseModel):
    days: int
    pageviews: int
    visitors: int
    by_day: list[dict]
    top_pages: list[dict]
    referrers: list[dict]
    devices: list[dict]
    countries: list[dict]


class SupabaseLinkIn(BaseModel):
    project_ref: str = Field(min_length=5, max_length=64, pattern=r"^[a-z0-9-]+$")
    #: Only for a link without a connector: the project's URL and its
    #: publishable (anon) key, both safe in a browser.
    url: str | None = Field(default=None, max_length=256)
    anon_key: str | None = Field(default=None, max_length=512)
    #: The Postgres connection string from the dashboard's Connect panel.
    #: With it the builder applies migrations itself, no account link needed.
    database_url: str | None = Field(default=None, max_length=512)


class PublishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    snapshot_id: str | None
    url: str | None
    #: pending | building | live | failed
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    mime: str
    size_bytes: int
    #: Where the app serves it: /uploads/<name>.
    path: str = ""
    #: A time-limited URL for showing it in a client.
    url: str = ""
    meta: dict | None = None
    created_at: datetime


class TextEditIn(BaseModel):
    #: The text as the page showed it, and what it should say.
    old: str = Field(min_length=1, max_length=5000)
    new: str = Field(min_length=1, max_length=5000)
    #: Change every place the text appears, when it appears in more than one.
    all: bool = False


class EditsIn(BaseModel):
    edits: list[TextEditIn] = Field(min_length=1, max_length=50)


class TextEditOut(BaseModel):
    old: str
    new: str
    #: applied | not_found | ambiguous
    status: str
    files: list[str] = []
    count: int = 0


class EditsOut(BaseModel):
    results: list[TextEditOut]
    #: The version the edits were saved as; null when none applied, or when
    #: storing it failed (the preview still has the change).
    snapshot: SnapshotOut | None = None


class ImageReplaceOut(BaseModel):
    #: The file that now holds the picture.
    path: str
    #: Source files repointed at it, when the picture got a new file.
    relinked: list[str] = []
    snapshot: SnapshotOut | None = None
