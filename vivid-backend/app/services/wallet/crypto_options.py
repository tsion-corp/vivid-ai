"""The crypto a user can top up with: one static Dextopus address per
option, every deposit bridged and settled as USDC on Base to Vivid.

Addresses and chain ids are from the Dextopus integration guide
(swap-api.dextopus.com/llms.txt). `available()` drops any the API does not
list as supporting static addresses, so a token Dextopus stops supporting
disappears instead of taking deposits it cannot route.
"""
from dataclasses import dataclass

BASE, ETHEREUM, ARBITRUM, POLYGON, BSC = 8453, 1, 42161, 137, 56
SOLANA, TRON = 792703809, 728126428

#: What deposits settle into: USDC on Base.
SETTLEMENT_CHAIN = BASE
SETTLEMENT_ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
SETTLEMENT_DECIMALS = 6


@dataclass(frozen=True)
class Option:
    key: str
    symbol: str
    chain: str
    chain_id: int
    asset: str
    #: What the user must send it from; shown next to the address.
    network_note: str


OPTIONS: tuple[Option, ...] = (
    Option("usdc-base", "USDC", "Base", BASE, SETTLEMENT_ASSET, "Base network only"),
    Option("usdt-tron", "USDT", "Tron", TRON, "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "TRC-20 only"),
    Option("usdc-solana", "USDC", "Solana", SOLANA, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
           "Solana (SPL) only"),
    Option("usdt-bsc", "USDT", "BNB Chain", BSC, "0x55d398326f99059fF775485246999027B3197955",
           "BEP-20 only"),
    Option("usdc-ethereum", "USDC", "Ethereum", ETHEREUM, "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
           "ERC-20 only; Ethereum fees are high for small amounts"),
    Option("usdt-ethereum", "USDT", "Ethereum", ETHEREUM, "0xdAC17F958D2ee523a2206206994597C13D831ec7",
           "ERC-20 only; Ethereum fees are high for small amounts"),
    Option("usdc-arbitrum", "USDC", "Arbitrum", ARBITRUM, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
           "Arbitrum One only"),
    Option("usdc-polygon", "USDC", "Polygon", POLYGON, "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
           "Polygon PoS only (native USDC)"),
    Option("eth-base", "ETH", "Base", BASE, "0x0000000000000000000000000000000000000000",
           "Base network only"),
    Option("sol-solana", "SOL", "Solana", SOLANA, "11111111111111111111111111111111", "Solana only"),
)

BY_KEY = {o.key: o for o in OPTIONS}


def get(key: str) -> Option | None:
    return BY_KEY.get(key)


# --------------------------------------------------------------- the catalog
# Beyond the options above, any token Dextopus takes on any chain can fund a
# wallet: the person picks a network, then a token, as in the Add funds flow.

#: The generic "native gas token" address Dextopus's per-chain catalog uses;
#: address generation wants the all-zero address on EVM chains and the system
#: program id on Solana instead (verified live).
NATIVE_PLACEHOLDER = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
EVM_NATIVE = "0x0000000000000000000000000000000000000000"
SOLANA_NATIVE = "11111111111111111111111111111111"

#: Shown first on the network step.
RECOMMENDED = ("Base", "Ethereum", "Solana", "Tron", "Polygon", "Arbitrum", "BNB Chain",
               "Optimism", "Avalanche")
#: Shown first on the token step: what most people hold to pay with.
TOKEN_ORDER = ("USDC", "USDT")


def origin_asset(chain_id: int, address: str) -> str:
    """The token address Dextopus's generate endpoint accepts."""
    if address.lower() != NATIVE_PLACEHOLDER:
        return address
    return SOLANA_NATIVE if chain_id == SOLANA else EVM_NATIVE


def pair_key(chain_id: int, asset: str) -> str:
    """A funding option key for any chain and token (fits the 32-char column).
    The ten named options keep their own keys, so existing addresses carry on."""
    for o in OPTIONS:
        if o.chain_id == chain_id and o.asset.lower() == asset.lower():
            return o.key
    import hashlib
    return "c-" + hashlib.sha256(f"{chain_id}:{asset.lower()}".encode()).hexdigest()[:24]
