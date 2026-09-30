# Scene flow: every scene hands something to the next

A launch video should feel like **one camera moving through one product**, not a slideshow. **Every scene boundary gets a continuity device.** Most boundaries **carry something across**: an element from scene A becomes, or stays in, scene B.

The cut techniques below (cut the curve, zoom-through, inverse zoom, waterfall) are adapted from the `product-launch-video` skill's cut catalog in the Hyperframes repository (Apache-2.0). The cross-scene morph and carry patterns are ours.

**The rule** (checked by `verify-composition.mjs`):
- Every scene root has `data-scene="<n>"`.
- Every boundary n→n+1 has an element tagged `data-flow="<device> <n>-<n+1>"`.
- At least **one boundary is a cross-scene morph**.
- At least **one is a carry**.
- No boundary is a plain cut or crossfade.

---

## The devices

| Device | `data-flow` | What happens | Use it for |
|---|---|---|---|
| **Cross-scene morph** | `morph` | an element from scene A **changes shape into** an element of scene B, which lands and becomes part of B | the strongest link. The story moves because the thing itself transforms. |
| **Carry** | `carry` | one element **stays on screen across the cut** and keeps moving (the cursor, the device frame, a headline bar, the product mark, a colour field), while everything else changes around it | modules of one product; keeping the viewer oriented |
| **Cut the curve** | `curve` | A's hero accelerates in one direction (`power4.in`); the cut lands mid-motion; B's hero continues **the same direction** and decelerates (`power4.out`); same distance and duration | the default between sibling scenes |
| **Zoom-through** | `zoom` | A scales toward the viewer (1 → 1.2, blur 0 → 10px text / 20px surfaces, `power3.in`, 0.2 s). Hard swap at peak blur. B continues from 0.75 → 1 (`expo.out`, 0.5 s) | a **state change**: hook → product, chapter → chapter |
| **Inverse zoom** | `inverse` | A recedes (1 → 0.8), B arrives oversized (1.25 → 1) | **arrival** beats: the payoff, the final name |
| **Waterfall** | `waterfall` | per word: out on `x: 0 → −230` with `power4.in`, ~0.022 s apart; in from `+230` with `power4.out`, and the gaps shrink ×0.84 per word | text-to-text: one headline becoming the next |

**One principle underneath all of them:** cut at peak velocity, and match the direction and speed on both sides. Never show two texts at once in a zoom, never move full off-screen (partial travel plus a fade), and don't leave dead air: the last fading element dies right at the cut.

---

## Cross-scene morphs: the catalogue

Choose one that turns **something the viewer just watched** into **what the next scene is about**:

| From (scene A) | To (scene B) | How |
|---|---|---|
| The CTA the user pressed | the next screen's header or card | FLIP: measure both boxes; animate the button's `x`, `y`, `scaleX/Y`, `borderRadius` and `backgroundColor` into the target box (0.55–0.7 s, `power3.inOut`); crossfade only the *contents* in the last 30%; then swap in the real element |
| A card in a list | the full detail screen | the card grows into the screen frame (container morph); the detail content staggers in inside it |
| The product name or logo mark (the hook) | the app icon, or the app's top bar | MorphSVG from the logo path to the icon path, or a FLIP of the wordmark into the nav logo |
| A chat bubble or prompt | the generated result (a card, a UI, a chart) | the bubble's box expands into the result's frame; the text breaks into its parts |
| A number or stat | a chart bar or progress ring | the digits' box collapses into the bar's origin, and the bar grows from it |
| A module headline pill | the next module's frame | the pill stretches (scaleX then scaleY) into the frame of the next screen |
| A map pin, avatar or icon | a circle reveal of the next scene | the icon scales to cover the frame (`clipPath: circle()` centred on it) |
| A tick or success state | the final lockup | the tick's circle grows into the brand-colour field of the end card |

**Build pattern** (seek-safe; measured at build time):

