"""What a model call cost, from OpenRouter's public price list.

`/api/v1/models` publishes per-token prices for every slug (prompt,
completion, and the cached-input rate). The listing is fetched once and
kept for an hour; a call is priced from the usage object the stream
returned. When the listing cannot be fetched the cost is None, never a
guess: a usage row with an unknown price is a gap to fill, a wrong price is
a lie in the ledger.
"""
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.models_gateway import http

log = logging.getLogger("vivid.builder.pricing")

_TTL = 3600
_cache: dict[str, "Price"] = {}
_fetched_at = 0.0


@dataclass(frozen=True)
class Price:
    """USD per token."""
    prompt: float
    completion: float
    cached: float | None

    def cost(self, usage: dict) -> float:
        reported = usage.get("cost")                     # OpenRouter's own figure, cache writes included
        if isinstance(reported, (int, float)) and reported > 0:
            return float(reported)
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        cached = min(cached, prompt)
        rate = self.cached if self.cached is not None else self.prompt
        return ((prompt - cached) * self.prompt + cached * rate
                + completion * self.completion)


async def price_of(model: str) -> Price | None:
    await _refresh()
    return _cache.get(model)


async def cost_of(model: str, usage: dict | None) -> float | None:
    if not usage:
        return None
    price = await price_of(model)
    return round(price.cost(usage), 8) if price else None


async def _refresh() -> None:
    global _fetched_at
    if _cache and time.monotonic() - _fetched_at < _TTL:
        return
    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/models"
    try:
        r = await http.client().get(url, timeout=20)
        r.raise_for_status()
        rows = r.json().get("data") or []
    except (httpx.HTTPError, ValueError) as e:
        log.warning("could not fetch model prices: %s", e)
        _fetched_at = time.monotonic() - _TTL + 60      # retry in a minute
        return
    fresh: dict[str, Price] = {}
    for row in rows:
        pricing = row.get("pricing") or {}
        try:
            fresh[row["id"]] = Price(
                prompt=float(pricing.get("prompt") or 0),
                completion=float(pricing.get("completion") or 0),
                cached=(float(pricing["input_cache_read"])
                        if pricing.get("input_cache_read") not in (None, "") else None))
        except (KeyError, TypeError, ValueError):
            continue
    if fresh:
        _cache.clear()
        _cache.update(fresh)
        _fetched_at = time.monotonic()
