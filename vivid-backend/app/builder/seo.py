"""How a published site presents itself: its title, description, the
picture link previews show, the tab icon, and whether search engines index
it. The person sets these in the project's settings; they are written into
the built index.html at publish time, never into the source, so the agent's
own tags stay as the default for anything left empty.
"""
import html as html_mod
import io
import re
import tarfile

#: Longest values that still read well in a search result and a card.
TITLE_MAX, DESCRIPTION_MAX = 70, 200

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _meta_re(attr: str, name: str) -> re.Pattern:
    return re.compile(rf"<meta\b[^>]*\b{attr}\s*=\s*[\"']{re.escape(name)}[\"'][^>]*>\s*", re.I)


def _content(tag: str) -> str | None:
    m = re.search(r"\bcontent\s*=\s*(\"([^\"]*)\"|'([^']*)')", tag, re.I)
    return html_mod.unescape(m.group(2) if m.group(2) is not None else m.group(3)) if m else None


def read(index_html: str) -> dict:
    """What the page says about itself now: title, description, image."""
    out: dict = {"title": None, "description": None, "image": None}
    m = _TITLE.search(index_html)
    if m:
        out["title"] = html_mod.unescape(re.sub(r"\s+", " ", m.group(1)).strip()) or None
    for key, attr, name in (("description", "name", "description"), ("image", "property", "og:image")):
        m = _meta_re(attr, name).search(index_html)
        if m:
            out[key] = _content(m.group(0)) or None
    return out


def from_snapshot(data: bytes) -> str | None:
    """index.html out of a snapshot tarball, without starting a sandbox."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for name in ("./index.html", "index.html"):
                try:
                    member = tf.getmember(name)
                except KeyError:
                    continue
                return tf.extractfile(member).read().decode("utf-8", errors="replace")
    except tarfile.TarError:
        return None
    return None


def _absolute(path: str, base: str | None) -> str:
    if re.match(r"^https?://", path) or not base:
        return path
    return base.rstrip("/") + "/" + path.lstrip("/")


def apply(index_html: bytes, seo: dict | None, site_url: str | None = None) -> bytes:
    """index.html with the settings written into <head>. Only the fields
    that are set replace the page's own tags."""
    if not seo:
        return index_html
    page = index_html.decode("utf-8", errors="replace")
    tags: list[str] = []
    esc = lambda v: html_mod.escape(v, quote=True)                             # noqa: E731

    def drop(attr: str, *names: str) -> None:
        nonlocal page
        for name in names:
            page = _meta_re(attr, name).sub("", page)

    title = (seo.get("title") or "").strip()
    if title:
        if _TITLE.search(page):
            page = _TITLE.sub(f"<title>{html_mod.escape(title)}</title>", page, count=1)
        else:
            tags.append(f"<title>{html_mod.escape(title)}</title>")
        drop("property", "og:title")
        drop("name", "twitter:title")
        tags += [f'<meta property="og:title" content="{esc(title)}">',
                 f'<meta name="twitter:title" content="{esc(title)}">']
    description = (seo.get("description") or "").strip()
    if description:
        drop("name", "description", "twitter:description")
        drop("property", "og:description")
        tags += [f'<meta name="description" content="{esc(description)}">',
                 f'<meta property="og:description" content="{esc(description)}">',
                 f'<meta name="twitter:description" content="{esc(description)}">']
    image = (seo.get("image") or "").strip()
    if image:
        url = _absolute(image, site_url)
        drop("property", "og:image")
        drop("name", "twitter:image", "twitter:card")
        tags += [f'<meta property="og:image" content="{esc(url)}">',
                 f'<meta name="twitter:image" content="{esc(url)}">',
                 '<meta name="twitter:card" content="summary_large_image">']
    if site_url and (title or description or image):
        drop("property", "og:url")
        tags.append(f'<meta property="og:url" content="{esc(site_url)}">')
    favicon = (seo.get("favicon") or "").strip()
    if favicon:
        page = re.sub(r"<link\b[^>]*\brel\s*=\s*[\"'](?:shortcut )?icon[\"'][^>]*>\s*", "", page, flags=re.I)
        tags.append(f'<link rel="icon" href="{esc(favicon)}">')
    if seo.get("noindex"):
        drop("name", "robots")
        tags.append('<meta name="robots" content="noindex">')
    if not tags:
        return page.encode("utf-8")
    block = "\n    ".join(tags)
    if re.search(r"</head>", page, re.I):
        page = re.sub(r"</head>", block + "\n  </head>", page, count=1, flags=re.I)
    else:
        page = block + page
    return page.encode("utf-8")
