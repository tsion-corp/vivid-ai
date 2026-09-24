"""What a project builds: a website or a mobile app.

The target is chosen when the project is created and never changes. It
decides which sandbox template the project runs in, how the dev server is
started and reached, which files the model is always shown, how the code is
typechecked, which commands are off limits, where uploads live, and which
integrations exist.

This module is configuration only: no prompt text, no imports from the rest
of the builder, so anything can import it. The prompts, briefs and skills
that differ per target live in their own modules and switch on
`target.name`.

The sandbox carries its target (`Sandbox.target`), because a sandbox is made
from a target's template; tools, typecheck, screenshots and the context
block read it from there instead of taking another argument.
"""
import re
from dataclasses import dataclass, field

from app.core.config import settings

WEB = "web"
MOBILE = "mobile"


@dataclass(frozen=True)
class Target:
    name: str
    #: Names of the settings holding the E2B template, the dev port and the
    #: template's directory on disk (local driver). Read when used, so a
    #: setting changed at runtime (tests, env) is honoured.
    template_setting: str
    port_setting: str
    template_dir_setting: str
    #: The local driver's dev server command; "{port}" is filled in.
    local_dev_cmd: tuple[str, ...]
    #: Shown to the model on every turn when they exist.
    key_files: tuple[str, ...]
    typecheck_cmd: str
    #: Blocked on top of tools.BLOCKED: (pattern, reason).
    blocked: tuple[tuple[re.Pattern, str], ...]
    #: Public env vars the app bundle can read.
    env_prefix: str
    #: Where uploads and generated pictures are copied in the app.
    upload_dir: str
    #: Screenshots the critique takes: (name, width). The template's
    #: scripts/screenshot.mjs writes <name>.jpg for each.
    shots: tuple[tuple[str, int], ...]
    #: Project integrations this target supports.
    integrations: frozenset[str] = field(default_factory=frozenset)
    #: The template's size (its template.py), for pricing sandbox time.
    vcpus: int = 2
    memory_gib: float = 2.0

    def sandbox_cost_per_second(self) -> float:
        return (self.vcpus * settings.E2B_COST_PER_VCPU_SECOND
                + self.memory_gib * settings.E2B_COST_PER_GIB_SECOND)

    @property
    def e2b_template(self) -> str:
        return getattr(settings, self.template_setting)

    @property
    def port(self) -> int:
        return getattr(settings, self.port_setting)

    @property
    def template_dir(self) -> str:
        return getattr(settings, self.template_dir_setting)

    @property
    def is_mobile(self) -> bool:
        return self.name == MOBILE

    def env(self, name: str) -> str:
        """`SUPABASE_URL` as this target's app reads it."""
        return self.env_prefix + name


_WEB = Target(
    name=WEB,
    template_setting="E2B_TEMPLATE",
    port_setting="BUILDER_DEV_PORT",
    template_dir_setting="BUILDER_TEMPLATE_DIR",
    local_dev_cmd=("npm", "run", "dev", "--", "--host", "127.0.0.1",
                   "--port", "{port}", "--strictPort"),
    key_files=("src/App.tsx", "src/main.tsx", "package.json"),
    typecheck_cmd="npx tsc --noEmit -p tsconfig.app.json",
    blocked=(),
    env_prefix="VITE_",
    upload_dir="public/uploads",
    shots=(("desktop", 1280), ("mobile", 390)),
    integrations=frozenset({"supabase", "payments", "maps", "chain", "auth"}),
)

_MOBILE = Target(
    name=MOBILE,
    template_setting="E2B_MOBILE_TEMPLATE",
    port_setting="BUILDER_MOBILE_DEV_PORT",
    template_dir_setting="BUILDER_MOBILE_TEMPLATE_DIR",
    local_dev_cmd=("npx", "expo", "start", "--port", "{port}"),
    key_files=("app/_layout.tsx", "app/(tabs)/_layout.tsx", "app.json", "package.json"),
    typecheck_cmd="npx tsc --noEmit",
    blocked=(
        (re.compile(r"\b(npx\s+)?expo\s+(start|run:\w+|prebuild|export)\b"),
         "starting, prebuilding or exporting the app (Metro is already running)"),
        (re.compile(r"\b(npx\s+)?eas\b"), "cloud builds (the user starts those from Vivid)"),
        (re.compile(r"\b(npm\s+(install|i|add)|yarn\s+add|pnpm\s+add)\s+[^-\s]"),
         "installing packages with npm; use `npx expo install <pkg>` so the version "
         "matches the Expo SDK"),
    ),
    env_prefix="EXPO_PUBLIC_",
    upload_dir="assets/uploads",
    shots=(("iphone", 390), ("android", 412)),
    integrations=frozenset({"supabase"}),
    memory_gib=4.0,
)

_BY_NAME = {t.name: t for t in (_WEB, _MOBILE)}
NAMES = tuple(_BY_NAME)


def get(name: str | None) -> Target:
    """The target called `name`; rows from before targets existed are web."""
    return _BY_NAME.get(name or WEB, _WEB)


def of(obj) -> Target:
    """The target of a project row or a sandbox (anything with `.target`)."""
    value = getattr(obj, "target", None)
    if isinstance(value, Target):
        return value
    return get(value)
