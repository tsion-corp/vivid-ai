"""Pictures of the page the builder just made, for the model to look at.

The sandbox template carries Chromium and scripts/screenshot.mjs; running it
against the dev server yields a desktop and a phone JPEG. They go to the
blob store (so a client can show them, and the eval can keep them) and to
the model as data URLs. Nothing here is a tool the model calls; the loop
decides when to look.
"""
import base64
import json
import logging
from dataclasses import dataclass

from app.builder import blob
from app.builder.sandbox.base import Sandbox, SandboxError
from app.core.config import settings

log = logging.getLogger("vivid.builder.screenshots")



@dataclass
class Shot:
    name: str
    width: int
    data: bytes
    key: str | None = None

    @property
    def data_url(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.data).decode()

    @property
    def url(self) -> str | None:
        return blob.presigned_url(self.key, expires_in=7 * 24 * 3600) if self.key else None


@dataclass
class PageReport:
    """What the browser saw besides pixels: whether the app rendered at
    each width, the Vite error overlay if one was up, console and page
    errors. A blank page with errors is a crash, and the critique says so."""
    rendered: dict = None
    overlay: str | None = None
    errors: list = None

    @property
    def broken(self) -> bool:
        return bool(self.overlay) or not all((self.rendered or {}).values()) \
            or any("Uncaught" in e or "pageerror" in e or not e.startswith("[") for e in (self.errors or []))

    def summary(self) -> str:
        lines = []
        if self.overlay:
            lines.append(f"Vite error overlay: {self.overlay}")
        for name, ok in (self.rendered or {}).items():
            if not ok:
                lines.append(f"The app rendered NOTHING at {name} width (blank page).")
        for e in (self.errors or [])[:8]:
            lines.append(f"Browser error: {e}")
        return "\n".join(lines)


#: Filled by capture() for the caller that wants it; a plain list return
#: keeps every existing caller working.
last_report: PageReport | None = None


async def capture(sandbox: Sandbox, project_id: str, label: str,
                  store: bool = True) -> list[Shot]:
    """Both shots, or an empty list when the sandbox cannot take them (no
    Chromium on this template, the page not answering). Never raises: a
    missing critique is not a failed turn. Sets `last_report`."""
    global last_report
    last_report = None
    out_dir = f"/tmp/vivid-shots-{sandbox.id}"
    result = await sandbox.run(
        f"rm -rf {out_dir} && node scripts/screenshot.mjs http://localhost:{sandbox.target.port} {out_dir}",
        timeout=(settings.BUILDER_MOBILE_SCREENSHOT_TIMEOUT if sandbox.target.is_mobile
                 else settings.BUILDER_SCREENSHOT_TIMEOUT))
    if not result.ok:
        log.warning("screenshot failed for %s: %s", project_id, result.output[-300:])
        return []
    shots: list[Shot] = []
    for name, width in sandbox.target.shots:
        try:
            data = await sandbox.read_bytes(f"{out_dir}/{name}.jpg")
        except (FileNotFoundError, SandboxError) as e:
            log.warning("screenshot %s missing for %s: %s", name, project_id, e)
            continue
        shot = Shot(name=name, width=width, data=data)
        if store:
            key = f"{settings.R2_PREFIX}projects/{project_id}/shots/{label}-{name}.jpg"
            try:
                await blob.put(key, data, "image/jpeg")
                shot.key = key
            except blob.BlobError as e:
                log.warning("screenshot not stored: %s", e)
        shots.append(shot)
    try:
        raw = await sandbox.read_bytes(f"{out_dir}/report.json")
        data = json.loads(raw.decode())
        last_report = PageReport(rendered=data.get("rendered") or {}, overlay=data.get("overlay"),
                                 errors=data.get("errors") or [])
    except (FileNotFoundError, SandboxError, ValueError):
        last_report = None
    await sandbox.run(f"rm -rf {out_dir}", timeout=15)
    return shots


CRITIQUE_BRIEF = """Here is your page as a user sees it: first at 1280px (desktop), then at \
390px (a phone). Look at both carefully.

List the problems you can see, most important first, at most five: text or elements \
overflowing or clipped on the phone, wrong hierarchy (what should read first does not), \
uneven spacing, misaligned edges, images without a fixed aspect ratio or stretched, low \
contrast, an empty-looking or unbalanced section, a hero without a visible action on the \
phone, anything that still says placeholder. Then fix them with edit_file. If the page is \
genuinely good on both screens, say so in one line and do not change anything.

Reply to the user afterwards in one or two sentences about what you adjusted."""


MOBILE_CRITIQUE_BRIEF = """Here is your app as a user sees it, on an iPhone-sized screen (390pt) \
and an Android-sized one (412dp), rendered through the web preview. Look at both carefully.

List the problems you can see, most important first, at most five: content under the status \
bar or the home indicator, text clipped or overflowing, tap targets smaller than 44pt, a tab \
bar without clear icons and labels, wrong hierarchy (what should read first does not), uneven \
spacing, images without a fixed aspect ratio, low contrast, an empty-looking screen with no \
empty state, a flat generic look (every card the same flat box, no clear hero element, no \
depth between content and the floating tab bar or header), anything that still says \
placeholder. Then fix them with edit_file. If the app \
is genuinely good on both screens, say so in one line and do not change anything.

Reply to the user afterwards in one or two sentences about what you adjusted."""


BROKEN_BRIEF = """Before any design critique: the page is BROKEN. Fix the runtime error first: read \
the errors below, use get_dev_server_logs and read_file, correct the code, and make sure the \
app renders on both screens. Then continue with the design review.\n\n"""


def critique_message(shots: list[Shot], report: PageReport | None = None,
                     mobile: bool = False) -> dict:
    """The user-role message that shows the model its own page. A broken
    page leads with the errors, so the model fixes the crash before the
    spacing."""
    brief = MOBILE_CRITIQUE_BRIEF if mobile else CRITIQUE_BRIEF
    if report is not None and report.broken:
        brief = BROKEN_BRIEF + report.summary() + "\n\n" + brief
    parts: list[dict] = [{"type": "text", "text": brief}]
    for shot in shots:
        parts.append({"type": "text", "text": f"[{shot.name}, {shot.width}px wide]"})
        parts.append({"type": "image_url", "image_url": {"url": shot.data_url}})
    return {"role": "user", "content": parts}
