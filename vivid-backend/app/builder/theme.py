"""The site's look, changed by hand: its main colour, corner roundness and
fonts. Generated websites keep these as CSS variables in src/index.css
(:root and .dark, oklch values, shadcn style) and one Google Fonts <link> in
index.html (the design skill's convention), so they are rewritten exactly
rather than by asking the model. A project that does not follow the
convention answers `supported: False`, and the client offers the chat.
"""
import math
import re

#: The design skill's palettes (skills/design/references/palettes.md):
#: light primary, dark primary.
PALETTES: dict[str, tuple[str, str]] = {
    "ink": ("oklch(0.25 0.02 260)", "oklch(0.85 0.02 260)"),
    "forest": ("oklch(0.42 0.12 150)", "oklch(0.72 0.14 150)"),
    "cobalt": ("oklch(0.5 0.2 258)", "oklch(0.7 0.16 258)"),
    "terracotta": ("oklch(0.58 0.15 40)", "oklch(0.75 0.13 40)"),
    "plum": ("oklch(0.45 0.16 330)", "oklch(0.75 0.13 330)"),
    "ember": ("oklch(0.6 0.22 28)", "oklch(0.72 0.19 28)"),
    "sand": ("oklch(0.35 0.03 70)", "oklch(0.85 0.03 70)"),
    "ocean": ("oklch(0.55 0.13 220)", "oklch(0.75 0.11 220)"),
    "gold": ("oklch(0.78 0.14 85)", "oklch(0.82 0.14 85)"),
    "lime": ("oklch(0.85 0.2 130)", "oklch(0.85 0.2 130)"),
    "navy": ("oklch(0.28 0.06 265)", "oklch(0.8 0.06 265)"),
}

#: The design skill's font pairings (references/fonts.md): heading, body.
FONTS: dict[str, tuple[str, str]] = {
    "modern": ("Inter Tight", "Inter"),
    "grotesk": ("Space Grotesk", "Inter"),
    "editorial": ("Fraunces", "Inter"),
    "serif-luxe": ("Playfair Display", "Source Sans 3"),
    "rounded": ("Manrope", "Manrope"),
    "geometric": ("Outfit", "Outfit"),
    "classic": ("Libre Baskerville", "Lato"),
    "bold": ("Sora", "Inter"),
}


class ThemeError(Exception):
    pass


