"""Visual edits: change the app by hand, without a chat turn.

Three things a person does to a finished app that do not need the model:
replace a picture, reword a line of copy, and do either by pointing at it in
the preview. All three land as files in the sandbox (Vite hot-reloads them)
and a snapshot, so they are versions like any turn's and undo works.

The preview side is a small script inside the app's index.html, between
EDITOR_START and EDITOR_END. It is kept there by `ensure_editor` whenever a
preview is handed out, does nothing unless the page is framed and the parent
turns edit mode on, and is stripped from the built site by `strip_editor` at
publish, so a live app never carries it.

A mobile (Expo) project previews through react-native-web as a single-page
app whose HTML is public/index.html, so the same script goes there; its copy
lives under app/, components/ and friends, and pictures come back from Metro
as /assets/?unstable_path=<file> URLs.
"""
import asyncio
import io
import json
import posixpath
import re
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from app.builder.sandbox.base import Sandbox

MAX_IMAGE_BYTES = 10 * 1024 * 1024
#: A replacement is resized to fit this on its long side when it is re-encoded.
MAX_IMAGE_SIDE = 2560
MAX_TEXT = 5000

#: Extensions an image can be re-encoded into, so the path (and every import
#: of it) stays the same whatever format was uploaded.
_ENCODE = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg", ".ico"}
_FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "AVIF": ".avif",
               "ICO": ".ico"}

#: Where copy lives. Text in node_modules or a lockfile is never the user's.
_SOURCE_EXT = (".tsx", ".jsx", ".ts", ".js", ".mdx", ".md", ".json", ".html")
_SKIP = ("package.json", "package-lock.json", "tsconfig", "components.json")
#: Where a mobile app's copy lives (Expo Router routes and their helpers).
_MOBILE_SOURCE_DIRS = ("app/", "components/", "constants/", "lib/", "data/")
_MOBILE_SKIP = ("app.json", "eas.json")


class VisualError(Exception):
    """Refused, with a sentence for the person."""


def is_image_path(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in _IMAGE_EXT


# ---------------------------------------------------------------- images
def _is_svg(data: bytes) -> bool:
    head = data[:1024].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:4096].lower())


def upload_ext(data: bytes) -> str:
    """The extension the uploaded bytes really are. Refuses anything that is
    not a picture, whatever it is called."""
    if len(data) > MAX_IMAGE_BYTES:
        raise VisualError("That image is over 10 MB. Try a smaller one.")
    if _is_svg(data):
        return ".svg"
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
    except (UnidentifiedImageError, OSError):
        raise VisualError("That file is not an image.")
    ext = _FORMAT_EXT.get(fmt or "")
    if ext is None:
        raise VisualError(f"{fmt} images are not supported. Use a JPEG, PNG, WebP or GIF.")
    return ext


def fit_to(data: bytes, target_path: str) -> bytes | None:
    """The upload as bytes for `target_path`, re-encoded into its format when
    that differs. None when it cannot be (a PNG for an .svg, say): the caller
    then gives the picture a new file instead."""
    have = upload_ext(data)
    want = posixpath.splitext(target_path)[1].lower()
    same = have == want or {have, want} == {".jpg", ".jpeg"}
    if same and len(data) <= MAX_IMAGE_BYTES:
        return data
    fmt = _ENCODE.get(want)
    if fmt is None or have == ".svg":
        return None
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        if fmt == "JPEG" and img.mode not in ("RGB", "L"):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        out = io.BytesIO()
        img.save(out, fmt, **({"quality": 88} if fmt in ("JPEG", "WEBP") else {"optimize": True}))
    return out.getvalue()


def new_image_path(filename: str, ext: str, mobile: bool = False) -> str:
    stem = posixpath.splitext(posixpath.basename(filename or ""))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:40] or "image"
    folder = "assets/images" if mobile else "public/images"
    return f"{folder}/{slug}-{secrets.token_hex(3)}{ext}"


@dataclass
class ImageTarget:
    #: The project file the picture is served from, when it is one of ours.
    path: str | None
    #: The strings the source uses to point at it, for a relink.
    refs: list[str] = field(default_factory=list)


