---
name: vividpay-mobile
description: How to take payments with Vivid Pay (pay by bank transfer) in an Expo mobile app the builder makes.
---

# Payments with Vivid Pay in the app (pay by bank transfer)

The customer gets an account number made for their order, switches to their bank app
(OPay, Kuda, GTB...), sends the exact amount, and comes back to see the order paid within
seconds. The money goes to the owner's Vivid earnings; the app never holds money or a key
that can move it. Amounts are in **kobo** (₦12,500 is 1250000).

`EXPO_PUBLIC_VIVIDPAY_KEY` and `EXPO_PUBLIC_VIVIDPAY_API` are in .env.
- **Test key while developing.** In the sandbox, the web preview and Expo Go use a test
  key: checkouts are `mode: "test"`, with no real account and no money. Show a
  "Simulate payment" button for those.
- **Live key in builds.** Installable builds get the live key automatically. Never
  hard-code either key.

## The client (write lib/vividpay.ts exactly like this)
```ts
const API = process.env.EXPO_PUBLIC_VIVIDPAY_API as string;
const KEY = process.env.EXPO_PUBLIC_VIVIDPAY_KEY as string;

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
  return call<Checkout>("/checkouts", {
    method: "POST", headers: { "Content-Type": "text/plain" },
    body: JSON.stringify({ key: KEY, amount_kobo: order.amountKobo, reference: order.reference,
                           customer: order.customer, metadata: order.metadata }),
  });
}

export const getCheckout = (id: string) =>
  call<Checkout>(`/checkouts/${id}?key=${encodeURIComponent(KEY)}`);

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
```

## Waiting for the payment
Poll `getCheckout` every 3 seconds **only while the app is in the foreground**. The
customer leaves for their bank app and comes back, so:
- listen to `AppState` and check immediately when it becomes `active` again;
- stop polling when the screen unmounts, or the status is `paid` or `expired`.

```ts
useEffect(() => {
  let alive = true;
  const tick = async () => {
    const c = await getCheckout(id).catch(() => null);
    if (alive && c) setCheckout(c);
  };
  const timer = setInterval(tick, 3000);
  const sub = AppState.addEventListener("change", (s) => { if (s === "active") tick(); });
  tick();
  return () => { alive = false; clearInterval(timer); sub.remove(); };
}, [id]);
```

## The checkout screen
A stack screen (`app/checkout/[orderId].tsx`) or a full-height sheet:

1. **Before paying:** collect name and phone first, then call `createCheckout` with the
   order id as the reference.
2. **The account details** go on one card:
   - the amount, large (`text-4xl font-bold`, tabular numbers);
   - the **account number** in a large monospace font, grouped 3-3-4 (`888 179 6023`);
   - a **Copy** button beside it: `expo-clipboard`'s `Clipboard.setStringAsync` (install
     with `npx expo install expo-clipboard`), a success haptic, and a "Copied" label for 2s;
   - the bank name and account name ("<App name> via Vivid");
   - a countdown to `expires_at`.
3. **Help line:** "Open your bank app, send exactly this amount to the account above, then
   come back here. It confirms automatically."
4. **Status:** a calm "Waiting for your transfer…" row with an ActivityIndicator.
   - **After 3 minutes,** it changes to "Banks can take a few minutes. You can leave this
     screen; your order will update."
5. **Paid:** a success screen with a check that springs in, a success haptic, the order
   number, and a button back to the orders.
6. **Partial:** show what arrived and what's left, and keep waiting.
7. **Expired:** a "Get a new account number" button, which creates a checkout with a new
   reference (`${orderId}-2`).
8. **Test mode** (`checkout.mode === "test"`): a clearly labelled "Simulate payment"
   button that calls `simulatePayment`. Never show it on live checkouts.

Keep the order and its checkout id in the store (AsyncStorage), so an app restart
resumes the wait. The Orders tab shows each order's payment status.

## Paying in crypto (only when `checkout.crypto_enabled`)
Customers can pay in USDC or USDT; Vivid converts it and the owner is paid in naira, so
the order confirms exactly like a transfer (same polling, same states).
- Two tabs on the checkout: **Bank transfer** (default) and **Crypto**. Hide the Crypto tab
  when `crypto_enabled` is false.
- Crypto asks for the payer's name, email, phone and address (required by our partner;
  prefill from the order), then calls `payWithCrypto` once.
- Then show: the **address** in monospace with a Copy button and a QR code of it
  (`npx expo install react-native-qrcode-svg`, `<QRCode value={address} size={176} />`; the copy button uses expo-clipboard with a haptic), `crypto.accepts` as the networks line, and "Send about
  **{crypto.due_usdc} USDC**" labelled as an estimate ("rates move; any shortfall shows
  here and you can top up to the same address").
- A warning line: "Only send USDC or USDT on the networks listed. Other coins or networks
  can be lost." Minimum about $3.
- Keep polling as for transfers. On `partial`, show what is left in naira and the new
  `crypto.due_usdc` for the rest, to the same address.
- Test mode: the address is a placeholder; show it with the Simulate payment button.

## With Supabase
- **Orders table:** create it with RLS. Only the service role changes the status.
- **Webhook:** the same `vivid-pay-webhook` edge function as on the web. It checks the
  `x-vivid-pay-signature` header (hex HMAC-SHA256 of the body with
  `VIVIDPAY_SECRET_KEY`) and marks the order paid.
- **Polling:** the app still polls for instant feedback. The webhook is what makes the
  database true.

## Rules
- Never put `VIVIDPAY_SECRET_KEY` in the app.
- One checkout per order attempt; reuse the reference on retries.
- Prices come from the app's data, never from user input.
- Format naira with `Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN" })`
  after dividing kobo by 100.