# ------------------------------------------------------------------ colour
def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_to_oklch(value: str) -> tuple[float, float, float]:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ThemeError("Use a colour like #1f6feb.")
    r, g, b = (_lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.hypot(a, bb)
    H = math.degrees(math.atan2(bb, a)) % 360
    return L, C, H


def oklch_to_hex(L: float, C: float, H: float) -> str:
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return "#" + "".join(f"{round(_gamma(c) * 255):02x}" for c in (r, g, bl))


_OKLCH = re.compile(r"oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)")


def parse_oklch(value: str) -> tuple[float, float, float] | None:
    m = _OKLCH.search(value or "")
    if not m:
        return None
    L = float(m.group(1)) / (100 if m.group(2) else 1)
    return L, float(m.group(3)), float(m.group(4))


def fmt(L: float, C: float, H: float) -> str:
    return f"oklch({L:.3g} {C:.3g} {H:.4g})"


def foreground_for(value: str) -> str:
    """Text on the colour: near-white on a dark one, near-black on a light one."""
    lch = parse_oklch(value)
    return "oklch(0.985 0 0)" if lch is None or lch[0] < 0.7 else "oklch(0.205 0 0)"


def dark_variant(value: str) -> str:
    """The same hue, lightened enough to hold contrast on a dark page."""
    L, C, H = parse_oklch(value) or (0.6, 0.1, 260)
    return fmt(max(L, min(0.85, L + 0.25)), C, H)


# --------------------------------------------------------------------- css
def _block(css: str, selector: str) -> re.Match | None:
    return re.search(rf"(^|\n)\s*{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", css)


def _var(body: str, name: str) -> str | None:
    m = re.search(rf"--{re.escape(name)}\s*:\s*([^;]+);", body)
    return m.group(1).strip() if m else None


def _set_var(css: str, selector: str, name: str, value: str) -> str:
    """css with --name set inside `selector { }` (added when missing)."""
    m = _block(css, selector)
    if m is None:
        return css
    body = m.group("body")
    if re.search(rf"--{re.escape(name)}\s*:", body):
        new = re.sub(rf"(--{re.escape(name)}\s*:\s*)[^;]+;", lambda mm: f"{mm.group(1)}{value};", body, count=1)
    else:
        new = body.rstrip() + f"\n  --{name}: {value};\n"
    return css[:m.start("body")] + new + css[m.end("body"):]


def _font_name(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(",")[0].strip().strip("'\"")
    return first or None


def read(index_css: str, index_html: str) -> dict:
    root = _block(index_css, ":root")
    primary = _var(root.group("body"), "primary") if root else None
    lch = parse_oklch(primary or "")
    theme_body = (_block(index_css, "@theme inline") or _block(index_css, "@theme"))
    fonts_body = (theme_body.group("body") if theme_body else "") + (root.group("body") if root else "")
    radius = _var(root.group("body"), "radius") if root else None
    rem = re.match(r"([\d.]+)rem", radius or "")
    return {
        "supported": lch is not None,
        "primary": oklch_to_hex(*lch) if lch else None,
        "radius": float(rem.group(1)) if rem else None,
        "font_heading": _font_name(_var(fonts_body, "font-display")) or _font_name(_var(fonts_body, "font-heading")),
        "font_body": _font_name(_var(fonts_body, "font-sans")),
        "fonts_link": "fonts.googleapis.com" in index_html,
    }


def _fonts_link(heading: str, body: str) -> str:
    families = []
    for family in dict.fromkeys((heading, body)):
        families.append("family=" + family.replace(" ", "+") + ":wght@400;500;600;700")
    return ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
            + "&".join(families) + '&display=swap">')


def write(index_css: str, index_html: str, change: dict) -> tuple[str, str]:
    """The two files with `change` applied: {palette | primary (hex),
    radius (rem), fonts (a pairing name)}. Raises ThemeError when the
    project does not keep its theme where this can change it."""
    if not read(index_css, index_html)["supported"]:
        raise ThemeError("This app doesn't keep its colours where they can be changed by hand.")
    css, html = index_css, index_html
    light = dark = None
    if change.get("palette"):
        if change["palette"] not in PALETTES:
            raise ThemeError("Unknown palette.")
        light, dark = PALETTES[change["palette"]]
    elif change.get("primary"):
        light = fmt(*hex_to_oklch(change["primary"]))
        dark = dark_variant(light)
    if light:
        for selector, value in ((":root", light), (".dark", dark)):
            css = _set_var(css, selector, "primary", value)
            css = _set_var(css, selector, "primary-foreground", foreground_for(value))
            css = _set_var(css, selector, "ring", value)
    if change.get("radius") is not None:
        radius = float(change["radius"])
        if not 0 <= radius <= 2:
            raise ThemeError("Roundness goes from 0 to 2.")
        css = _set_var(css, ":root", "radius", f"{radius:g}rem")
    if change.get("fonts"):
        if change["fonts"] not in FONTS:
            raise ThemeError("Unknown font pairing.")
        heading, body = FONTS[change["fonts"]]
        target = "@theme inline" if _block(css, "@theme inline") else ":root"
        css = _set_var(css, target, "font-sans", f'"{body}", ui-sans-serif, system-ui, sans-serif')
        css = _set_var(css, target, "font-display", f'"{heading}", ui-sans-serif, system-ui, sans-serif')
        html = re.sub(r'\s*<link\b[^>]*href="https://fonts\.googleapis\.com/css2[^"]*"[^>]*>', "", html)
        link = _fonts_link(heading, body)
        if "fonts.gstatic.com" not in html:
            link = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n    '
                    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n    ' + link)
        html = re.sub(r"</head>", f"  {link}\n  </head>", html, count=1, flags=re.I)
    return css, html
