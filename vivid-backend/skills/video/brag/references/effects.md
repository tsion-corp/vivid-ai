# Effects: morph, glow, glass, skew and perspective, continuous cuts

Five finishing effects that make a launch video feel produced. Each section says **when** to use the effect, gives a seek-safe recipe for a Hyperframes composition, and names the `hyperframes-animation` rule to read for depth.

**Required vs. optional.** The four signature moves (pop-out, tilt, morph, continuous cut) are **required in every video**: see `motion-signature.md`. Glow, glass and skew are extras, chosen by tone:

| Tone | Good fits |
|---|---|
| `polished`, `app-store` | glass panels, soft glow, gentle perspective settle, match cuts |
| `cinematic` | glow bloom, deep perspective, zoom-through cuts |
| `default` | shape morph (button → check), continuous cuts, light tilt |
| `chaotic` | skew on whips, hard glow, morph slams |
| `deadpan`, `yc-parody` | almost none: one match cut at most |

All effects follow the Hyperframes contract:
- Tween on the one paused timeline, at explicit times.
- Animate size with `scale`, never `width` or `height`.
- Use no timers or randomness.
- Land in a clean final state: flat, sharp and readable.

---

## 1. Shape morphing

One shape becomes another, so the eye follows a single object through a change.

**When:**
- A button becomes a success tick.
- The logo mark becomes the app icon.
- A card grows into the full screen.
- A circle opens into the next scene.
- A chart bar becomes the number it stands for.

**A. SVG path morph** (icons, logo marks, blobs). GSAP's MorphSVG plugin is free:

```html
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/MorphSVGPlugin.min.js"></script>
<svg viewBox="0 0 48 48"><path id="shape" d="...send icon path..."/><path id="tick" d="...check path..." style="visibility:hidden"/></svg>
<script>
  gsap.registerPlugin(MorphSVGPlugin);
  tl.to("#shape", { morphSVG: "#tick", duration: 0.5, ease: "power3.inOut" }, t);
</script>
```

Take both paths from the app's own icon set (see the icon rule). With very different shapes, add `shapeIndex: "auto"`, and check a still at the midpoint.

**B. Container morph** (a card → a screen, a pill → a panel). Animate `scale`, `x`/`y` and `borderRadius` in **one** tween. Fade the old content out during the first 40% and the new content in during the last 40%. See `hyperframes-animation/rules/card-morph-anchor.md`.

**C. Clip-path reveal** (a circle opens into the next scene from the tap point):

```js
tl.fromTo("#next", { clipPath: `circle(0px at ${p.x}px ${p.y}px)` },
                   { clipPath: `circle(150% at ${p.x}px ${p.y}px)`, duration: 0.7, ease: "power3.inOut", immediateRender: false }, t);
```

When morphing `polygon()` clip-paths, both polygons need the same number of points.

---

## 2. Glow

Glow gives a hero element presence, as if it had just powered on.

**When:**
- The product name at frame 0 and at the end.
- The key number.
- The button just pressed.
- The payoff state (a green glow when an error is fixed).
- A dark UI.

**Recipes:**

```css
/* text glow: two layers, a tight core and a wide halo */
.glow-text { text-shadow: 0 0 8px rgb(var(--accent) / .55), 0 0 32px rgb(var(--accent) / .35); }
/* element glow that follows the shape (icons, logos, cut-outs) */
.glow-shape { filter: drop-shadow(0 0 10px rgb(var(--accent) / .5)) drop-shadow(0 0 28px rgb(var(--accent) / .3)); }
/* bloom behind a card: its own layer so it can scale */
.bloom { position:absolute; inset:-20%; background: radial-gradient(closest-side, rgb(var(--accent) / .45), transparent); z-index:0; opacity:0; }
```

```js
// bloom lands on the hero's settle; then a bounded breathe
tl.fromTo(".bloom", { opacity: 0, scale: 0.8 }, { opacity: 0.4, scale: 1, duration: 0.6, ease: "power2.out" }, heroSettle - 0.6);
tl.to(".bloom", { opacity: 0.3, scale: 1.04, duration: 1.2, ease: "sine.inOut" }, heroSettle);
```

**Rules:**
- **Peak opacity at most 0.45.**
- **Make the glow colour a darker, more saturated version of the accent,** or it disappears on light UIs.
- **Put the glow behind the element,** never on top of it.
- **Use one glow at a time.**
- **The traveling sweep** (a highlight crossing a card once) is in `rules/ambient-glow-bloom.md`.

---

## 3. Glass

Frosted, translucent panels layered over colour.

**When:**
- A feature callout floating over the real UI.
- Stat chips.
- The frame for the module headline.
- The end card.

It also fits apps whose own UI already uses glass.

**Glass needs colour behind it.** On a flat background it just looks grey. Put the app's screen, or slow-moving gradient blobs in the brand colours, behind it.

```css
.glass {
  background: linear-gradient(135deg, rgb(255 255 255 / .18), rgb(255 255 255 / .06));
  backdrop-filter: blur(22px) saturate(160%);
  -webkit-backdrop-filter: blur(22px) saturate(160%);
  border: 1px solid rgb(255 255 255 / .28);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / .35), 0 20px 50px rgb(0 0 0 / .18);
  border-radius: 24px;
}
/* dark UIs: rgb(20 20 28 / .45) base and a rgb(255 255 255 / .12) border */
```

