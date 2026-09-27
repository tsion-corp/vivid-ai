from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled app", max_length=120)
    #: Start in build mode with no spec (a developer who knows what they want).
    skip_plan: bool = False
    #: What to build: a website or an iOS and Android app. Fixed for life.
    target: Literal["web", "mobile"] = "web"


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
    target: str = "web"
    brief_md: str | None = None
    spec_md: str | None
    current_snapshot_id: str | None
    backend_mode: str
    supabase_project_ref: str | None
    payments_provider: str = "none"
    maps_provider: str = "none"
    chain: str = "none"
    deployer_address: str | None = None
    #: "decane" when the app has its own sign-in; decane_app_id is the SDK's appId.
    auth_provider: str = "none"
    decane_app_id: str | None = None
    fullstack: bool = False
    recipe: str | None = None
    published_url: str | None
    published_at: datetime | None = None
    #: True when the plan's app limit leaves this project without turns
    #: (it is not one of the user's most recently updated apps): a turn
    #: answers 402 plan_limit with details.read_only. Reading, preview and
    #: publish still work.
    read_only: bool = False
    #: "running" while a turn is in flight in the backend, else "idle".
    turn_status: str = "idle"
    turn_started_at: datetime | None = None
    #: The latest desktop screenshot from the critique, a time-limited URL.
    thumbnail_url: str | None = None
    #: The caller's role: owner | editor (builds, hand-edits, publishes) |
    #: viewer (reads). Shared projects list with the other two.
    role: str = "owner"
    #: On a project shared with the caller: the owner's name.
    owner_name: str | None = None
    created_at: datetime
    updated_at: datetime


class DuplicateIn(BaseModel):
    #: The version to copy; the current one when left out.
    seq: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=120)


class DuplicateOut(BaseModel):
    project: ProjectOut
    #: What the source was connected to that the copy is not, to reconnect:
    #: database | payments | sign-in | blockchain | maps key | published site.
    reset: list[str]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    #: Who wrote a user message (match it against GET .../members).
    user_id: str | None = None
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
    #: web | mobile, the project's target.
    target: str = "web"
    #: Mobile projects: the exps:// URL Expo Go opens (as a QR code). None on
    #: the web, and for a local sandbox a phone cannot reach.
    device_url: str | None = None


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
    #: publish | rollback (an earlier publish put back) | unpublish (the
    #: site was taken offline)
    kind: str = "publish"
    #: This publish's build is kept: POST .../publishes/{id}/rollback can
    #: put it back. False for publishes made before builds were kept.
    can_rollback: bool = False
    created_at: datetime
    updated_at: datetime


class AppBuildIn(BaseModel):
    platform: Literal["android", "ios"]
    #: preview: an Android APK to install directly, or an iOS simulator
    #: build. production: store builds (an Android AAB; iOS needs the user's
    #: own Expo account with Apple credentials set up there).
    profile: Literal["preview", "production"] = "preview"
    #: auto: the user's connected Expo account if there is one, else Vivid's.
    account: Literal["auto", "vivid", "user"] = "auto"


class AppBuildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    snapshot_id: str | None
    platform: str
    profile: str
    account: str
    #: starting | queued | building | canceling | finished | failed | canceled
    status: str
    #: The installable file once finished (an .apk to open on the phone,
    #: an .aab for the Play Store, or an iOS simulator archive).
    artifact_url: str | None = None
    #: The build's page on expo.dev: logs, and an install QR for internal builds.
    logs_url: str | None = None
    error: str | None = None
    #: What this build costs, in micro-USD (1 USD = 1,000,000); 0 on the
    #: user's own account. `charge` is refunded when a build fails.
    price: int = 0
    currency: str = "USD"
    charge: str = "none"
    created_at: datetime
    finished_at: datetime | None = None


class BuildAccountOut(BaseModel):
    id: Literal["vivid", "user"]
    available: bool
    #: vivid: the price per platform, in micro-USD; user: 0, the builds use
    #: their quota.
    price_android: int = 0
    price_ios: int = 0
    currency: str = "USD"
    #: vivid: builds left this month under the cap, None when uncapped.
    remaining: int | None = None
    #: vivid: the user's wallet balance, in micro-USD (prices are too).
    balance: int | None = None
    #: user: the Expo account builds go to.
    owner: str | None = None
    reason: str | None = None


class BuildOptionsOut(BaseModel):
    #: Which account `auto` picks.
    default: Literal["vivid", "user"]
    accounts: list[BuildAccountOut]
    #: iOS store builds need the user's own account (Apple credentials).
    ios_production_needs_user_account: bool = True


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


class DeleteIn(BaseModel):
    """An element clicked in the preview, named by what the page shows (the
    editor sends it with `vivid:delete`)."""
    #: The DOM tag, e.g. section, div, p, img.
    tag: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z][a-zA-Z0-9-]*$")
    id: str | None = Field(default=None, max_length=120)
    classes: list[str] = Field(default_factory=list, max_length=20)
    #: Up to a few distinctive pieces of its text, headings first.
    texts: list[str] = Field(default_factory=list, max_length=6)
    #: For a picture with no text: its src as written in the page.
    src: str | None = Field(default=None, max_length=1000)
    #: element | section: only changes the version label.
    scope: Literal["element", "section"] = "element"
    #: A short name for the version label, e.g. the section's heading.
    label: str | None = Field(default=None, max_length=120)


