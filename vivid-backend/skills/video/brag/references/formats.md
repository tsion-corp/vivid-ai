# Formats: landscape, vertical, square

Each format shows the product **the way people see it on that screen**. A vertical video for TikTok, Instagram Reels, YouTube Shorts or WhatsApp Status is watched on a phone, so it shows the app's **mobile layout**: the one the code itself renders at phone width. **Never scale a desktop layout down to fit a tall frame.** That gives tiny text, a sidebar nobody uses on a phone, and a UI the viewer can't read.

| Format | Size | The app is shown as |
|---|---|---|
| `landscape` (X, LinkedIn, YouTube, websites) | 1920×1080 | the desktop layout. A mobile-first app appears in one or two phone frames. |
| `vertical` (TikTok, Reels, Shorts, Status) | 1080×1920 | **the mobile layout**, full-bleed or in a large phone frame |
| `square` (feeds) | 1080×1080 | **the mobile layout** in a phone frame, or one pane at tablet width (~600 css px) |

---

## 1. Find the mobile layout in the code (step 1)

Note in `feature-map.md` how each highlight screen looks at phone width:
- **Tailwind:** classes without a prefix are the mobile styles; `sm:` `md:` `lg:` add the desktop ones. `hidden md:flex` is desktop-only; `md:hidden` is mobile-only. Build the mobile screen from the un-prefixed classes plus whatever `md:hidden` shows.
- **CSS media queries:** `@media (max-width: 768px)` (or `min-width` blocks that the mobile styles sit outside of).
- **Mobile-only components:** a bottom tab bar, a hamburger or drawer menu (`MobileNav`, `Sheet`, `Drawer`), `useIsMobile` / `useMediaQuery` branches, a mobile header, a floating action button.
- **What collapses on a phone, and how:**
  - the sidebar becomes a hamburger or bottom tabs;
  - split panes (chat + preview, list + detail) become stacked screens or tabs;
  - modals become bottom sheets;
  - tables become cards;
  - multi-column grids become one or two columns;
  - hover states become taps.
- **Expo / React Native apps** are already mobile: use their screens as written.

If the code has no mobile layout at all (a desktop-only tool), say so in the plan. Then show it in landscape, or crop to one pane at a readable size. Never shrink the whole desktop.

---

## 2. Build screens at a phone viewport, then scale *up*

Lay each screen out at a real phone width, **390 css px** (iPhone 14/15; 360–430 is fine), with the app's mobile classes. Then enlarge that whole screen to fill the frame. It stays sharp because it's DOM, not a screenshot:

```html
<!-- vertical, full-bleed: 390 × 2.769 = 1080 -->
<div class="phone-screen" data-viewport="mobile"
     style="position:absolute;left:0;top:0;width:390px;height:693px;transform:scale(2.769);transform-origin:0 0">
  … the app's mobile layout: mobile header, content, bottom tab bar …
</div>

<!-- vertical, in a phone frame with room for headlines: 390 × 2.1 ≈ 820 px wide -->
<div class="device" style="position:absolute;left:130px;top:430px;width:820px;height:1690px;border-radius:110px;…">
  <div class="phone-screen" data-viewport="mobile" style="width:390px;height:804px;transform:scale(2.1);transform-origin:0 0">…</div>
</div>
```

- **Mark every app screen `data-viewport="mobile"`** in vertical and square videos. The gate checks that.
- **Full-bleed** suits the most immersive feel: the screen *is* the video, like a screen recording on a phone. **A phone frame** leaves room for headlines and is better for 3D tilts (its edges show).
- **Scale is ×2–3:** a 14px mobile label becomes 30–40px on screen, which is readable on a phone. If the text still looks small, push in further. Don't make the layout wider.
- **No element in a vertical composition may be wider than the frame (1080px).** A 1280–1440px desktop shell scaled down fails the gate.

---

## 3. Platform safe zones (vertical)

TikTok, Reels and Shorts cover parts of the frame with their own UI. Keep text and key UI out of them:
- **top ~220px:** status bar, tabs, the account name;
- **bottom ~420px:** the caption, the music line, comment and share prompts;
- **right ~160px:** the like, comment and share buttons.

Headlines go in the upper-middle (y ≈ 260–620). The hero UI moment goes in the centre third. The name and CTA at the end sit in the middle, not at the very bottom.

---

## 4. Motion in a tall frame

- **Moves follow the phone:**
  - scene changes and cuts the curve go **vertically** (swipe up = next);
  - a sheet rises from the bottom;
  - a list scrolls with momentum.
- **3D:** tilt with **rotateX** (the phone tipping back) more than rotateY. Orbit around a phone frame. Pop-outs lift UI out of the phone toward the camera.
- **Thumb interactions:** use a touch dot instead of a cursor (`ui-demo-motion.md` §3). Taps land where a thumb would reach: the bottom half, the tab bar.
- **Type:** headlines of 72–110px, 2–5 words per line, at most two lines.

---

## 5. Square

Use the mobile layout in a phone frame, centred, with the headline above it. Or use one pane at ~600 css px (tablet width), scaled ×1.6–1.8. Never shrink the desktop.

---

## Checks

- [ ] Vertical/square: every app screen is the code's mobile layout, built at 360–430 css px, scaled up, and tagged `data-viewport="mobile"`.
- [ ] Nothing in the composition is wider than the frame, and there's no desktop sidebar or desktop nav.
- [ ] Text and key UI sit inside the safe zones.
- [ ] Moves go vertical; taps are thumb taps.
