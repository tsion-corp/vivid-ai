"""Skills: packaged expertise the orchestrator attaches to a turn.

A skill is a folder under BUILDER_SKILLS_DIR with a SKILL.md (frontmatter
plus the method) and optional references/. Nobody picks a skill; the loader
chooses by project state and stage: the design skill for turns that touch
UI, one page recipe matched to the spec, and the palette and font tables so
choices are curated rather than invented. Loaded once and cached; the text
changes only with a deploy, which keeps the prompt cacheable upstream.
"""
import logging
import re
from functools import lru_cache
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("vivid.builder.skills")

def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip()
    return text


def _root() -> Path:
    return Path(settings.BUILDER_SKILLS_DIR)


@lru_cache(maxsize=32)
def _read(rel: str) -> str:
    path = _root() / rel
    try:
        return _strip_frontmatter(path.read_text(encoding="utf-8")).strip()
    except OSError:
        log.warning("skill file missing: %s", path)
        return ""


def clear_cache() -> None:
    _read.cache_clear()


_TITLE = re.compile(r"^#\s*Recipe:\s*(.+)$", re.M)


def _recipe_dir(mobile: bool) -> str:
    """Page recipes for websites; screen recipes for mobile apps."""
    return "mobile/references/recipes" if mobile else "design/references/recipes"


def recipes(mobile: bool = False) -> list[dict]:
    """The recipes on disk, name and title, so the planner can offer
    exactly what exists: dropping a file in the folder adds a recipe."""
    rel = _recipe_dir(mobile)
    out = []
    for path in sorted((_root() / rel).glob("*.md")):
        text = _read(f"{rel}/{path.name}")
        m = _TITLE.search(text)
        out.append({"name": path.stem, "title": (m.group(1).strip() if m else path.stem)})
    return out


def recipe_names(mobile: bool = False) -> list[str]:
    return [r["name"] for r in recipes(mobile)]


def recipe_menu(mobile: bool = False) -> str:
    """One line per recipe for a prompt."""
    return "\n".join(f"- {r['name']}: {r['title']}" for r in recipes(mobile))


async def pick_recipe(text: str, mobile: bool = False) -> str | None:
    """Ask the planning model which recipe fits a project that skipped plan
    mode. One short call; the answer is stored on the project so it runs
    once. Returns None when nothing fits or the call fails."""
    names = recipe_names(mobile)
    if not names or not (text or "").strip():
        return None
    from app.builder import routing
    from app.services.models_gateway import code_llm
    kind = "screen" if mobile else "page"
    prompt = (f"Which {kind} recipe fits this app best? Answer with the recipe name only, "
              f"or 'none'.\n\nRecipes:\n{recipe_menu(mobile)}\n\nApp:\n{text[:2000]}")
    try:
        out = []
        async for ev in code_llm.stream_chat([{"role": "user", "content": prompt}], [],
                                             endpoint=routing.endpoint_for(routing.PLAN),
                                             max_tokens=20, temperature=0):
            if ev.get("type") == "token":
                out.append(ev["text"])
        answer = "".join(out).strip().lower().strip(".'\"`")
    except Exception as e:                                 # a missing recipe is not a failed turn
        log.warning("recipe pick failed: %s", e)
        return None
    return answer if answer in names else None


def design_block(spec_md: str | None, user_text: str = "", recipe: str | None = None) -> str:
    """The design skill for a UI turn: method, palettes, fonts, and the
    recipe the plan chose (or pick_recipe stored) for this project."""
    if not settings.BUILDER_DESIGN_SKILL:
        return ""
    parts = [_read("design/SKILL.md")]
    if not parts[0]:
        return ""
    if recipe and recipe in recipe_names():
        text = _read(f"design/references/recipes/{recipe}.md")
        if text:
            parts.append(text)
    for ref in ("design/references/palettes.md", "design/references/fonts.md"):
        text = _read(ref)
        if text:
            parts.append(text)
    block = "\n\n".join(p for p in parts if p)
    return "## Design skill\n" + block


#: Always part of the mobile skill, in this order: the method, then the kit
#: every screen is built from, then how screens connect, then the rest.
_MOBILE_REFS = ("components", "navigation", "native-apis", "motion", "fonts")


def mobile_block(backend: bool = False, recipe: str | None = None) -> str:
    """The mobile skill for an Expo app: native design method, the component
    kit, navigation, the device APIs Expo Go has, motion and fonts, the
    screen recipe the plan chose, and the data layer: on the phone, or
    Supabase when a backend is linked. Takes the design and motion skills'
    place; the palettes still apply."""
    method = _read("mobile/SKILL.md")
    if not method:
        return ""
    parts = [method] + [_read(f"mobile/references/{ref}.md") for ref in _MOBILE_REFS]
    if recipe and recipe in recipe_names(mobile=True):
        parts.append(_read(f"mobile/references/recipes/{recipe}.md"))
    parts.append(_read("mobile/references/supabase.md" if backend
                       else "mobile/references/state.md"))
    parts.append(_read("design/references/palettes.md"))
    return "## Mobile app skill\n" + "\n\n".join(p for p in parts if p)


