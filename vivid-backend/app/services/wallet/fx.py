"""Exchange rates for the wallet: converting bank deposits to USD, and
showing the USD balance in naira and other currencies.

Rates are USD-based from open.er-api.com (the source the chat's
exchange_rate tool uses), kept for an hour. When a refresh fails the last
good rates stay in use; with none at all, conversions raise rather than
guess, because a made-up rate would credit the wrong amount.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.services.models_gateway import http
from app.services.wallet import MICRO

log = logging.getLogger("vivid.wallet.fx")

URL = "https://open.er-api.com/v6/latest/USD"
TTL = 3600

#: Minor units per major unit; everything the wallet sees has two.
_DECIMALS = {"USD": 2, "NGN": 2, "GHS": 2, "KES": 2, "ZAR": 2, "EUR": 2, "GBP": 2}


class RatesUnavailable(Exception):
    pass


@dataclass
class Rates:
    #: Units of each currency per 1 USD.
    per_usd: dict[str, float]
    as_of: datetime


_cache: Rates | None = None
_fetched = 0.0


async def rates() -> Rates:
    global _cache, _fetched
    if _cache is not None and time.monotonic() - _fetched < TTL:
        return _cache
    try:
        r = await http.client().get(URL, timeout=settings.PAYMENTS_API_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("result") != "success" or not data.get("rates"):
            raise ValueError(data.get("error-type") or "no rates")
        _cache = Rates(per_usd={k: float(v) for k, v in data["rates"].items()},
                       as_of=datetime.fromtimestamp(int(data.get("time_last_update_unix") or 0)
                                                    or time.time(), tz=timezone.utc))
        _fetched = time.monotonic()
    except (httpx.HTTPError, ValueError) as e:
        if _cache is None:
            raise RatesUnavailable(f"exchange rates unavailable: {e}") from e
        log.warning("rates refresh failed, keeping those from %s: %s", _cache.as_of, e)
        _fetched = time.monotonic() - TTL + 300          # try again in 5 minutes
    return _cache


def set_rates(per_usd: dict[str, float]) -> None:
    """For tests and a manual override."""
    global _cache, _fetched
    _cache = Rates(per_usd=dict(per_usd), as_of=datetime.now(timezone.utc))
    _fetched = time.monotonic()


async def rate(currency: str) -> float:
    currency = currency.upper()
    if currency == "USD":
        return 1.0
    value = (await rates()).per_usd.get(currency)
    if not value:
        raise RatesUnavailable(f"no rate for {currency}")
    return value


async def minor_to_usd_micro(amount_minor: int, currency: str,
                             spread_bps: int | None = None) -> tuple[int, float]:
    """A deposit in `currency` minor units (kobo) as micro-USD, less the FX
    spread. Returns (micro_usd, rate used)."""
    fx = await rate(currency)
    major = amount_minor / 10 ** _DECIMALS.get(currency.upper(), 2)
    spread = settings.WALLET_FX_SPREAD_BPS if spread_bps is None else spread_bps
    usd = major / fx * (1 - spread / 10_000)
    return int(usd * MICRO), fx


async def display(amount_micro: int, currency: str) -> dict:
    """{currency, amount, rate, as_of} for showing a USD amount elsewhere."""
    currency = currency.upper()
    fx = await rate(currency)
    as_of = (await rates()).as_of if currency != "USD" and _cache else None
    return {"currency": currency, "amount": round(amount_micro / MICRO * fx, 2),
            "rate": fx, "as_of": as_of}
