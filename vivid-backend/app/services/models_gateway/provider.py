"""Which upstream answers a model call: our own pods, or OpenRouter.

MODEL_PROVIDER decides. Every caller above this module asks for an endpoint by
ROLE — the chat assistant, the coding agent, speech-to-text, text-to-speech —
and gets back a base URL, a vendor model id, the headers that upstream wants
and the context window it serves. It never learns which provider it got, and
that is the whole point: when a GPU is down, moving the product onto
OpenRouter is a config change and a restart, not a client release and not a
frontend deploy.

What stays on the backend either way: conversation history, the prompt, the
token budgets, translation, speech normalisation. The provider only changes
where the finished request is sent and what the model is called there.

Nothing else in the codebase may look at OPENROUTER_*, LLM_BASE_URL,
ASR_BASE_URL or TTS_BASE_URL directly.
"""
import re
from dataclasses import dataclass

from app.core.config import settings

RUNPOD = "runpod"
OPENROUTER = "openrouter"


class UpstreamError(Exception):
    """Base for every adapter's failure. Two messages on purpose:

    str(e) is the DETAIL — the status code, the upstream's own words, which
    host — and is for the log. `public` is the only part a client may see,
    and never names an upstream: a user of Vivid is not told that Vivid is
    on OpenRouter this afternoon, and a developer on the /v1 proxy is not
    handed our billing state. Adapters raise with the detail and override
    `public` only when they have something safe and useful to say.
    """
    public: str = "That didn't work just now. Please try again."

    def __init__(self, detail: str, public: str | None = None):
        super().__init__(detail)
        if public is not None:
            self.public = public


def public_message(e: Exception) -> str:
    """What a client may be told about `e`."""
    return getattr(e, "public", None) or UpstreamError.public


# Belt and braces for the client boundaries: even a message that was never
# meant to quote an upstream must not carry a host, a vendor or an env var.
_URL = re.compile(r"https?://[^\s'\"<>)\]]+")
_HOST = re.compile(r"\b[\w.-]*(?:runpod\.net|openrouter\.ai)\b", re.I)
_VENDOR = re.compile(r"\b(?:open ?router|runpod|vllm)\b", re.I)
_ENV_VAR = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def scrub(text: str) -> str:
    """`text` with anything that identifies an upstream replaced."""
    text = _URL.sub("the model service", text)
    text = _HOST.sub("the model service", text)
    text = _VENDOR.sub("the model service", text)
    return _ENV_VAR.sub("a server setting", text)

#: The assistant's model: chat turns, title generation, the tool planner.
CHAT = "chat"
#: The coding agent's model: native tool calling over long loops.
CODE = "code"
#: Speech-to-text for voice turns and the composer mic.
ASR = "asr"
#: Text-to-speech for voice replies.
TTS = "tts"
#: Picture generation for the generate_image tool.
IMAGE = "image"
#: Clip generation for the generate_video tool.
VIDEO = "video"

#: Roles the MODEL_PROVIDER switch moves between the pods and OpenRouter.
SWITCHED_ROLES = (CHAT, CODE, ASR, TTS)
#: Roles only OpenRouter serves: the pods have nothing that makes pictures or
#: video, so these ignore the switch and exist only while the key is set.
MEDIA_ROLES = (IMAGE, VIDEO)
ROLES = SWITCHED_ROLES + MEDIA_ROLES


@dataclass(frozen=True)
class Endpoint:
    """One place a request for `role` can be sent."""
    provider: str
    role: str
    #: Service root; for the LLM roles the OpenAI-compatible root incl. /v1.
    base_url: str
    #: What the upstream calls the model. Empty for pods that serve one thing.
    model: str
    #: Why this endpoint cannot be called, in the words of the env var an
    #: operator has to set. None when it can.
    missing: str | None = None
    #: Served context window, for the LLM roles. The backend budgets history
    #: and replies against this, so it must be the real number for whichever
    #: upstream is live — a pod's 8k and OpenRouter's 128k are not the same.
    context_tokens: int = 0

    @property
    def configured(self) -> bool:
        return self.missing is None

    @property
    def headers(self) -> dict[str, str]:
        """Per-request headers, merged over the shared client's own. The pods
        take none; OpenRouter needs the key, and takes attribution."""
        if self.provider != OPENROUTER:
            return {}
        headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
        if settings.OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
        if settings.OPENROUTER_APP_NAME:
            headers["X-Title"] = settings.OPENROUTER_APP_NAME
        return headers

    def url(self, path: str = "/chat/completions") -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    @property
    def extra_payload(self) -> dict:
        """Fields the upstream wants in every chat-completions body beyond
        the OpenAI shape. vLLM takes none. OpenRouter takes a routing
        preference, which decides which host answers and therefore how long
        the first token takes."""
        if self.provider != OPENROUTER:
            return {}
        extra: dict = {"usage": {"include": True}}       # usage carries OpenRouter's own cost (cache writes too)
        if settings.OPENROUTER_PROVIDER_SORT:
            extra["provider"] = {"sort": settings.OPENROUTER_PROVIDER_SORT}
        return extra

    @property
    def is_pod(self) -> bool:
        """True when the upstream is our own server, whose quirks (vLLM
        flags, the 200-with-error convention) the adapters may reason about."""
        return self.provider == RUNPOD


