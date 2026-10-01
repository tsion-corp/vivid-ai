# Step 1: Inspect the project

Read the project directory to understand what you're bragging about.

## What to look for: the whole product, not the landing page

The landing page is the product describing itself; the code is the product. A brag that
only restages the landing page shows what every competitor's video shows. Read enough of
the codebase to know **everything the product does**, then choose what to show. Skim
widely; read deeply only what could end up on screen.

### 1. Map the project

- List the source tree. Skip `node_modules/`, `dist/`, `build/`, `.next/`, lock files and tests.
- Note the stack: web (Vite, Next) or mobile (Expo, React Native); the router; the backend
  (Supabase migrations, API routes, edge functions, server code); integrations.
- Find the router and **list every route or screen with its component**: `src/App.tsx`
  `<Route>`s, `app/` or `pages/` directories, Expo `app/(tabs)/`, navigation stacks.

### 2. Walk every screen

Open each route's component and write one line per screen:
- what the person can do there,
- the video-worthy UI on it (a form, a live list, a map, a chart, an editor, a checkout,
  a status timeline, a dashboard),
- real copy from it (headings, button labels, empty states, success messages).

Group the screens by area and by who uses them: the public site, the signed-in app, the
owner's admin or dashboard, settings, and any other roles (riders, staff, vendors).

### 3. Find what the product actually does

- **Data model.** Migrations, schemas, types and seed files give the nouns (orders,
  bookings, riders, invoices) and their states (`booked → in_transit → delivered`). A state
  moving from one value to the next is a great video beat.
- **Logic.** Stores, hooks, services, API calls, edge functions: calculations (pricing,
  ETAs, matching, scoring), integrations (payments, maps, sign-in, AI, notifications,
  realtime), and anything clever or unusual.
- **Demo data.** Seed and fixture files give realistic names, amounts and places to fill
  the video's UI. Use them; never real customer data.
- **Voice.** The README, docs and the landing page: the product's own claims and tone. Use
  them for copy, and check each claim against the code before repeating it.
- **Assets.** `public/`, `assets/` and uploads: the logo, icons, product images.
- **Mobile layout.** How each highlight screen looks at phone width in the code: its responsive classes (un-prefixed vs `md:`), media queries, mobile-only components (bottom tabs, drawer, sheets), and what collapses (sidebar, split panes, tables). Vertical and square videos are built from this (`formats.md`).
- **Icons.** Find the icon set the app really uses: the package (`lucide-react`,
  `@heroicons/react`, `react-icons`, `@expo/vector-icons`, `@phosphor-icons/react`...),
  inline `<svg>` components, and SVG files. For each highlight screen, note the icons
  it shows by name (`Truck`, `CalendarCheck`...). The video draws these, never
  placeholder boxes.

### 4. Write `<output-dir>/feature-map.md`

```markdown
# Feature map: [App]

## Stack
[framework, router, backend, integrations — one line each]

## Screens (by area)
### [Area, e.g. Customer app]
- [route] · [component file] · [what you do there] · [video-worthy UI]

## Features
| Feature | Where in the code | What it does for the user | How it shows on screen | Wow (1-5) | Distinctive? |
|---|---|---|---|---|---|

## Flows
- [Who, e.g. customer]: [entry] → [key action] → [result]
- [Who, e.g. owner]: ...

## Real numbers and facts (from the code)
- [e.g. "12 Lagos delivery zones", "3 service tiers", "₦2,500 base fare"]

## Demo data to use
[names, amounts, places from seed files]

## Brand
[colors, fonts, logo and key visual file paths]

## Highlights (chosen)
1. [feature] — [screen/component to recreate] — [the moment on screen]
2. ...
```

List **every** feature you find. A real app usually has 8 to 20. Rate each one.

### 5. Choose the highlights

Pick **3 or 4 features** that are the most impressive **and** the most distinctive: the
ones a competitor's video could not show. Cover more than one area when the product has
them (the customer's live tracking map *and* the owner's dispatch board). Each highlight
must be showable from a real screen or component, with real copy and demo data.

The landing page may frame the video (the hook line, the outro) but is never a
highlight when the app has screens of its own. If the project really is a
landing-page-only site, say so in the feature map and use its strongest sections.