```js
// Morph element `a` (scene A) into the box of `b` (scene B), then hand over to `b`.
function morphAcross(tl, a, b, at, o = {}) {
  const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(), k = o.stageScale ?? 1;
  const dx = (rb.left + rb.width / 2 - (ra.left + ra.width / 2)) / k;
  const dy = (rb.top + rb.height / 2 - (ra.top + ra.height / 2)) / k;
  const dur = o.dur ?? 0.65;
  tl.set(a, { zIndex: 30, transformOrigin: "50% 50%" }, at);
  tl.to(a, { x: dx, y: dy, scaleX: rb.width / ra.width, scaleY: rb.height / ra.height,
             borderRadius: o.radius ?? getComputedStyle(b).borderRadius,
             backgroundColor: o.bg ?? getComputedStyle(b).backgroundColor,
             duration: dur, ease: "power3.inOut" }, at);
  if (o.contentOut) tl.to(o.contentOut, { opacity: 0, duration: dur * 0.3 }, at);        // A's label fades early
  tl.set(b, { autoAlpha: 1 }, at + dur);                                                // B takes over exactly where A landed
  tl.set(a, { autoAlpha: 0 }, at + dur);
  if (o.contentIn) tl.fromTo(o.contentIn, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.35, ease: "power2.out", immediateRender: false }, at + dur - 0.1);
  return at + dur;
}
```

- **Both scenes exist in the DOM together.** Scene B's layer is under A, hidden until the handover, with `b` pre-set to `autoAlpha: 0`.
- **Scene B's other elements enter while `a` is still travelling,** from about 60% of the morph on, so the new scene assembles around the morphing element.
- **Measure `b` in its final layout.** Don't measure it inside a transformed (tilted or zoomed) parent unless you account for that transform.
- **Sound:** a `toneSweep` glide between two scale notes across the morph, and a soft `thud` or `pop` on the handover.

---

## Carry patterns

- **The device frame stays; the screen content swaps.** Use this for several screens of one app. The frame can drift or tilt continuously across the cut, and only the content inside cuts, using cut the curve.
- **The cursor stays.** It keeps its position, or keeps moving, while the UI changes under it. That reads as the same user.
- **Headline bar:** the module-headline band stays in place, and its text waterfalls to the next headline.
- **Product mark:** a small logo in the corner persists from the hook to the end card, then grows into the final lockup (a morph).
- **Colour field / light:** a brand-colour blob or glow moves continuously across boundaries, like a light passing through the scenes.
- **Camera move through a world:** lay the scenes side by side, or in depth, on one canvas, and move the camera through it (`hyperframes-animation/rules/3d-camera-flight.md`, `viewport-change.md`). Every boundary becomes a carry.

---

## Planning the flow

`brag-plan.md` gets a **Scene flow** table. Fill it in before building:

```
| Boundary | Device | What carries / morphs | Direction & speed | Sound |
|---|---|---|---|---|
| 1→2 hook → module 1 | morph | "Ark" wordmark → the app's top-bar logo | up, 0.65 s | tone glide + thud |
| 2→3 module 1 → 2 | carry + curve | device frame stays, content cuts left | left, 0.3 s | whoosh L |
| 3→4 module 2 → payoff | morph | "Confirm" button → the "Trade confirmed" card | — | glide + success |
| 4→5 payoff → end | inverse | the card recedes, the name lockup arrives oversized | Z | impact |
```

Vary the devices. Don't use the same one at every boundary, apart from cut the curve as the default between siblings.

---

## Checks

- [ ] Every `data-scene` boundary has a `data-flow` element, and none is a plain cut or crossfade.
- [ ] There is at least one cross-scene morph and at least one carry.
- [ ] Stills at the cut −2 / 0 / +2 frames show one continuous motion: the same direction, no double exposure, no empty frame.
- [ ] The morph's handover frame looks identical before and after the swap (same box, colour and radius).