def copy_block() -> str:
    """The copy skill for any turn that writes visible text."""
    if not settings.BUILDER_COPY_SKILL:
        return ""
    text = _read("copy/SKILL.md")
    return "## Copy skill\n" + text if text else ""


def payments_block(provider: str | None, mobile: bool = False) -> str:
    """The payments skill, when the project takes payments. A mobile app
    only takes Vivid Pay (Paystack's checkout is a web script)."""
    if not provider or provider == "none":
        return ""
    if provider == "vividpay":
        text = _read("vividpay/MOBILE.md" if mobile else "vividpay/SKILL.md")
        return "## Payments skill (Vivid Pay)\n" + text if text else ""
    if mobile:
        return ""
    text = _read("payments/SKILL.md")
    return "## Payments skill\n" + text if text else ""


def fullstack_block(backend: bool) -> str:
    """The app-logic skill, when the project has a Supabase backend: accounts,
    roles and policies, data, lifecycles, edge functions, and the patterns
    (SQL and TypeScript) to copy so every project has the same shape."""
    if not backend or not settings.BUILDER_FULLSTACK_SKILL:
        return ""
    text = _read("fullstack/SKILL.md")
    if not text:
        return ""
    patterns = _read("fullstack/references/patterns.md")
    block = text + ("\n\n" + patterns if patterns else "")
    return "## App logic skill\n" + block


def maps_block(provider: str | None) -> str:
    """The maps skill, when the project has a Google Maps key."""
    if not provider or provider == "none":
        return ""
    text = _read("maps/SKILL.md")
    return "## Maps skill\n" + text if text else ""


def auth_block(provider: str | None) -> str:
    """The auth skill, when the app signs its users in with Decane."""
    if provider != "decane":
        return ""
    text = _read("auth/SKILL.md")
    return "## Sign-in skill\n" + text if text else ""


#: Recipes with a marketing face and a hero: they get the motion skill.
_MOTION_RECIPES = {"landing", "platform", "portfolio", "shop", "restaurant", "event", "real-estate",
                   "course", "saas", "nonprofit", "fitness", "hotel", "travel", "agency", "marketplace",
                   "crowdfunding", "membership", "personal", "wedding", "newsletter", "nft-drop",
                   "token-launch", "dao", "exchange", "ticketing", "magazine", "directory"}
_MOTION_WORDS = ("animat", "motion", "parallax", "gsap", "framer", "shader", "scroll effect",
                 "transition", "hover effect", "sparkle", "glitter", "grain")


def motion_block(recipe: str | None, user_text: str = "") -> str:
    """The motion skill for pages that sell (the recipes with a hero) or for
    any request that asks for animation."""
    if not settings.BUILDER_MOTION_SKILL:
        return ""
    low = (user_text or "").lower()
    if recipe not in _MOTION_RECIPES and not any(w in low for w in _MOTION_WORDS):
        return ""
    text = _read("motion/SKILL.md")
    if not text:
        return ""
    patterns = _read("motion/references/patterns.md")
    return "## Motion skill\n" + text + ("\n\n" + patterns if patterns else "")


def web3_block(on: bool) -> str:
    """The web3 skill with its patterns, when the project is on-chain."""
    if not on or not settings.BUILDER_WEB3_SKILL:
        return ""
    text = _read("web3/SKILL.md")
    if not text:
        return ""
    patterns = _read("web3/references/patterns.md")
    return "## Web3 skill\n" + text + ("\n\n" + patterns if patterns else "")


def ui_block(spec_md: str | None, user_text: str = "",
             payments: str | None = None, backend: bool = False,
             recipe: str | None = None, maps: str | None = None,
             chain: bool = False, auth: str | None = None,
             mobile: bool = False) -> str:
    """Everything a build or edit turn gets: the design skill with its
    recipe, the copy skill, the app-logic skill when a backend is linked,
    the sign-in skill when the app has Decane sign-in (after app logic,
    whose auth rules it overrides), and the payments skill when payments
    are enabled. The design skill is
    first because the recipe names the sections the copy fills; app logic
    comes before payments because the payments flow builds on its orders.
    A mobile app gets the mobile skill in place of the web design and motion
    skills; web-only integrations never reach it."""
    if mobile:
        blocks = (mobile_block(backend, recipe), copy_block(), fullstack_block(backend),
                  payments_block(payments, mobile=True))
        return "\n\n".join(b for b in blocks if b)
    blocks = (design_block(spec_md, user_text, recipe), copy_block(),
              motion_block(recipe, user_text),
              fullstack_block(backend), auth_block(auth), payments_block(payments),
              maps_block(maps), web3_block(chain))
    return "\n\n".join(b for b in blocks if b)


def available() -> list[str]:
    root = _root()
    if not root.is_dir():
        return []
    return sorted(p.parent.name for p in root.glob("*/SKILL.md"))