## The 9-question rubric

After reading, answer all nine. Write these down before moving to Step 2.

```
1. What is the app?
   One sentence. What does it actually do (or claim to do)?

2. What is the funniest or most impressive claim?
   The one line that earns a reaction: from the site, or a real fact from the
   code (a number, a capability) the site undersells.

3. What is the visual hook?
   The strongest CSS visual: a color palette moment, a UI element, a diagram, a card.

4. What should be shown from the actual UI?
   The 3-4 highlights chosen in feature-map.md, each with the screen or
   component it comes from (file path) and the moment it shows.

5. What is the shortest satisfying video?
   About 4 seconds per highlight, plus a hook and an outro: 3 highlights
   land in 18-22 seconds, 4 in up to 30.

6. What tone fits best?
   If the user specified a preset, use it.
   If the user gave freeform direction, preserve it and map it to the nearest preset.
   If the user did not specify, infer both:
   - Tone preset: one of the known presets
   - Creative direction: a short custom phrase for this project
   Examples:
   - Absurd product → preset: yc-parody; direction: fake startup launch
   - Earnest product → preset: polished; direction: quiet premium product film
   - Chaotic product → preset: chaotic; direction: overproduced social ad

7. What should the audio feel like?
   Decide the audio role and music direction before picking exact SFX files.
   Bias toward a polished audio layer: include music and tasteful SFX unless
   the user disabled them, assets are missing, or silence is clearly the
   strongest creative choice.
   Examples:
   - Warm corporate bed; SFX chosen later to match real UI motion
   - Low music bed with final fade; one dry logo hit if the composition supports it
   - Dense chaotic music; Hyperframes may align text/card reveals to beats
   - Cinematic bed with a low swell, restrained motion-matched accents, and subtle audio-reactive glow/presence if it supports the visual style
   Choose it for **this** app: its category and its audience (see `audio.md` →
   "Sound for the app"). A banking app and a party-games app must not sound alike.

8. What should the share caption say?
   Draft one sentence. This becomes share-copy.txt.

9. What's the user flow worth showing?
   The 2–3 beats a real user goes through: entry → key action → result.
   Not the landing page's section list — the working app.
   Examples:
   - Upload long video → see it processing with progress → see 3 vertical clips ready
   - Type a message → assistant types back → user clicks "mark resolved"
   - Swipe right on Thunder's profile → match animation → chat opens
   If the project is a landing-page-only static site with no app, write
   "none — landing-page only" and rely on the strongest visual (Q3) instead.
```

## Color extraction

When reading CSS, look for custom properties like:

```css
:root {
  --primary: oklch(...);
  --bg: oklch(...);
  --accent: ...;
}
```

If no custom properties exist, scan for the most-used colors in background, color, and border rules.

Write down:
- Background color (exact value)
- Primary text color
- Accent/brand color
- Any gradient or special treatment

These colors are recorded in `composition-brief.md` and carry into the design spec the current hyperframes-creative workflow scaffolds.

## Font extraction

Look for:
- `font-family` declarations in `:root` or `body`
- Google Fonts `<link>` in `<head>` (the font families are in the URL query string)
- `@import` statements

Write down the display font (used for headings) and the body font separately.

## What to skip

Don't read:
- Generated build artifacts (`dist/`, `.next/`, `build/`)
- Lock files (`package-lock.json`, `yarn.lock`)
- Test files
- `.git/`
- Environment and secret files (`.env`, `.env.*`)
- Credential and key material (`.pem`, `.key`, `id_rsa`, service-account JSON, anything under a `secrets/` or `credentials/` directory)
- Local config that commonly holds tokens
- Any file the project's `.gitignore` excludes for the reasons above

## Rule: nothing secret leaves this step

Everything read in this step can end up on screen in a video the user posts publicly. Never carry secrets, API keys, tokens, internal hostnames or URLs, real customer or user names, email addresses, or any personal data into `brag-plan.md`, `composition-brief.md`, the composition, the rendered video, or share copy. If the product's real UI contains such data, substitute plausible fictional stand-ins and say so in the plan.

