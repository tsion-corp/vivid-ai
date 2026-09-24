"""A Vivid user's wallet: USD balance, bank and crypto top-ups, charges.

ledger.py moves money; fx.py converts and displays it; pouch.py and
dextopus.py are the two ways money comes in; deposits.py turns a provider's
deposit into a ledger credit, for the webhooks and the reconciler alike.
"""
MICRO = 1_000_000


def to_micro(usd: float) -> int:
    return int(round(usd * MICRO))


def to_usd(micro: int) -> float:
    return micro / MICRO
