import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api.routes import api_router
from app.builder import app_build
from app.builder.sandbox.manager import manager as sandbox_manager
from app.core import errors
from app.core.config import settings
from app.db.session import init_db
from app.services import storage
from app.services.models_gateway import http as gateway_http
from app.ws.code import router as code_ws_router
from app.ws.handler import router as ws_router

log = logging.getLogger("vivid")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        app.state.arq = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    except Exception as e:
        log.warning("arq pool unavailable, background jobs disabled: %s", e)
        app.state.arq = None
    try:
        await storage.ensure_bucket()
    except Exception as e:
        log.warning("object storage unavailable: %s", e)
    # The builder's sandboxes cost money while they run; the sweeper kills
    # the ones nobody has touched for a while.
    sweeper = asyncio.create_task(sandbox_manager.sweeper(app.state.redis))
    # Mobile app builds run for minutes on Expo's side; this follows them.
    app_builds = asyncio.create_task(app_build.poller(app.state.redis))
    yield
    sweeper.cancel()
    app_builds.cancel()
    if settings.BUILDER_KILL_SANDBOXES_ON_SHUTDOWN:
        await sandbox_manager.kill_all(app.state.redis)
    await gateway_http.aclose()
    if app.state.arq is not None:
        await app.state.arq.aclose()
    await app.state.redis.aclose()


#: Shown above the endpoint list in Swagger UI at /docs. This page is the
#: whole documentation set for a partner: they arrive with a key and no
#: context, so the two things that are not guessable from the route list —
#: how to authenticate, and that a key is its own tenant — are said here.
API_DESCRIPTION = """
The Vivid API. Everything the Vivid apps do — chat, voice, files, search,
browsing, model access — over the same endpoints they use.

### Authenticating

Generate a key in the Vivid web app under **Settings → Developer**, then send
it as a bearer token:

```
Authorization: Bearer vivid_xxxxxxxxxxxxxxxxxxxx
```

Press **Authorize** above to try requests from this page.

The secret is shown once, when the key is generated, and is stored only as a
hash. If it is lost, revoke that key and generate another.

### What a key can reach

Every `/v1` endpoint below, except key management itself: creating, listing
and revoking keys needs a signed-in session, so a leaked key cannot mint a
replacement for itself.

A key is its own tenant. The chats, attachments and browser sessions it
creates belong to the key, not to the account that generated it, and they are
not visible in that person's Vivid app. Revoking a key leaves other keys
untouched.
"""

#: Order and prose for the groups in Swagger UI. Without this the tags appear
#: in whatever order the routers were included, unlabelled.
API_TAGS = [
    {"name": "api keys",
     "description": "Generate and revoke the credentials for everything below. "
                    "Session-only: an API key cannot call these."},
    {"name": "generation",
     "description": "Make an image, a video clip or speech from a prompt, and "
                    "turn speech back into text. Video renders in the "
                    "background: POST returns a job id to poll."},
    {"name": "tools",
     "description": "The assistant's own tools, callable directly: web search, "
                    "code execution, browsing, weather, exchange rates."},
    {"name": "chats", "description": "Conversations and their messages."},
    {"name": "builder",
     "description": "The app builder: projects, the streaming chat that "
                    "writes the app, the live preview and its files."},
    {"name": "models",
     "description": "OpenAI-compatible chat completions, for tools that "
                    "already speak that shape."},
    {"name": "attachments", "description": "Upload files and fetch them back."},
    {"name": "artifacts", "description": "Files, images and video Vivid generated."},
    {"name": "search", "description": "Search across this account's messages."},
    {"name": "browser",
     "description": "Drive a real browser: open a session, navigate, read the "
                    "page, act on it."},
    {"name": "connectors", "description": "Third-party accounts linked to this one."},
    {"name": "auth", "description": "Sign-in for the Vivid apps."},
    {"name": "health", "description": "Liveness and model-service reachability."},
]

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION,
              description=API_DESCRIPTION, openapi_tags=API_TAGS,
              lifespan=lifespan)

# One error shape for every route, plus a request id on every response.
errors.install(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[errors.REQUEST_ID_HEADER],
)

# The integration guide for people building a client on the builder, served
# where the llms.txt convention puts it: the origin root.
_LLMS_TXT = Path(__file__).resolve().parent.parent / "llms.txt"


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    if not _LLMS_TXT.is_file():
        return PlainTextResponse("llms.txt is not shipped in this build.", status_code=404)
    return PlainTextResponse(_LLMS_TXT.read_text(encoding="utf-8"))


# REST is versioned from day one (spec section 6) so partner APIs can be added
# under the same scheme.
app.include_router(api_router, prefix="/v1")
app.include_router(ws_router)
# The coding agent's own socket (/ws/code): native tool calling, tools run in
# the editor. Separate from /ws, which is the chat assistant.
app.include_router(code_ws_router)
