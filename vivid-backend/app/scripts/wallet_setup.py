"""One-time wallet setup: register the payment webhooks and check the
providers are ready.

    python -m app.scripts.wallet_setup

Run on the server inside the backend container, with PUBLIC_BASE_URL,
POUCH_API_KEY, DEXTOPUS_API_KEY and DEXTOPUS_SETTLEMENT_ADDRESS set. Prints
the webhook secrets to put in app.env (POUCH_WEBHOOK_SECRET,
DEXTOPUS_WEBHOOK_SECRET), then restart the backend.
"""
import asyncio

from app.core.config import settings
from app.services.wallet import crypto_options, dextopus, pouch


async def main() -> None:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    if not base.startswith("https://"):
        print(f"PUBLIC_BASE_URL is {base!r}; webhooks need the public https URL of this backend.")
        return

    print("== Pouch (bank transfers)")
    if not pouch.configured():
        print("  POUCH_API_KEY is not set; skipped.")
    else:
        try:
            me = await pouch.integrator()
            print(f"  integrator: {me.get('name')} ({me.get('status')}), "
                  f"default settlement {me.get('default_settlement')}")
            url = f"{base}/v1/webhooks/pouch"
            await pouch.set_webhook(url)
            me = await pouch.integrator()
            print(f"  webhook: {me.get('webhook_url')}")
            print("  secret: read it from the Pouch dashboard (or GET /api/v1/integrator) and set "
                  "POUCH_WEBHOOK_SECRET. Without it payments still credit: every webhook is "
                  "checked against the API, and the reconciler runs every "
                  f"{settings.WALLET_RECONCILE_SECONDS}s.")
        except pouch.PouchError as e:
            print(f"  FAILED: {e}. Set the webhook URL {base}/v1/webhooks/pouch in the Pouch dashboard.")

    print("== Dextopus (crypto)")
    if not settings.DEXTOPUS_API_KEY:
        print("  DEXTOPUS_API_KEY is not set; skipped.")
        return
    if not settings.DEXTOPUS_SETTLEMENT_ADDRESS:
        print("  DEXTOPUS_SETTLEMENT_ADDRESS (Vivid's USDC treasury on Base) is not set.")
    try:
        data = await dextopus.set_webhook(f"{base}/v1/webhooks/dextopus")
        print(f"  webhook: {data.get('webhookUrl')}  events: {', '.join(data.get('events') or [])}")
        if data.get("secret"):
            print(f"  DEXTOPUS_WEBHOOK_SECRET={data['secret']}")
        for chain_id in sorted({o.chain_id for o in crypto_options.OPTIONS}):
            supported = await dextopus.supported(chain_id)
            for o in (o for o in crypto_options.OPTIONS if o.chain_id == chain_id):
                ok = o.asset.lower() in supported
                print(f"  {o.key:<14} {'ok' if ok else 'NOT supported for static addresses'}")
        print("  Also set default refund addresses (EVM, Solana, Tron) in the Dextopus dashboard: "
              "Integrations > Edit > Default Refund Addresses. Addresses cannot be made without them.")
    except dextopus.DextopusError as e:
        print(f"  FAILED: {e}")


if __name__ == "__main__":
    asyncio.run(main())
