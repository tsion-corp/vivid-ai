"""Publish: `vite build` in the sandbox, the built site uploaded to
Cloudflare Pages by the backend, a live URL on the project.

Direct upload, the protocol Wrangler uses (workers-sdk, pages/upload.ts):
an upload token for the project, check which file hashes are missing,
upload those in batches, upsert the hashes, then create a deployment from
a manifest of path -> hash. A file's hash is blake3 of its base64 body
followed by its extension, first 32 hex chars. The Cloudflare API token
stays in this process; the sandbox only ever runs the build.

Every app is a branch alias on one Pages project, so the URL is
`<alias>.<project>.pages.dev` until a custom domain fronts the project.
A `_redirects` rule sends unknown paths to index.html for the SPA router.
"""
import asyncio
import base64
import io
import json
import logging
import mimetypes
import re
import tarfile
from dataclasses import dataclass

import httpx
from blake3 import blake3

from app.builder import visual
from app.builder.sandbox.base import Sandbox, SandboxError
from app.core.config import settings
from app.services.models_gateway import http

log = logging.getLogger("vivid.builder.publish")

#: Branch aliases: lowercase, digits, hyphens, 28 chars (Pages truncates).
_ALIAS_MAX = 28
_BATCH_FILES = 500
_BATCH_BYTES = 20 * 1024 * 1024
_SPA_REDIRECTS = "/*    /index.html   200\n"


class PublishError(Exception):
    """What went wrong, in words a user may see."""


#: The pageview reporter every published site carries. Plain-text body, so
#: the browser sends it without a preflight; sendBeacon so it never delays
#: navigation; SPA route changes are reported by wrapping pushState.
SNIPPET = """<script>(function(){var u="%s";if(!u||/localhost|e2b\\.app/.test(location.hostname))return;
var last="";function send(){var p=location.pathname;if(p===last)return;last=p;
var b=new Blob([JSON.stringify({p:p,r:document.referrer||""})],{type:"text/plain"});
if(navigator.sendBeacon){navigator.sendBeacon(u,b)}else{fetch(u,{method:"POST",body:b,keepalive:true}).catch(function(){})}}
var ps=history.pushState;history.pushState=function(){ps.apply(this,arguments);setTimeout(send,0)};
addEventListener("popstate",send);send()})();</script>"""