- **Animate the panel's `opacity`, `y` and `scale`,** not the blur amount. Tweening `backdrop-filter` is slow and flickers.
- **Keep it to two or three glass panels on screen,** because each one costs render time.
- **Add a sheen:** a narrow white gradient crossing the panel once, clipped by `overflow:hidden`, to sell the glass.
- **Text on glass needs contrast.** The panel's tint must keep it at WCAG AA (`hyperframes check` tests this).

---

## 4. Skew and perspective

Depth and speed, without any 3D engine.

**When:**
- A device or screen arrives tilted, then settles flat.
- Cards fan out in space.
- A fast pan needs to feel fast.

**Perspective settle.** The screen arrives angled and lands flat, ready to be read:

```js
gsap.set("#stage3d", { perspective: 1600 });              // on the PARENT
gsap.set("#device", { transformStyle: "preserve-3d", transformOrigin: "50% 60%" });
tl.fromTo("#device", { rotationY: -22, rotationX: 10, z: -200, opacity: 0 },
                     { rotationY: 0, rotationX: 0, z: 0, opacity: 1, duration: 1.0, ease: "power3.out" }, t);
```

**Hold a tilt for showcase shots.** Keep it at `rotationY` ±8–14° and `rotationX` 4–8° while a slow drift plays, then go flat before the viewer needs to read the text. Anything past ~15° makes text hard to read.

**Skew for speed.** On a whip pan, lean the moving layer in the direction of travel, and straighten it as it lands:

```js
tl.to("#strip", { x: -1920, duration: 0.45, ease: "expo.inOut" }, t);
tl.to("#strip", { skewX: -8, duration: 0.2, ease: "power2.in" }, t);
tl.to("#strip", { skewX: 0, duration: 0.25, ease: "power2.out" }, t + 0.2);
```

**Rules:**
- **Set `perspective` on the parent,** not the element.
- **Stay in 2D for Hyperframes' motion blur** (skew is fine).
- **Always end with skew at 0 and rotation at 0 on readable UI.**
- **Split-tilt cards and 3D fans** are in `rules/split-tilt-cards.md`, and depth layers in `rules/3d-text-depth-layers.md`.

---

## 5. Continuous (smooth) cuts

The cut is hidden inside a movement, so the video feels like one take.

**When:** between modules or scenes where a lateral slide alone feels flat. This is the stronger alternative to the transitions in `ui-demo-motion.md` §5.

**A. Velocity-matched cut.** The outgoing scene accelerates away (`.in` ease). The incoming scene arrives with the same speed and direction (`.out` ease), so speed peaks exactly at the cut and the eye doesn't see a join:

```js
// A leaves left, B arrives from the right; the cut happens at speed
function speedCut(tl, a, b, t, o = {}) {
  const d = o.distance ?? 1920, dur = o.duration ?? 0.35;
  tl.to(a, { x: -d * 0.5, duration: dur, ease: "expo.in" }, t - dur);
  tl.set(a, { autoAlpha: 0 }, t);
  tl.fromTo(b, { x: d * 0.5, autoAlpha: 1 }, { x: 0, duration: dur * 1.3, ease: "expo.out", immediateRender: false }, t);
  return t + dur * 1.3;
}
```

Add `data-hf-motion-blur` to `a` and `b` for the smear (see `references/motion-blur.md` in `hyperframes-animation`). If the move is vertical or diagonal, the same direction must continue after the cut.

**B. Match cut / shared element.** The thing the viewer is watching carries on: the tapped card becomes the next screen's header, or the logo becomes the app icon on the home screen. Measure both boxes, then move one element from the first box to the second (FLIP: `x`, `y`, `scale`, `borderRadius`) while the scenes change around it. See `rules/scale-swap-transition.md` and `card-morph-anchor.md`.

**C. Zoom-through.** Push into an element (the "Build" button, a map pin, a video thumbnail) until it fills the frame. Its colour or content becomes the next scene's background, and the next scene starts from that fill. Ease it `expo.in` into the fill and `expo.out` out of it.

**D. Wipe on an object.** A moving element that crosses the whole frame (a card, a panel, a big word) acts as the wipe edge: the scene changes behind it.

**Rules:**
- **Every continuous cut has one element or one direction the eye can hold across the cut.** Without one it's just a fast cut.
- **Use one or two per video.** The rest can use the simpler transitions.
- **Check the frames around the cut** (cut −2, cut, cut +2). There should be no black, no double exposure, and no frame where both scenes are half visible and static.

---

## Checks

- [ ] Each effect used has a job: presence, continuity, depth or context. There are no more than three effect types in one video.
- [ ] Morphs have a clean midpoint (check a still), and they start and end on the app's real shapes.
- [ ] Glow peaks at ≤0.45 behind the element, and there's one glow at a time.
- [ ] Glass sits over colour or UI (never a flat background), and text on it passes contrast.
- [ ] Tilted and skewed UI ends flat before anyone needs to read it.
- [ ] Continuous cuts match the direction and speed across the cut, with no black and no muddy frames.