class StructureIn(DeleteIn):
    """The editor's `vivid:structure`: what to do with the clicked element."""
    op: Literal["duplicate", "move_up", "move_down", "remove"]


class DeleteOut(BaseModel):
    #: applied | not_found (its text comes from data, or it has none) |
    #: ambiguous (several elements match; count says how many) |
    #: not_simple (an item of a list loaded while running, or the whole page) |
    #: would_break (removing it would break the code; nothing changed) |
    #: not_supported (mobile apps) | error
    status: str
    reason: str | None = None
    files: list[str] = []
    count: int = 0
    #: Set when the element was one item of a list built from data in the
    #: code: that entry was removed from this file (e.g. src/lib/seed.ts).
    data_file: str | None = None
    #: Texts of the removed entry. A page that keeps its data in the
    #: browser's storage still shows it: post {type: "vivid:forget", texts}
    #: to the preview, which clears those saved entries and reloads.
    forget: list[str] = []
    #: The version the delete was saved as, when it applied.
    snapshot: SnapshotOut | None = None


class ImageReplaceOut(BaseModel):
    #: The file that now holds the picture.
    path: str
    #: Source files repointed at it, when the picture got a new file.
    relinked: list[str] = []
    snapshot: SnapshotOut | None = None


class ShareOut(BaseModel):
    token: str
    #: The page to send people: the live preview, no sign-in needed.
    url: str
    created_at: datetime


class SharedPreviewOut(BaseModel):
    """What the public share page shows."""
    name: str
    target: str = "web"
    #: The live preview to put in an iframe. It changes when the workspace
    #: restarts, so the page asks again rather than keeping it.
    url: str
    #: Mobile projects: the URL Expo Go opens (a QR code on the page).
    device_url: str | None = None


class PersonOut(BaseModel):
    user_id: str
    name: str | None = None
    avatar_url: str | None = None


class MemberOut(PersonOut):
    role: str                       # editor | viewer
    created_at: datetime


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime
    expires_at: datetime
    #: The invite link (owner only): send it yourself when email is not
    #: delivered, e.g. over WhatsApp. Whoever opens it signed in joins.
    url: str | None = None
    #: This time only: whether the invite email went out.
    emailed: bool | None = None


class MembersOut(BaseModel):
    owner: PersonOut
    members: list[MemberOut]
    #: Pending invites; shown to the owner only (empty for others).
    invites: list[InviteOut]


class MemberInviteIn(BaseModel):
    email: str = Field(max_length=320)
    role: Literal["editor", "viewer"] = "editor"


class MemberRoleIn(BaseModel):
    role: Literal["editor", "viewer"]


class InvitePreviewOut(BaseModel):
    """What an invite link shows before it is accepted."""
    project_name: str
    inviter: str | None = None
    role: str
    #: expired | used | ok
    status: str


class SeoIn(BaseModel):
    """How the published site presents itself. Empty fields keep what the
    page says; `image` and `favicon` are paths of uploads (/uploads/x.png)
    or full URLs."""
    title: str | None = Field(default=None, max_length=70)
    description: str | None = Field(default=None, max_length=200)
    image: str | None = Field(default=None, max_length=1024, pattern=r"^(/|https://)[^\s\"'<>]*$")
    favicon: str | None = Field(default=None, max_length=1024, pattern=r"^(/|https://)[^\s\"'<>]*$")
    #: Ask search engines not to list the site.
    noindex: bool = False


class SeoPage(BaseModel):
    """What the current version's index.html says, for the empty fields."""
    title: str | None = None
    description: str | None = None
    image: str | None = None


class SeoOut(SeoIn):
    page: SeoPage


class UserSecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=4000)
    #: True: goes into the app's .env as VITE_<name>, readable by anyone in
    #: the browser (publishable keys only). False: a server secret for the
    #: backend's edge functions.
    public: bool = False


class UserSecretOut(BaseModel):
    name: str
    public: bool
    #: The last four characters, to tell keys apart; never the value.
    hint: str | None = None
    updated_at: datetime


class UserSecretSaved(UserSecretOut):
    #: app (in .env) | backend (set on the linked Supabase project) |
    #: stored (kept; set on the backend when one is linked)
    where: str


class FormsIn(BaseModel):
    enabled: bool = True
    #: Where submissions are emailed; empty = the owner's own address.
    email: str | None = Field(default=None, max_length=320)


class FormsOut(BaseModel):
    enabled: bool
    email: str | None
    #: The owner's address, used when `email` is empty.
    default_email: str | None
    #: Whether this server sends email at all; submissions are kept either way.
    email_ready: bool


class FormSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    form: str
    fields: dict
    #: Sent from the builder's preview.
    test: bool
    emailed: bool
    created_at: datetime