def provider_for(role: str) -> str:
    """The master switch, unless this role has its own override set."""
    if role in MEDIA_ROLES:
        return OPENROUTER
    override = {
        CHAT: settings.LLM_PROVIDER,
        CODE: settings.CODE_LLM_PROVIDER,
        ASR: settings.ASR_PROVIDER,
        TTS: settings.TTS_PROVIDER,
    }.get(role, "")
    return override or settings.MODEL_PROVIDER


def endpoint(role: str) -> Endpoint:
    """The endpoint currently serving `role`. Always returns one; check
    `.configured` (or read `.missing`) before calling it."""
    if role not in ROLES:
        raise ValueError(f"unknown model role {role!r}")
    if provider_for(role) == OPENROUTER:
        return _openrouter(role)
    return _runpod(role)


def _runpod(role: str) -> Endpoint:
    if role == CODE:
        # One-pod deployments serve the coder off the chat pod rather than
        # 404ing: degraded is more useful than absent. The model name follows
        # the same rule so a request never names a model the pod is not running.
        base = settings.CODE_LLM_BASE_URL or settings.LLM_BASE_URL
        model = (settings.CODE_LLM_MODEL
                 or (settings.LLM_MODEL if not settings.CODE_LLM_BASE_URL else ""))
        missing = ("CODE_LLM_BASE_URL is not set" if not base
                   else "CODE_LLM_MODEL is not set" if not model else None)
        return Endpoint(RUNPOD, role, base.rstrip("/"), model, missing,
                        context_tokens=settings.CODE_LLM_CONTEXT_TOKENS)
    if role == CHAT:
        base, model = settings.LLM_BASE_URL, settings.LLM_MODEL
        missing = ("LLM_BASE_URL is not set" if not base
                   else "LLM_MODEL is not set" if not model else None)
        return Endpoint(RUNPOD, role, base.rstrip("/"), model, missing,
                        context_tokens=settings.LLM_CONTEXT_TOKENS)
    if role == ASR:
        base = settings.ASR_BASE_URL
        return Endpoint(RUNPOD, role, base.rstrip("/"), "",
                        None if base else "ASR_BASE_URL is not configured")
    # TTS rides on the ASR server unless it has its own address.
    base = settings.TTS_BASE_URL or settings.ASR_BASE_URL
    return Endpoint(RUNPOD, role, base.rstrip("/"), "",
                    None if base else
                    "neither TTS_BASE_URL nor ASR_BASE_URL is configured")


def _openrouter(role: str) -> Endpoint:
    model, model_var, window = {
        CHAT: (settings.OPENROUTER_CHAT_MODEL, "OPENROUTER_CHAT_MODEL",
               settings.OPENROUTER_CHAT_CONTEXT_TOKENS),
        # Empty code model falls back to the chat one, mirroring the pods.
        CODE: (settings.OPENROUTER_CODE_MODEL or settings.OPENROUTER_CHAT_MODEL,
               "OPENROUTER_CHAT_MODEL", settings.OPENROUTER_CODE_CONTEXT_TOKENS),
        ASR: (settings.OPENROUTER_STT_MODEL, "OPENROUTER_STT_MODEL", 0),
        TTS: (settings.OPENROUTER_TTS_MODEL, "OPENROUTER_TTS_MODEL", 0),
        IMAGE: (settings.OPENROUTER_IMAGE_MODEL, "OPENROUTER_IMAGE_MODEL", 0),
        VIDEO: (settings.OPENROUTER_VIDEO_MODEL, "OPENROUTER_VIDEO_MODEL", 0),
    }[role]
    missing = ("OPENROUTER_API_KEY is not set" if not settings.OPENROUTER_API_KEY
               else f"{model_var} is not set" if not model else None)
    return Endpoint(OPENROUTER, role, settings.OPENROUTER_BASE_URL.rstrip("/"),
                    model, missing, context_tokens=window)


#: The app builder's turns. Not a switched role: nothing on the pods serves
#: a tool-calling model with the window a build needs, so this always goes
#: to OpenRouter, and the slug is chosen per stage by app/builder/routing.py.
BUILDER = "builder"


def openrouter_model(model: str, role: str = BUILDER,
                     context_tokens: int = 0) -> Endpoint:
    """An OpenRouter endpoint for an explicit slug.

    For callers that pick their model by something other than MODEL_PROVIDER
    (the builder routes by stage). Same headers, same attribution, same
    routing preference as the switched roles; only the model differs.
    """
    missing = ("OPENROUTER_API_KEY is not set" if not settings.OPENROUTER_API_KEY
               else "no model slug given" if not model else None)
    return Endpoint(OPENROUTER, role, settings.OPENROUTER_BASE_URL.rstrip("/"),
                    model, missing, context_tokens=context_tokens)


def describe(role: str) -> dict:
    """What /health reports: enough for an operator to see at a glance which
    way the switch is set, and never the key."""
    ep = endpoint(role)
    out = {"provider": ep.provider, "configured": ep.configured}
    if ep.model:
        out["model"] = ep.model
    if ep.missing:
        out["missing"] = ep.missing
    return out
