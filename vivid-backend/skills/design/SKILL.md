---
name: design
description: How to make a web app look designed rather than generated. Applies to every turn that creates or changes UI.
---

# Design method

You are designing for a real business and its customers, on phones first. A page is
finished when a stranger understands what it is and what to do within three seconds,
on a 390px screen, without zooming.

## Layout and rhythm
- One idea per section. Each section has one heading, one supporting line, one action.
- Spacing on a 4px grid, in steps of 4/8/12/16/24/32/48/64/96. Section padding: py-16 on
  phones, py-24 on desktop. Never two different gaps doing the same job.
- Content width: max-w-6xl for pages, max-w-prose for text. Center it. Side padding px-4
  on phones, px-6 from sm, px-8 from lg.
- Grid: 1 column on phones, 2 from sm or md, 3 or 4 from lg. Cards in a grid have equal
  height and the same internal padding.
- Align to the left edge inside sections; center only short heroes and empty states.

## Type
- Two sizes of heading per page, one body size, one small size. Nothing else.
- Pick the pairing from the fonts table by audience, load it, and use the display font
  on every heading. A shop for young buyers wants the grotesk pairing; a bakery the
  editorial one. Never leave the default system font on headings.
- Hero: text-4xl sm:text-5xl lg:text-6xl, font-semibold, tracking-tight, leading-[1.05].
- Section titles: text-2xl sm:text-3xl, font-semibold, tracking-tight.
- Body: text-base leading-relaxed; secondary text: text-sm text-muted-foreground.
- Line length under 65 characters: max-w-prose or max-w-xl on paragraphs.
- Load the chosen font pairing in index.html (Google Fonts) and set it in index.css.

## Colour and contrast
- Use the theme tokens (background, foreground, primary, muted, accent, border). Add at
  most one accent colour for the whole app; use it for the primary action and links.
