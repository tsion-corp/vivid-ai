---
name: vividpay
description: How to take payments with Vivid Pay (pay by bank transfer) in an app the builder makes. Applies when the project has Vivid Pay enabled.
---

# Payments with Vivid Pay (pay by bank transfer)

The owner takes payments through Vivid. At checkout the customer gets an account number
made for their order and pays by bank transfer from any Nigerian bank app; the app sees
the order paid within seconds. The money goes to the owner's Vivid earnings. The app
never holds money or keys that can move it. Amounts are in **kobo** (₦12,500 is 1250000).

`VITE_VIVIDPAY_KEY` (publishable, safe in the bundle) and `VITE_VIVIDPAY_API` are in .env.

## The client (write src/lib/vividpay.ts exactly like this)
```ts
const API = import.meta.env.VITE_VIVIDPAY_API as string;
const KEY = import.meta.env.VITE_VIVIDPAY_KEY as string;

export type Checkout = {
  id: string; reference: string; mode: "live" | "test";
  status: "pending" | "paid" | "partial" | "expired";
  amount_kobo: number; paid_kobo: number;
  account_number: string; account_name: string; bank_name: string;
  expires_at: string; paid_at: string | null; late: boolean;
  /** Paying in crypto is offered only when this is true. */
  crypto_enabled: boolean;
  crypto: null | { address: string; network: string; accepts: string; due_usdc: string;
                   rate: number; estimate: true };
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.error?.message || "Payment service unavailable");
  return body as T;
}

/** Same reference, same checkout: safe to call again for one order. */
export function createCheckout(order: {
  reference: string; amountKobo: number;
  customer?: { name?: string; email?: string; phone?: string };
  metadata?: Record<string, unknown>;
}) {
  // text/plain on purpose: no CORS preflight.
  return call<Checkout>("/checkouts", {
    method: "POST", headers: { "Content-Type": "text/plain" },
    body: JSON.stringify({ key: KEY, amount_kobo: order.amountKobo, reference: order.reference,
                           customer: order.customer, metadata: order.metadata }),
  });
}

export const getCheckout = (id: string) =>
  call<Checkout>(`/checkouts/${id}?key=${encodeURIComponent(KEY)}`);

/** Preview only: pays a test checkout without money. */
export const simulatePayment = (id: string) =>
  call<Checkout>(`/checkouts/${id}/simulate`, {
    method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify({ key: KEY }),
  });

/** Pay this checkout in crypto instead: returns the checkout with `crypto` set
 *  (the deposit address). Pouch converts what arrives and it confirms like a
 *  transfer. The payer's name, email, phone and address are required. */
export const payWithCrypto = (id: string, payer: { name: string; email: string; phone: string; address: string }) =>
  call<Checkout>(`/checkouts/${id}/crypto`, {
    method: "POST", headers: { "Content-Type": "text/plain" },
    body: JSON.stringify({ key: KEY, network: "evm", payer }),
  });

/** Polls every 3s until paid, partial or expired. */
export async function waitForPayment(id: string, onUpdate: (c: Checkout) => void, signal?: AbortSignal) {
  for (;;) {
    if (signal?.aborted) return;
    const c = await getCheckout(id).catch(() => null);
    if (c) {
      onUpdate(c);
      if (c.status !== "pending") return c;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
}
```

## The checkout screen (a PayByTransfer component)
1. Collect name, email or phone first, then create the checkout with the order id as the
   `reference`. Show a spinner for the second it takes.
2. Show, large and clear:
   - the amount in naira;
   - **account number** with a Copy button (toast "Copied");
   - **bank name** and **account name** (it reads "<App name> via Vivid");
   - a countdown to `expires_at` ("Pay within 29:41");
   - one line: "Transfer exactly this amount from any bank app. It confirms here
     automatically."
3. Start `waitForPayment` right away and show "Waiting for your transfer…" with a soft
   pulse. Add an "I've sent it" button that only reassures and keeps waiting.
4. On `paid`: a success state with a check, the order reference and what happens next.
   On `partial`: show how much arrived and how much is left
   (`amount_kobo - paid_kobo`), and keep waiting. On `expired`: offer "Get a new account
   number". That creates a checkout with a new reference, e.g. `${orderId}-2`.
5. When `checkout.mode === "test"` (the builder preview), show a clearly labelled
   **Simulate payment** button that calls `simulatePayment` and nothing else.
   Never show it for live checkouts.

Make it feel trustworthy:
- the account number in a large monospace font (tabular figures), grouped 3-3-4;
- the app's logo above it;
- the amount on its own line;
- no clutter.

On phones, the copy button is the primary action.

## Paying in crypto (only when `checkout.crypto_enabled`)
Customers can pay in USDC or USDT; Vivid converts it and the owner is paid in naira, so
the order confirms exactly like a transfer (same polling, same states).
- Two tabs on the checkout: **Bank transfer** (default) and **Crypto**. Hide the Crypto tab
  when `crypto_enabled` is false.
- Crypto asks for the payer's name, email, phone and address (required by our partner;
  prefill from the order), then calls `payWithCrypto` once.
- Then show: the **address** in monospace with a Copy button and a QR code of it
  (`npm install qrcode.react`, `<QRCodeSVG value={address} size={176} />`), `crypto.accepts` as the networks line, and "Send about
  **{crypto.due_usdc} USDC**" labelled as an estimate ("rates move; any shortfall shows
  here and you can top up to the same address").
- A warning line: "Only send USDC or USDT on the networks listed. Other coins or networks
  can be lost." Minimum about $3.
- Keep polling as for transfers. On `partial`, show what is left in naira and the new
  `crypto.due_usdc` for the rest, to the same address.
- Test mode: the address is a placeholder; show it with the Simulate payment button.

## Orders
- **Without a backend:** keep the order locally. When the checkout polls `paid`, mark it
  paid and show it in the customer's orders. Tell the user in one line that linking
  Supabase makes payment confirmation server-side.
- **With Supabase:** the verified flow.
  1. Migration: `orders` (id, items jsonb, amount_kobo, customer, status 'pending' | 'paid'
     | 'partial', checkout_id, reference, paid_at). RLS on. Anon may insert a pending
     order and read its own. **Only the service role changes status.**
  2. Edge function `vivid-pay-webhook` (verify_jwt false):
     - check the `x-vivid-pay-signature` header: hex HMAC-SHA256 of the raw body with the
       `VIVIDPAY_SECRET_KEY` secret (already set when the account is connected);
     - on `checkout.paid` or `checkout.partial`, update the order by `data.reference` with
       the service role.
     Tell the user to paste the function URL into Vivid Pay's webhook field in the
     project's settings.
  3. The page still polls `getCheckout` for instant feedback. The webhook is what makes
     the database true.
  4. The owner's admin shows orders with payment status and paid time.

## Rules
- Never put `VIVIDPAY_SECRET_KEY` in the app bundle, and never call the secret-key route
  from the browser.
- One checkout per order attempt. Reuse the same reference on retries, and a new
  reference only after `expired`.
- Prices come from the app's data, never from the URL or a form field.
- Amounts are integers in kobo; format with `Intl.NumberFormat("en-NG", { style:
  "currency", currency: "NGN" })` after dividing by 100.