def analytics_url(project_id: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/v1/a/{project_id}"


def inject_analytics(index_html: bytes, project_id: str) -> bytes:
    """index.html with the reporter before </head>, once."""
    html = index_html.decode("utf-8", errors="replace")
    if "/v1/a/" in html:
        return index_html
    tag = SNIPPET % analytics_url(project_id)
    if "</head>" in html:
        html = html.replace("</head>", tag + "</head>", 1)
    else:
        html = tag + html
    return html.encode("utf-8")


@dataclass
class BuiltSite:
    files: dict[str, bytes]          # "index.html" -> bytes; no leading slash

    @property
    def size(self) -> int:
        return sum(len(v) for v in self.files.values())


def configured() -> bool:
    return bool(settings.CF_API_TOKEN and settings.CF_ACCOUNT_ID and settings.CF_PAGES_PROJECT)


def alias_for(name: str, project_id: str) -> str:
    """A stable, unique branch alias: the app's name plus a bit of its id."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:_ALIAS_MAX - 7] or "app"
    return f"{slug}-{project_id[:6]}"


def public_url(alias: str) -> str:
    host = settings.BUILDER_PUBLISH_HOST.format(alias=alias, project=settings.CF_PAGES_PROJECT)
    return f"https://{host}"


def file_hash(content: bytes, path: str) -> str:
    ext = path.rsplit(".", 1)[1] if "." in path.rsplit("/", 1)[-1] else ""
    return blake3(base64.b64encode(content) + ext.encode()).hexdigest()[:32]


# ---------------------------------------------------------------- build
async def build_site(sandbox: Sandbox, project_id: str | None = None) -> BuiltSite:
    """`vite build` in the sandbox, dist/ brought back as bytes."""
    result = await sandbox.run("rm -rf dist && npx vite build",
                               timeout=settings.BUILDER_BUILD_TIMEOUT)
    if not result.ok:
        tail = result.output[-1500:]
        raise PublishError("The build failed:\n" + tail)
    tar = f"/tmp/vivid-dist-{sandbox.id}.tgz"
    result = await sandbox.run(f"tar -czf {tar} -C dist . && rm -rf dist", timeout=60)
    if not result.ok:
        raise PublishError("Could not package the build: " + result.output[-300:])
    data = await sandbox.read_bytes(tar)
    await sandbox.run(f"rm -f {tar}", timeout=15)
    files = _untar(data)
    if "index.html" not in files:
        raise PublishError("The build produced no index.html.")
    # The preview's click-to-edit script is for the builder, never the live app.
    files["index.html"] = visual.strip_editor(files["index.html"])
    if project_id:
        files["index.html"] = inject_analytics(files["index.html"], project_id)
    site = BuiltSite(files)
    if site.size > settings.BUILDER_PUBLISH_MAX_BYTES:
        raise PublishError(f"The built site is {site.size // 1_000_000} MB, over the limit.")
    return site


def _untar(data: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            name = member.name[2:] if member.name.startswith("./") else member.name
            if not name or name.startswith("/") or ".." in name.split("/"):
                continue
            files[name] = tf.extractfile(member).read()
    return files


# --------------------------------------------------------------- upload
class Pages:
    def __init__(self) -> None:
        if not configured():
            raise PublishError("Publishing is not configured on this deployment.")
        self._base = settings.CF_API_BASE.rstrip("/")
        self._project = settings.CF_PAGES_PROJECT
        self._account = f"{self._base}/accounts/{settings.CF_ACCOUNT_ID}"

    def _headers(self, token: str | None = None) -> dict:
        return {"Authorization": f"Bearer {token or settings.CF_API_TOKEN}"}

    async def _call(self, method: str, url: str, *, token: str | None = None, **kw):
        last: Exception | None = None
        for attempt in (1, 2, 3):
            try:
                r = await http.client().request(method, url, headers=self._headers(token),
                                                timeout=120, **kw)
                break
            except httpx.HTTPError as e:
                # A dropped connection mid-upload is the common failure on a
                # poor link; the calls are idempotent, so try again.
                last = e
                log.warning("Cloudflare call failed (attempt %d): %s", attempt,
                            e.__class__.__name__)
                await asyncio.sleep(1.5 * attempt)
        else:
            raise PublishError(f"Cloudflare could not be reached ({last.__class__.__name__}).")
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400 or body.get("success") is False:
            errors = body.get("errors") or [{"message": r.text[:300]}]
            raise PublishError("Cloudflare: " + "; ".join(str(e.get("message", e)) for e in errors))
        return body.get("result")

    async def ensure_project(self) -> None:
        r = await http.client().get(f"{self._account}/pages/projects/{self._project}",
                                    headers=self._headers(), timeout=60)
        if r.status_code == 200:
            return
        await self._call("POST", f"{self._account}/pages/projects",
                         json={"name": self._project, "production_branch": "main"})
        log.info("created Pages project %s", self._project)

    async def deploy(self, site: BuiltSite, alias: str, message: str) -> dict:
        await self.ensure_project()
        files = {path: (data, file_hash(data, path)) for path, data in site.files.items()}
        jwt = (await self._call("GET", f"{self._account}/pages/projects/{self._project}/upload-token"))["jwt"]
        hashes = [h for _, h in files.values()]
        missing = set(await self._call("POST", f"{self._base}/pages/assets/check-missing",
                                       token=jwt, json={"hashes": hashes}) or [])
        batch, batch_bytes = [], 0
        for path, (data, h) in files.items():
            if h not in missing:
                continue
            entry = {"key": h, "value": base64.b64encode(data).decode(),
                     "metadata": {"contentType": _content_type(path)}, "base64": True}
            if batch and (len(batch) >= _BATCH_FILES or batch_bytes + len(data) > _BATCH_BYTES):
                await self._call("POST", f"{self._base}/pages/assets/upload", token=jwt, json=batch)
                batch, batch_bytes = [], 0
            batch.append(entry)
            batch_bytes += len(data)
        if batch:
            await self._call("POST", f"{self._base}/pages/assets/upload", token=jwt, json=batch)
        await self._call("POST", f"{self._base}/pages/assets/upsert-hashes", token=jwt,
                         json={"hashes": hashes})

        manifest = {f"/{path}": h for path, (_, h) in files.items()}
        form = {"manifest": json.dumps(manifest), "branch": alias,
                "commit_message": message[:384], "commit_dirty": "false"}
        parts = [("_redirects", ("_redirects", _SPA_REDIRECTS.encode(), "text/plain"))]
        if "_headers" in site.files:
            parts.append(("_headers", ("_headers", site.files["_headers"], "text/plain")))
        return await self._call("POST", f"{self._account}/pages/projects/{self._project}/deployments",
                                data=form, files=parts)


def _content_type(path: str) -> str:
    guess, _ = mimetypes.guess_type(path)
    return guess or "application/octet-stream"


async def wait_until_live(url: str, timeout: float = 90) -> bool:
    """A new alias takes a few seconds to answer. Best effort."""
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await c.get(url)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(3)
    return False
