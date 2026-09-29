"""Which model owns a turn.

By stage, not by what the turn touches: planning writes the spec, build is
the first pass over the empty template, edit is everything after. One model
owns a whole turn; the fallback takes over for one retry when the primary
hits the step cap or keeps failing the typecheck.
"""
from app.core.config import settings
from app.services.models_gateway import provider

PLAN = "plan"
BUILD = "build"
EDIT = "edit"
FALLBACK = "fallback"
#: Launch videos (video.py): motion design needs a stronger model.
VIDEO = "video"


def stage_for(snapshot_seq: int) -> str:
    """Build until the first snapshot exists, edit from then on."""
    return BUILD if snapshot_seq == 0 else EDIT


def slug_for(stage: str) -> str:
    return {
        PLAN: settings.PLAN_MODEL,
        BUILD: settings.BUILD_MODEL,
        EDIT: settings.EDIT_MODEL,
        FALLBACK: settings.FALLBACK_MODEL,
        VIDEO: settings.VIDEO_MODEL,
    }[stage]


def endpoint_for(stage: str) -> provider.Endpoint:
    return provider.openrouter_model(slug_for(stage),
                                     context_tokens=settings.BUILDER_CONTEXT_TOKENS)