def resolve_src(src: str, preview_url: str, files: list[str],
                mobile: bool = False) -> ImageTarget:
    """Which file a URL seen in the preview is.

    Vite serves src/ files at their own path (/src/assets/hero.jpg) and
    public/ files at the root (/hero.jpg), generated pictures and uploads
    included (/uploads/hero.jpg). Anything else, a stock photo on a CDN, is
    not a file, but the source names it, so it can be relinked.
    """
    src = (src or "").strip()
    if not src or src.startswith(("data:", "blob:")):
        raise VisualError("That picture is generated in the page, not a file. Ask Vivid to change it.")
    url = urlparse(src)
    preview = urlparse(preview_url)
    local = not url.netloc or url.netloc == preview.netloc
    if not local:
        return ImageTarget(path=None, refs=[src])
    if mobile:
        return _resolve_metro(url, src, set(files))
    route = unquote(url.path)
    if route.startswith("/@fs/") or ".." in route.split("/"):
        raise VisualError("That picture is not one of the app's files.")
    rel = route.lstrip("/")
    known = set(files)
    candidates = [rel, f"public/{rel}"]
    path = next((c for c in candidates if c in known), None)
    if path is None:
        return ImageTarget(path=None, refs=[route])
    refs = [route] if path.startswith("public/") else []
    return ImageTarget(path=path, refs=refs)


def _resolve_metro(url, src: str, known: set[str]) -> ImageTarget:
    """A picture in an Expo app's web preview. Metro serves required files
    as /assets/?unstable_path=./assets/uploads/x.png (or, bundled, at their
    own path under /assets/); either way the path names the project file,
    which is replaced in place, so a require() never has to change."""
    raw = (parse_qs(url.query).get("unstable_path") or [""])[0]
    rel = posixpath.normpath(unquote(raw or url.path).lstrip("./").lstrip("/")) if (raw or url.path) else ""
    if ".." in rel.split("/"):
        raise VisualError("That picture is not one of the app's files.")
    for candidate in (rel, rel.removeprefix("assets/")):
        if candidate in known:
            return ImageTarget(path=candidate)
        # Bundled URLs drop the project's own "assets/" once: /assets/uploads/x.png.
        if f"assets/{candidate}" in known:
            return ImageTarget(path=f"assets/{candidate}")
    return ImageTarget(path=None, refs=[src])


def relink_uri(sources: dict[str, str], src: str, new_path: str) -> list[str]:
    """In a mobile app a remote picture is `{ uri: "<src>" }`; its local
    replacement is required instead. Other uses of the URL (a string in a
    data file) are left alone: they cannot become a require()."""
    pattern = re.compile(r"\{\s*uri\s*:\s*([\"'`])" + re.escape(src) + r"\1\s*\}")
    changed = []
    for path, content in sources.items():
        updated = pattern.sub(f'require("@/{new_path}")', content)
        if updated != content:
            sources[path] = updated
            changed.append(path)
    return changed


# ------------------------------------------------------------------ text
def _is_source(path: str, mobile: bool) -> bool:
    if mobile:
        return (path.startswith(_MOBILE_SOURCE_DIRS) and path.endswith(_SOURCE_EXT)
                and path not in _MOBILE_SKIP)
    return (path.startswith("src/") and path.endswith(_SOURCE_EXT)) or path == "index.html"


async def read_sources(sandbox: Sandbox, files: list[str]) -> dict[str, str]:
    """Every file copy can live in, read concurrently."""
    mobile = sandbox.target.is_mobile
    wanted = [f for f in files if _is_source(f, mobile)]
    wanted = [f for f in wanted if not any(s in f for s in _SKIP)]
    gate = asyncio.Semaphore(16)

    async def one(path: str) -> tuple[str, str | None]:
        async with gate:
            try:
                return path, await sandbox.read_file(path)
            except (FileNotFoundError, UnicodeDecodeError):
                return path, None
    pairs = await asyncio.gather(*(one(f) for f in wanted))
    return {p: c for p, c in pairs if c is not None}


#: How a character the page shows may be spelled in JSX or HTML.
_SPELLINGS = {
    "'": r"(?:'|&apos;|&#39;|&rsquo;|’|\{\"'\"\})",
    "’": r"(?:’|'|&rsquo;|&#8217;)",
    '"': r"(?:\"|&quot;|&#34;|“|”)",
    "&": r"(?:&|&amp;)",
    " ": r"(?: |&nbsp;|\s)",
    "<": r"(?:<|&lt;)",
    ">": r"(?:>|&gt;)",
}


def text_pattern(text: str) -> re.Pattern:
    """`text` as the page shows it, matched however the source spells it:
    any run of whitespace (JSX wraps long copy across lines) and the usual
    entities for quotes and ampersands."""
    words = text.split()
    if not words:
        raise VisualError("There is no text to change.")
    parts = ["".join(_SPELLINGS.get(ch, re.escape(ch)) for ch in word) for word in words]
    return re.compile(r"\s+".join(parts))