- Premium reads as restraint: never a pure saturated primary (#ff0000, #0000ff). Soften
  the accent (a coral instead of red, a cobalt instead of blue: chroma about 0.15 to
  0.19 in oklch) and use it on the primary button, eyebrow labels and one highlight per
  screen, nothing else. On dark themes: background near-black (oklch 0.13 to 0.16),
  cards one step lighter, borders at white/10, text at 0.92 not pure white.
- An eyebrow label above the hero headline (small caps, tracking-wider, accent colour,
  a place or a promise: "SURULERE · LAGOS") is worth more than a badge.
- Body text is foreground on background, never grey on grey. Muted text only for labels,
  captions and metadata, and never below 14px.
- Dark mode works because you used tokens, not literal colours. Never hardcode #fff.

## Make it distinctive, not generated
Before writing code, decide in one line each: the palette's four to six named colours and
their jobs, the font pairing, the one hero element of the home page, and the one bold
thing (a 3D tilting product card, an oversized number, an editorial serif headline, a
mesh-gradient hero, a floating product mockup). Then check the plan against the brief:
if it would suit any business, change it until it only suits this one.
- Spend boldness in one place per page; everything else is calm and consistent.
- Hierarchy from contrast: size jumps of 3x between the hero and body, weight extremes
  (a 700 headline over 400 body), muted text for metadata only.
- Depth: cards sit on the background with a hairline border and a soft, wide shadow
  (`shadow-[0_1px_2px_rgb(0_0_0/0.04),0_8px_24px_rgb(0_0_0/0.06)]`); floating things
  (sticky header, popovers, a mockup) get more; on dark themes use a lighter surface and
  a `border-white/10` hairline instead of shadow. Never flat boxes on a flat page.
- Shape contrast: pill buttons and badges (`rounded-full`), 16 to 24px cards, 8 to 12px
  inputs. Uniform small corners everywhere read as a template.
- Atmosphere behind the hero: a tinted gradient or soft blurred blobs in the palette,
  with grain; never a purple-to-blue gradient on white, never a gradient behind body text.

## Feel: micro-interactions on every page
Even a dashboard needs these (the motion skill adds more for pages that sell):
- Every button and card responds: a colour or border shift on hover (200 ms), a press
  scale of 0.98 (`active:scale-[0.98] transition-transform`), a visible focus ring.
- Async actions show their work: the button shows a spinner, then "Saved ✓", then
  returns; a toast confirms. Copy buttons turn into a check with "Copied".
- Tabs, segmented controls and toggles slide their active indicator (motion's
  `layoutId`) rather than jumping.
- Numbers that matter (totals, balances, stats) count up once when they appear.
- Lists add and remove rows with a short slide and fade (`AnimatePresence` + `layout`);
  skeletons shaped like the content while loading, never a lone spinner.
- Durations 150 to 300 ms here, ease-out; nothing on a working screen loops or waits.
  Respect `prefers-reduced-motion` (`<MotionConfig reducedMotion="user">` in App.tsx).

## Imagery
- Every image has a fixed aspect ratio (aspect-[4/3], aspect-square, aspect-video), fills
  it with object-cover, and has a rounded-lg or rounded-xl corner matching the cards.
- Uploaded files are the product; show them large.
- No upload for a product, a hero or a section that needs a picture? Make one with
  generate_image: describe the exact item ("a red and white running sneaker, side view,
  on a light grey surface"), one image per product, and one kind=lifestyle image for the
  hero (a group of the products in dramatic light). Never ship a grey box, a broken image
  or an empty aspect-ratio block. If image generation is unavailable, use a gradient
  block with the item's initial as the last resort.
- Consistency is what makes generated photos look like a real catalogue: use the same
  phrase for the setting in every product prompt ("on a light grey studio surface, side
  view, soft light") so the set matches; vary only the item.
- People: the apps are for Nigeria. Every generated picture with a person shows Black
  Africans, and the prompt says so ("a Black Nigerian dispatch rider in an orange jacket").
  A hero with the wrong faces reads as a template; never ship one.
- Platforms (delivery, logistics, fintech, marketplaces, SaaS) do not sell with stock-like
  photos. Their hero shows the product: build a `ProductMockup` component that renders a
  real, data-filled screen of the app (the dashboard, the order tracker, the rider view)
  inside a device frame (rounded-2xl, ring-1, shadow-2xl, a slim top bar with three dots),
  and use kind=illustration tiles or shape-and-gradient tiles for benefit cards. Photos of
  people appear only as small, warm accents (a rider, a customer), never as the whole hero.
- Logo: if the user uploaded one, use it in the header at h-8 (phones) to h-10, never
  stretched. If not, make a mark with generate_image kind=logo: one bold symbol tied to
  the business in a vibrant two-colour gradient (the palette's primary and its bright
  partner), app-icon quality, no text. Show it at h-9 with rounded-xl and the brand name
  next to it in the heading font (font-semibold tracking-tight). A flat single-colour
  square is not a logo; the mark must look like it came from a brand agency.

## Components and states
- Use the shadcn components in src/components/ui. One primary button per view; the rest
  are outline or ghost. Buttons have a clear verb ("Book a slot", not "Submit").
- Every list has an empty state with one line and one action. Every async action has a
  loading state and a toast on success or failure.
- Inputs have labels above, help text below, and a visible focus ring. Touch targets are
  at least h-11 on phones.
- Hover states are subtle (a border or background shift), never a jump in size.

## Roles: customers never see the owner's tools
- A public site has two audiences. The customer nav and footer carry customer pages only.
  Anything for the owner (admin, dashboard, stock, orders, bookings list) lives at `/admin`,
  not linked from the customer nav; at most a small "Owner sign in" link in the footer.
  `/admin` itself is the owner's front door: signed out it shows the admin sign-in form,
  signed in as owner it shows the dashboard; no other route for it.
- The customer nav changes with the session: signed out it shows Sign in; signed in it shows
  the account items (My orders, My bookings) and the name. Never show a signed-in-only page
  to a visitor who is not signed in.
- Without a backend, gate /admin with a sign-in screen that checks a PIN or password
  kept in the code, remember it in localStorage, and tell the user in the final reply that
  this keeps customers out but is not real security until a backend is linked.
- With a Supabase backend, the gate is real: Supabase auth for the owner, a `profiles`
  table with a `role` column, RLS policies so only `role = 'admin'` can write products,
  orders and bookings, and admin routes that redirect anyone else. Hiding a link is not
  security; the policies are.
- The owner's pages look like a tool (dense, tables, forms); the customer's pages look
  like a shop. Do not mix the two styles.

## Every site ships with
- A favicon: when a logo mark is generated it is also saved as /favicon.png and linked from
  index.html automatically; when the user uploaded a logo, write `public/favicon.png` from
  it (run_command with the file copied) and make sure index.html has
  `<link rel="icon" type="image/png" href="/favicon.png" />` and an apple-touch-icon link.
  A site with the Vite default icon is unfinished.
- A real `<title>` ("Kicks Lagos · Sneakers in Surulere"), a `<meta name="description">`
  of one sentence, `<meta name="theme-color">` in the primary colour, and Open Graph
  title, description and image (the hero picture) so a shared link shows a card.

## Navigation
- Header: logo left, up to five links, one primary action right. On phones the links
  collapse into a menu button (use the dropdown-menu component); the primary action stays.
- Signed in, the header's right side is an account menu (the dropdown-menu component,
  trigger = avatar initial or name, `cursor-pointer`): My orders, Account, and Sign out,
  on desktop and on phones alike. Sign out must be reachable in two taps from any page,
  and the account page has a plain "Sign out" button as well. A nav item that only looks
  like a link (a `div` with no `onClick` or `Link`) is a bug; use `Link` or `button`.
- Footer: business name, contact, hours or address, and the same links. Real details from
  the spec, no lorem ipsum, no "Copyright 2024".

## Copy
- Headlines say what the business does for the customer, in plain words. No "Welcome to".
- Prices show the currency the spec uses, formatted (₦12,000, not 12000).
- Nigerian context when the spec is Nigerian: naira, WhatsApp as a contact channel, local
  place names, phone formats like 0803 123 4567.

## Before you finish a page
Check, in this order: phone width first (does anything overflow or wrap badly?), then
desktop; heading hierarchy; consistent spacing; every image has an aspect ratio and its
file exists in public/uploads (a card showing alt text is a bug); primary action visible
without scrolling on the home page; nothing says placeholder or TODO.
