---
name: forms
description: Contact, booking, quote and newsletter forms that deliver to the site owner by email, with no backend. Applies to websites whose page has a form.
---

# Forms that reach the owner

`VITE_VIVID_FORMS_URL` is set in .env. Posting a form there stores what was sent and
emails it to the site's owner, and a reply to that email goes to the visitor's `email`
field. Use it for every form whose job is to reach the owner (contact, booking request,
quote, enquiry, catering, newsletter sign-up) unless the app keeps that data in its own
backend. Never fake a form with a `setTimeout` "sent" or a `mailto:` link.

## Sending

```ts
const FORMS_URL = import.meta.env.VITE_VIVID_FORMS_URL as string;

async function send(form: string, fields: Record<string, string>) {
  const res = await fetch(FORMS_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ form, ...fields }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error?.message ?? "It didn't send. Try again in a minute.");
  }
}
```

- `form` names it in the owner's inbox: "contact", "booking", "quote", "newsletter".
- Field names are the labels the owner reads: `name`, `email`, `phone`, `date`,
  `guests`, `message`. Values are strings. Send `email` whenever the form asks for one,
  so the owner can reply.
- Add a hidden honeypot the visitor never sees and bots fill in:
  `<input type="text" name="_gotcha" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden />`
  and send its value as `_gotcha`.

## The form itself
- Real labels, the right input types (`email`, `tel`, `date`), `required` on what is needed.
- The button disables while sending and says "Sending…".
- Success replaces the form with a plain confirmation ("Thanks, Ada. We'll reply within a
  day."). Keep the visitor's words if it fails, and show the error in plain words next to
  the button, with a way to try again.
- The preview works too: a submission from the preview reaches the owner marked as a test.

## Final reply
Say where messages go: to the owner's email, and in the project's settings under Forms.
