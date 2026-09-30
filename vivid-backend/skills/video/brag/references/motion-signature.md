# Motion signature: the moves every brag video must have

Earlier runs chose effects by tone, and every tone ended up choosing "almost none". The result looked like a flat screen recording. From now on **every video uses all the signature moves below**. **Tilt means at least two perspective shots:** one of them is held at an angle of **20° or more** for over a second (`tiltGlide`) on an object **scaled below the frame** (0.6–0.8), so its edges and corners are visible. A full-bleed screen tilted a few degrees reads as flat. See `depth-and-interaction.md` §4. The tone changes only how strong they are, never whether they appear.

| Move | What the viewer sees | Tag the moving element |
|---|---|---|
| **1. Pop-out** | a real control (the CTA, a price, a toast, a card) lifts out of the screen toward the camera, glows or casts a big shadow, is pressed, and settles back | `data-fx="pop-out"` |
| **2. Tilt** | a screen or device is angled in 3D (perspective) and settles flat, or glides at an angle during a showcase | `data-fx="tilt"` |
| **3. Shape morph** | one shape becomes another: a button → a tick, a card → the next screen, a circle opening the next scene, the logo mark → the app icon | `data-fx="morph"` |
| **4. Scene flow** | every scene boundary is joined: a cross-scene morph, a carry, cut the curve, zoom-through, inverse zoom or waterfall (`scene-flow.md`); at least one morph and one carry | `data-scene` on roots, `data-flow="<device> a-b"` |
| **5. Skew** | a moving layer leans ≥5° in its direction of travel and straightens as it lands | `data-fx="skew"` |

The following extras are recommended (at least one, except in deadpan/parody): `glow`, `glass`, `skew`, `stagger-pop`, `exploded`.

Also tag the frame-0 product name `data-fx="name-open"` and the final lockup `data-fx="name-close"`. `scripts/verify-composition.mjs` checks every tag *and* that the script really animates it. The render doesn't start until it passes.

**Intensity by tone:**

| Tone | Pop-out | Tilt | Morph | Cut |
|---|---|---|---|---|
| `chaotic` | z 200, scale 1.25, rotate ±8°, spring overshoot | 25–35°, fast (0.5 s), with skew | slam morphs (0.3 s), clip-path bursts | whip + skew + motion blur, on the beat |
| `default`, `app-store` | z 120, scale 1.12, back.out(1.6) | 15–22°, settle over 0.9 s | button → tick, card → screen | velocity-matched slides |
| `polished`, `cinematic` | z 80, scale 1.08, slow (0.6 s), a big soft shadow | 10–18°, slow glide with drift | container morphs, circle reveals | match cuts, zoom-through |
| `deadpan`, `yc-parody` | z 50, scale 1.05, no bounce | 8–12°, one settle | a single clean morph | one match cut |

All recipes are seek-safe: tweens sit on the one paused timeline at explicit times, and transforms end at a clean state. Pair each move with its sound from `sound-design.md` §5.

---

## Stage setup for 3D

Perspective lives on a **parent**, and 3D children need `transform-style: preserve-3d` all the way down:

```html
<div id="stage3d" style="position:absolute;inset:0;perspective:1800px;perspective-origin:50% 45%">
  <div id="screen" data-fx="tilt" style="position:absolute;left:280px;top:120px;width:1360px;height:840px;transform-style:preserve-3d;border-radius:28px;overflow:visible">
    <div class="ui">… the real app UI …</div>
    <div class="dim" style="position:absolute;inset:0;background:#000;opacity:0;border-radius:28px;pointer-events:none"></div>
    <button id="cta" data-fx="pop-out" style="position:absolute;…">Place order</button>
  </div>
</div>
```

Put `overflow:visible` on the screen while something pops out. `overflow:hidden` flattens 3D children. Clip the UI inside `.ui` instead.

---

## 1. Pop-out