def _context(content: str, start: int, end: int) -> str:
    """What the matched text sits in: a quoted string (which quote), JSX or
    HTML text, or data (md, json)."""
    before = content[:start].rstrip(" \t")
    after = content[end:].lstrip(" \t")
    for q in ('"', "'", "`"):
        if before.endswith(q) and after.startswith(q):
            return q
    return "text"


def escape_for(new: str, context: str, path: str) -> str:
    if context in ('"', "'"):
        if path.endswith(".json"):
            return json.dumps(new)[1:-1]
        return new.replace("\\", "\\\\").replace(context, "\\" + context).replace("\n", "\\n")
    if context == "`":
        return new.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    if path.endswith((".md", ".mdx")):
        return new
    out = new.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if path.endswith((".tsx", ".jsx")):
        out = out.replace("{", "&#123;").replace("}", "&#125;")
    return out


@dataclass
class TextEditResult:
    status: str                      # applied | not_found | ambiguous
    files: list[str] = field(default_factory=list)
    count: int = 0


def apply_text_edit(sources: dict[str, str], old: str, new: str,
                    every: bool = False) -> TextEditResult:
    """Change `old` to `new` in `sources` in place.

    Exactly one place, or every place when `every` is set. Copy the page
    builds from variables ("Hello, {name}") is not found here; the client
    offers to ask the model instead.
    """
    if len(new) > MAX_TEXT or len(old) > MAX_TEXT:
        raise VisualError("That text is too long to edit here.")
    if not new.strip():
        raise VisualError("Text cannot be left empty. Ask Vivid to remove it instead.")
    pattern = text_pattern(old)
    hits = {path: list(pattern.finditer(content)) for path, content in sources.items()}
    hits = {p: m for p, m in hits.items() if m}
    count = sum(len(m) for m in hits.values())
    if count == 0:
        return TextEditResult("not_found")
    if count > 1 and not every:
        return TextEditResult("ambiguous", sorted(hits), count)
    for path, matches in hits.items():
        content = sources[path]
        for m in reversed(matches):
            text = escape_for(new, _context(content, m.start(), m.end()), path)
            content = content[:m.start()] + text + content[m.end():]
        sources[path] = content
    return TextEditResult("applied", sorted(hits), count)


def relink(sources: dict[str, str], refs: list[str], new_ref: str) -> list[str]:
    """Point every use of an image at its replacement; the files changed."""
    changed = []
    for path, content in sources.items():
        updated = content
        for ref in refs:
            updated = updated.replace(ref, new_ref)
        if updated != content:
            sources[path] = updated
            changed.append(path)
    return changed


# ---------------------------------------------------------------- editor
EDITOR_START = "<!-- vivid:editor -->"
EDITOR_END = "<!-- /vivid:editor -->"