```js
// Lift el out of its screen at `at`, hold, optionally press, settle back. Returns when it's back.
function popOut(tl, el, at, o = {}) {
  const z = o.z ?? 120, s = o.scale ?? 1.12, hold = o.hold ?? 1.0;
  const lift = { z, scale: s, rotationX: o.rx ?? -6, rotationY: o.ry ?? 4,
                 boxShadow: o.shadow ?? "0 40px 90px rgba(0,0,0,.35), 0 0 0 1px rgba(255,255,255,.08)" };
  tl.set(el, { transformStyle: "preserve-3d", zIndex: 5 }, at);
  tl.to(el, { ...lift, duration: o.dur ?? 0.45, ease: o.ease ?? "back.out(1.6)" }, at);
  if (o.dim) tl.to(o.dim, { opacity: 0.35, duration: 0.35, ease: "power2.out" }, at);          // the rest of the screen recedes
  if (o.glow) tl.fromTo(o.glow, { opacity: 0, scale: 0.8 }, { opacity: 0.45, scale: 1.1, duration: 0.5, ease: "power2.out", immediateRender: false }, at + 0.1);
  let t = at + (o.dur ?? 0.45) + hold;
  if (o.press) {                       // pressed while lifted: dips toward the screen, springs back
    tl.to(el, { z: z * 0.55, scale: s * 0.96, duration: 0.08, ease: "power2.out" }, t - 0.35);
    tl.to(el, { z, scale: s, duration: 0.25, ease: "back.out(2.2)" }, t - 0.27);
  }
  tl.to(el, { z: 0, scale: 1, rotationX: 0, rotationY: 0, boxShadow: o.rest ?? "0 2px 6px rgba(0,0,0,.12)", duration: 0.5, ease: "power3.inOut" }, t);
  if (o.dim) tl.to(o.dim, { opacity: 0, duration: 0.4 }, t);
  if (o.glow) tl.to(o.glow, { opacity: 0, duration: 0.4 }, t);
  return t + 0.5;
}
```

**How to use it:**
- **Pop the one control the feature is about:** the CTA before it is clicked, the price in a checkout, the "Trade confirmed" toast, the new chat message.
- **Pair it with a camera push-in** (`ui-demo-motion.md` §4), so the lift reads on a phone screen.
- **Sound:** a whoosh 'in' as it rises, then a tuned pop as it reaches full size. If it is pressed while lifted, a click + blip.

**Variants:**
- **Card lift:** a whole card rises with `rotationX: -10`. Its neighbours dim and blur 2px.
- **Toast pop:** the toast arrives already lifted (from `z: 200, opacity: 0`) and settles into place.
- **Price pop:** the number pops, then counts up while lifted.

---

## 2. Tilt (perspective)

```js
// Screen arrives angled and settles flat, ready to read.
function tiltIn(tl, el, at, o = {}) {
  tl.fromTo(el, { rotationY: o.ry ?? -20, rotationX: o.rx ?? 10, z: o.z ?? -220, opacity: 0, transformOrigin: "50% 60%" },
               { rotationY: 0, rotationX: 0, z: 0, opacity: 1, duration: o.dur ?? 0.95, ease: o.ease ?? "power3.out", immediateRender: false }, at);
  return at + (o.dur ?? 0.95);
}
// Showcase glide: hold an angle while drifting, then flatten before reading.
function tiltGlide(tl, el, at, dur, o = {}) {
  tl.fromTo(el, { rotationY: o.from ?? -14, rotationX: 6 }, { rotationY: o.to ?? -6, rotationX: 3, duration: dur, ease: "sine.inOut", immediateRender: false }, at);
  tl.to(el, { rotationY: 0, rotationX: 0, duration: 0.6, ease: "power3.inOut" }, at + dur);
  return at + dur + 0.6;
}
```

**More ways to use it:**
- **Split-tilt pairs** for comparing (before/after, customer/admin): see `hyperframes-animation/rules/split-tilt-cards.md`.
- **A whole landing or dashboard as a tilted, scrolling 3D page:** `rules/3d-page-scroll.md`.
- **Readability:** past ~15°, text is hard to read. Flatten before the dwell.

---

## 3. Shape morph

Pick the version that shows the change the feature makes:

| Story | Morph |
|---|---|
| submit → done | **button → tick**: the button's shape collapses to a circle (scale + `borderRadius: "50%"` in one tween, the label fades), then the icon path morphs into a check (`morphSVG`) |
| open a detail | **card → screen**: the tapped card's box grows into the next screen (FLIP: measure both, animate `x`, `y`, `scale`, `borderRadius`) |
| next scene from a tap | **circle reveal**: `clipPath: circle(0 → 150% at tap)` |
| brand ↔ product | **logo → icon**: the logo mark's path morphs into the app's main icon (both from real SVGs) |
| state change | **pill → panel**: a status pill expands into the panel that explains it |

Button → tick, fully:

```js
function buttonToTick(tl, btn, label, icon, tick, at, o = {}) {
  const size = o.size ?? 72;                        // final circle size in px
  const r = btn.getBoundingClientRect();
  tl.to(label, { opacity: 0, duration: 0.15 }, at);
  tl.to(btn, { scaleX: size / r.width, scaleY: size / r.height, borderRadius: "50%",
               backgroundColor: o.done ?? "#16a34a", duration: 0.45, ease: "power3.inOut" }, at);
  // keep the icon undistorted: counter-scale it inside the button
  tl.to(icon, { scaleX: r.width / size, scaleY: r.height / size, duration: 0.45, ease: "power3.inOut" }, at);
  tl.to(icon.querySelector("path"), { morphSVG: tick, duration: 0.4, ease: "power2.inOut" }, at + 0.3);
  tl.fromTo(btn, { boxShadow: "0 0 0 0 rgba(22,163,74,.5)" }, { boxShadow: "0 0 0 18px rgba(22,163,74,0)", duration: 0.6, ease: "power2.out", immediateRender: false }, at + 0.7);
  return at + 1.0;
}
```

Load MorphSVG with `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/MorphSVGPlugin.min.js"></script>` and `gsap.registerPlugin(MorphSVGPlugin)`. More detail: `effects.md` §1, `hyperframes-animation/rules/card-morph-anchor.md`, `scale-swap-transition.md`. Check a still at the midpoint of every morph.

---

## 4. Scene flow

See `scene-flow.md`. Every boundary gets a device. The strongest is a **cross-scene morph**: something the viewer just watched changes shape into what the next scene is about. `examples/trimly/` has a wordmark → brand mark morph (1→2) and a carried brand mark that grows into the final name (2→3).

---

## Extras

**Stagger pop** (`data-fx="stagger-pop"`): cards, chips or rows spring in one after another. Tune one pop sound per item, rising in pitch:

```js
function staggerPop(tl, items, at, o = {}) {
  const gap = o.stagger ?? 0.07;
  items.forEach((el, i) => tl.fromTo(el, { scale: 0.6, opacity: 0, y: 24 },
    { scale: 1, opacity: 1, y: 0, duration: 0.5, ease: o.ease ?? "back.out(1.7)", immediateRender: false }, at + i * gap));
  return at + (items.length - 1) * gap + 0.5;
}
```

**Exploded view** (`data-fx="exploded"`): a tilted screen separates into its layers (background, panels, cards, the CTA) along z, holds, then reassembles. It's a strong "look how it's built" beat for dev tools and builders:

```js
function explode(tl, layers, at, o = {}) {   // layers: back → front
  const gap = o.gap ?? 90, hold = o.hold ?? 1.2;
  layers.forEach((el, i) => tl.to(el, { z: i * gap, duration: 0.7, ease: "power3.out" }, at + i * 0.04));
  layers.forEach((el) => tl.to(el, { z: 0, duration: 0.6, ease: "power3.inOut" }, at + 0.7 + hold));
  return at + 1.3 + hold;
}
```

Use it on a screen that is already tilted (`rotationY` −25°, `rotationX` 15°), or the separation can't be seen.

**Glow, glass and skew:** see `effects.md` §2–4.

---

## Gotchas (from test renders)

- **Pre-set everything that enters later.** A `fromTo` with `immediateRender: false` leaves the element visible at rest *before* its tween starts. Headlines and cards then flash on, vanish and animate in. `gsap.set(el, { opacity: 0 })` every entering element at build time.
- **A morphing element must be above the incoming scene.** Give the outgoing scene (or the travelling element) a higher `z-index` while it hands over, or the new scene covers it mid-morph.
- **No negative `z` on children of a `preserve-3d` surface.** They go behind it and disappear. Wind up with `y` and `scale` instead.
- **Hide what a reveal covered.** After a circle or clip reveal or a zoom-through finishes, set the covered scene to `autoAlpha: 0`. Otherwise `hyperframes check` reports `text_occluded` for every line underneath.
- **Keep the dim overlay of a pop-out at 0.35 opacity or less, and short.** The check flags the dimmed text's contrast while it's dimmed. That's expected during the lift, but not during a dwell.
- **A morph's midpoint is visible for several frames.** Counter-scale icons inside a scaled button (`buttonToTick` does this), or they stretch.

## Checks

- [ ] `node <skill-dir>/scripts/verify-composition.mjs <output-dir>/composition --tone <tone>` passes.
- [ ] Stills at the peak of the pop-out, the tilt midpoint, the morph midpoint, and cut −2/0/+2 frames look intentional. There's no clipping of 3D children by `overflow:hidden`, and no warped final state.
- [ ] Each signature move has its sound on the same cue.