#: Framed and switched on by the parent, this makes copy editable in place
#: and pictures pickable. It posts only to the origin that switched it on.
EDITOR_SCRIPT = r"""<script>
(function () {
  if (window.parent === window || window.__vividEditor) return;
  window.__vividEditor = true;
  var on = false, owner = null, hovered = null, editing = null, original = "";
  var style = document.createElement("style");
  style.textContent =
    "[data-vivid-hover]{outline:2px dashed #7c5cff !important;outline-offset:2px;cursor:pointer !important}" +
    "[data-vivid-editing]{outline:2px solid #7c5cff !important;outline-offset:2px;cursor:text !important}";
  function send(msg) { if (owner) window.parent.postMessage(msg, owner); }
  function bgUrl(el) {
    for (var i = 0; el && i < 4; i++, el = el.parentElement) {
      var m = /url\(["']?([^"')]+)["']?\)/.exec(getComputedStyle(el).backgroundImage || "");
      if (m) return m[1];
    }
    return null;
  }
  function imageOf(el) {
    if (el.tagName === "IMG") return el.currentSrc || el.src;
    var pic = el.closest && el.closest("picture");
    if (pic) { var img = pic.querySelector("img"); if (img) return img.currentSrc || img.src; }
    return null;
  }
  function textOnly(el) {
    if (!el || el === document.body || el === document.documentElement) return false;
    if (/^(INPUT|TEXTAREA|SELECT|SCRIPT|STYLE|SVG|PATH|IMG|VIDEO|CANVAS|IFRAME)$/i.test(el.tagName)) return false;
    for (var i = 0; i < el.children.length; i++) if (el.children[i].tagName !== "BR") return false;
    return (el.textContent || "").trim().length > 0;
  }
  function mark(el) {
    if (hovered && hovered !== el) hovered.removeAttribute("data-vivid-hover");
    hovered = el;
    if (el && el !== editing) el.setAttribute("data-vivid-hover", "");
  }
  function finish(keep) {
    var el = editing;
    if (!el) return;
    editing = null;
    el.removeAttribute("data-vivid-editing");
    el.removeAttribute("contenteditable");
    var now = el.textContent || "";
    if (!keep) { el.textContent = original; return; }
    if (now.trim() && now.trim() !== original.trim()) send({ type: "vivid:text-edit", old: original, new: now });
    else el.textContent = original;
  }
  function onOver(e) { if (on) mark(e.target); }
  function onClick(e) {
    if (!on) return;
    var el = e.target;
    if (editing && editing.contains(el)) return;
    e.preventDefault(); e.stopPropagation();
    finish(true);
    var src = imageOf(el) || (textOnly(el) ? null : bgUrl(el));
    if (src) { send({ type: "vivid:image-pick", src: src }); return; }
    if (!textOnly(el)) { send({ type: "vivid:edit-hint", reason: "not_text" }); return; }
    editing = el; original = el.textContent || "";
    el.removeAttribute("data-vivid-hover");
    el.setAttribute("data-vivid-editing", "");
    try { el.contentEditable = "plaintext-only"; } catch (_) {}
    if (el.contentEditable !== "plaintext-only") el.contentEditable = "true";
    el.focus();
    var range = document.createRange(); range.selectNodeContents(el);
    var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
  }
  function onKey(e) {
    if (!editing) return;
    if (e.key === "Escape") { e.preventDefault(); finish(false); }
    else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
  }
  function onBlur(e) { if (editing && e.target === editing) finish(true); }
  function block(e) { if (on && !(editing && editing.contains(e.target))) { e.preventDefault(); e.stopPropagation(); } }
  function setMode(next) {
    if (next === on) return;
    on = next;
    var add = on ? "addEventListener" : "removeEventListener";
    document[add]("mouseover", onOver, true);
    document[add]("click", onClick, true);
    document[add]("keydown", onKey, true);
    document[add]("blur", onBlur, true);
    document[add]("submit", block, true);
    document[add]("mousedown", block, true);
    if (on) document.head.appendChild(style);
    else { finish(false); mark(null); if (style.parentNode) style.remove(); }
  }
  function bust(src) {
    var base = String(src || "").split("?")[0], stamp = "vivid=" + Date.now();
    document.querySelectorAll("img").forEach(function (img) {
      if ((img.currentSrc || img.src).split("?")[0] === base) {
        img.removeAttribute("srcset");
        img.src = base + "?" + stamp;
      }
    });
  }
  window.addEventListener("message", function (e) {
    if (e.source !== window.parent) return;
    var d = e.data || {};
    if (d.type === "vivid:edit-mode") { owner = e.origin; setMode(!!d.on); }
    else if (d.type === "vivid:image-updated" && e.origin === owner) bust(d.src);
  });
  window.parent.postMessage({ type: "vivid:editor-ready" }, "*");
})();
</script>"""

EDITOR_BLOCK = f"{EDITOR_START}\n{EDITOR_SCRIPT}\n{EDITOR_END}"
_BLOCK_RE = re.compile(re.escape(EDITOR_START) + r".*?" + re.escape(EDITOR_END) + r"\n?", re.S)


def with_editor(html: str) -> str:
    """index.html carrying the current editor block, exactly once."""
    html = _BLOCK_RE.sub("", html)
    if "</body>" in html:
        return html.replace("</body>", EDITOR_BLOCK + "\n</body>", 1)
    return html + "\n" + EDITOR_BLOCK + "\n"


def strip_editor(html: bytes) -> bytes:
    text = html.decode("utf-8", errors="replace")
    stripped = _BLOCK_RE.sub("", text)
    return html if stripped == text else stripped.encode("utf-8")


#: The page the preview loads: Vite's index.html, or an Expo app's
#: single-page template.
MOBILE_HTML = "public/index.html"


async def ensure_editor(sandbox: Sandbox) -> None:
    """Put the editor into the preview's index.html if it is missing or out
    of date. Cheap when it is already there: one read."""
    path = MOBILE_HTML if sandbox.target.is_mobile else "index.html"
    try:
        html = await sandbox.read_file(path)
    except FileNotFoundError:
        return
    if EDITOR_BLOCK in html:
        return
    await sandbox.write_file(path, with_editor(html))
