# Depth and interaction: spatial UI, immersive 3D, micro-interactions, anticipation, live data

Motion designers' notes on earlier brag videos: the UI felt flat, clicks didn't feel physical, values snapped, and moves started without warning. This reference fixes each one. Every recipe below is **seek-safe GSAP** on the one paused timeline, and was tested in a HyperFrames render.

HyperFrames renders by seeking the timeline, so React hooks, spring libraries, `requestAnimationFrame` and `setInterval` don't drive a render. Drive everything from tweens, including `onUpdate` on a tweened proxy object, which GSAP re-runs on every seek.

---

## 1. Anticipation: every big move winds up first

Before a major move, the element makes a small **opposite** motion. It pulls back and squashes slightly, then goes. Without it, moves look like they start by teleporting.

```js
// v = the real move, e.g. { x: -300 } or { y: -500 }. Returns the time the move ends.
function anticipate(tl, el, at, v, o = {}) {
  const wind = o.wind ?? 0.16, back = {};
  for (const k of ["x", "y"]) if (v[k] !== undefined) back[k] = -Math.sign(v[k]) * (o.amount ?? 14);
  tl.to(el, { ...back, scale: o.squash ?? 0.97, duration: wind, ease: "power2.out" }, at);
  tl.to(el, { ...v, scale: 1, duration: o.dur ?? 0.5, ease: o.ease ?? "power3.in" }, at + wind);
  return at + wind + (o.dur ?? 0.5);
}
```

**Where to use it** (plan at least four per video):
- **Button presses:** the control rises about 2 px, *then* dips. The cursor lifts slightly before the click.
- **Exits:** a card, modal or screen leaving the frame backs off 10–20 px first.
- **Pop-outs:** the element sinks a touch (`y: 3, scale: 0.97`) before lifting toward the camera. **Never wind up with a negative `z` inside a 3D (`preserve-3d`) parent**: it passes behind its own surface and vanishes for those frames.
- **Camera pushes and whips:** the camera eases back 2–3% before pushing in.
- **Slams:** a headline word rises and holds for a beat before it drops into place.

**Size and timing:** the wind-up is 10–20% of the move's distance, and takes 0.12–0.2 s. The move itself uses an `.in` or `.inOut` ease, and lands with an `.out` settle. Put a quiet `swish` or `tick` on the wind-up, and the real sound on the move.

---

## 2. Tactile micro-interactions: every input answers immediately

**Every visible interaction gets a state change on the same frame.** Pick the matching recipe:

| Interaction | Recipe |
|---|---|
| **Press** | `scale: 0.94` over 0.08 s (`power2.out`), then back to 1 over 0.3 s (`back.out(2.5)`). The shadow shrinks while pressed. Add the ripple from `ui-demo-motion.md` §3. |
| **Submit → busy state** | On the press frame, the label changes to the app's real busy copy ("Thinking…", "Placing…", "Sending…"). A spinner appears (a finite `rotation` tween), and the fill dims to the disabled style (`opacity: 0.85`, a darker fill). |
| **Busy → done** | The label swaps to the result ("Cash out", "Booked"). The colour tweens to the success colour over 0.25 s, with a small scale pop (1 → 1.04 → 1). |
| **Select (chips, numbers, seats, slots)** | Instant fill and text colour, a ring that pops out (`boxShadow 0 0 0 0` → `0 0 0 6px accent` → fades), and `scale: 1.06` → 1. For multi-select, use a 0.06 s stagger and a rising pop pitch. |
| **Hover / focus before a click** | A soft highlight sweeps across the control (a clipped gradient band `x: -100%` → `100%`, 0.4 s), or the focus ring fades in 0.15 s before the press. |
| **Toggle** | The knob slides with a slight overshoot (`back.out(1.8)`), and the track colour tweens. Add a `ui/switch*` or `blip` sound. |
| **Type into a field** | The focus ring appears first. The caret and characters follow (`ui-demo-motion.md` §1a). The send button enables (dim → full) when the text is complete. |
| **Icons** | Nudge them 2–3 px in their meaning's direction on the related action: an arrow → right, a bell swings ±12°, a heart scales 1.2. |

- **Use the app's own state names and colours:** its disabled class, its "Thinking…" copy, its success green. Read them from the code (`disabled:`, `aria-busy`, loading states).
- **A micro-interaction is 0.08–0.35 s.** It never delays the story, and it overlaps the next beat.

---

## 3. Spatial UI: layers in Z, modals over content

Treat the interface as physical layers, not a flat canvas. When a modal, sheet or result screen appears, **the content behind it recedes**:

```js
// content recedes: dim scrim + depth-of-field blur + pushed back in Z
tl.to("#scrim", { opacity: 0.55, duration: 0.4 }, at);             // a dark layer between the world and the modal
tl.to("#world", { filter: "blur(6px)", duration: 0.4 }, at);        // depth of field on everything behind
tl.to("#cam", { z: -120, duration: 0.6, ease: "power3.out" }, at);  // the world backs away from the viewer
// the modal rises in front: glass panel, tipped back in 3D, settling flat
tl.fromTo("#modal", { opacity: 0, y: 60, scale: 0.9, rotationX: 18, transformPerspective: 1200 },
  { opacity: 1, y: 0, scale: 1, rotationX: 0, duration: 0.6, ease: "back.out(1.4)", immediateRender: false }, at + 0.1);
```

- **Structure:** `#world` (perspective) > `#cam` (preserve-3d) > the layers. The scrim and the modal are *outside* `#world`, so they stay sharp. Give the modal glass (`effects.md` §3): `backdrop-filter: blur(22px) saturate(160%)`, a translucent gradient, a 1px light border and an inner highlight.
- **Use it for:** result states ("You won!", "Calculating the winner…"), pickers (a theme picker over the live preview), confirmations, and sheets rising over the app.
- **Exits reverse it with anticipation:** the modal backs off, then leaves. The blur and scrim clear, and the world comes forward.
- **Lower layers keep moving slightly** (the counter still ticking, the preview still updating) so the depth feels live.

---

## 4. Immersive 3D: a camera moving through the product

**3D only reads when you can see an object's edges.** A full-screen UI tilted 18° looks like a slightly skewed flat screen. That's what an earlier VividBuild run shipped, and it passed its tags while showing no 3D. For depth to be visible, all of these must hold:
- **The tilted object is smaller than the frame:** scale it to 0.6–0.8 so its whole silhouette (corners, edges, shadow) shows against a background. The background has its own depth cue: a gradient, a grid floor, or blurred shapes.
- **Real angles:** 25–35° on the hero shot (`rotationY`), with 8–15° of `rotationX`. Keep 12–18° only for gentle glides.
- **Strong perspective:** `perspective` of 900–1400px (lower is stronger), not 1800+.
- **Real separation in depth:** layers sit **150–350 px apart in z** (for example background −400, screen 0, phone +180, floating card +320). Separations of 40–90 px produce no visible parallax.
- **The camera moves while angled:** an orbit (rotateY sweeping 20° or more), a dolly or a crane, lasting 1.5–3 s. The parallax is only seen *during* movement. A tilt that settles in 0.8 s and flattens is not immersive.
- **Depth cues:** a soft contact shadow under the object, far layers blurred 3–6 px, and a floating element casting a bigger, softer shadow.

**Check a still at the peak of the move:** you should see at least two corners of the screen, a floor or background around it, and layers clearly offset from each other.

At least one scene is shot like a camera moving in real 3D, not a flat screen sliding in:

```js
// layers at different depths → parallax when the camera moves
gsap.set("#bg", { z: -400 }); gsap.set("#mainCard", { z: 0 }); gsap.set("#sideWidget", { z: 120 }); gsap.set("#logs", { z: 60 });
tl.fromTo("#cam", { rotationY: 18, rotationX: 10, z: -500 },   // start deep and angled
  { rotationY: -6, rotationX: 4, z: 0, duration: 2.2, ease: "power3.out" }, at);
tl.to("#cam", { rotationY: 0, rotationX: 0, duration: 1.2, ease: "power2.inOut" }, at + 2.2);   // flatten to read
```

- **Split the product into 3–5 depth layers:** a background grid or gradient far back, the main screen at 0, and widgets, toasts or stats nearer the camera. Moving the camera then gives real parallax.
- **Camera moves:**
  - a *fly-in* from deep and angled;
  - an *orbit* (rotateY sweeping ±15° around the hero);
  - a *dolly* past standing cards;
  - a *crane down* onto a screen, from above (rotateX 25° → 0).
  
  See `hyperframes-animation/rules/3d-camera-flight.md`, `orbit-3d-entry.md` and `depth-scatter-assemble.md`.
- **Readability:** hold the angles at 25° or less while moving, and flatten to 0–5° before any text must be read.
- **Blur the far layers** (2–6 px) for depth of field, and keep the focal layer sharp.
- This counts toward the tilt requirement. Tag the camera rig `data-fx="tilt immersive"`.

---

## 5. Live data: values interpolate, never snap

When a number changes, **one progress value drives everything that depends on it**: the number, the path, the marker and the colour. That keeps them locked together on every frame.

```js
// Crash multiplier + trajectory from ONE proxy. m(p) maps progress to the real value range.
const P = { p: 0 };
const m = (p) => 1 + (Math.pow(1.9, p * 3.2) - 1) * 0.33;              // 1.00x → ~3.06x, accelerating
const pt = (p) => [40 + p * (W - 90), H - 40 - ((m(p) - 1) / 2.06) * (H - 150)];
function draw() {
  label.textContent = m(P.p).toFixed(2) + "x";                           // tabular-nums on the label
  let d = ""; for (let i = 0; i <= 60; i++) { const [x, y] = pt((P.p * i) / 60); d += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1); }
  path.setAttribute("d", d); const [rx, ry] = pt(P.p); marker.setAttribute("cx", rx); marker.setAttribute("cy", ry);
}
draw(); tl.to(P, { p: 1, duration: 3, ease: "power1.in", onUpdate: draw }, at);
```

```js
// Countdown ring: the number and the arc from one clock; colour flips under a threshold
const C = { s: 60 }, L = 2 * Math.PI * r;  arc.setAttribute("stroke-dasharray", L);
const ring = () => { num.textContent = Math.ceil(C.s); arc.setAttribute("stroke-dashoffset", L * (1 - C.s / 60));
                     arc.setAttribute("stroke", C.s < 15 ? danger : accent); };
ring(); tl.to(C, { s: 12, duration: 5, ease: "none", onUpdate: ring }, at);
```

**Rules:**
- **Values come from the app:** its real ranges, units, decimals and formatting (`toFixed`, currency, `%`). Use `font-variant-numeric: tabular-nums` so the digits don't jitter.
- **Choose the ease by what the number is:**
  - growth that accelerates (a multiplier, a price) uses `power1.in` or an exponential `m(p)`;
  - a count-up to a result uses `power3.out`;
  - a clock uses `ease: "none"`.
- **Mark milestones:**
  - the number pops (`scale 1.12`, 0.12 s);
  - the colour shifts at thresholds;
  - a `tick` sound plays per whole step, pitch rising (from the same proxy, precomputed times);
  - a `success` or `impact` sound plays at the payoff.
- **Draw charts and paths in sync:** progress rings (`stroke-dashoffset`), bars (`scaleY` from the base), sparklines (the path is rebuilt from `p`) and gauges (the needle's `rotation`).

---

## 6. Orchestrated split panes

When two panels show one process (a build log and the UI it builds, a chat and its result, an order and its map), **one step table drives both**, and the score reads the same table:

```js
// in audio/cues.mjs so the score can voice each step
export const STEPS = [[1.0, "Writing src/pages/home.tsx", [0, 1]], [1.8, "Updating the database", [2, 3]], [2.6, "Wiring checkout", [4]], [3.3, "✓ Built in 41s", [5]]];
STEPS.forEach(([t, , blocks], i) => {
  tl.fromTo(lines[i], { opacity: 0, x: -8 }, { opacity: 1, x: 0, duration: 0.25, immediateRender: false }, t);
  blocks.forEach((b, k) => tl.fromTo(uiBlocks[b], { opacity: 0, scale: 0.85 }, { opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.8)", immediateRender: false }, t + 0.08 + k * 0.06));
});
```

- **Use the app's real step strings** (from the code: its status messages and log lines).
- **The right pane's reveal lands about 0.08 s after its log line,** so cause visibly precedes effect.
- **The final step resolves both panes on one beat:** the ✓ line, the last block, a camera push onto the finished UI, and a `success` sound.
- **Pre-set everything hidden at build time** (`gsap.set(lines, { opacity: 0 })`). See the gotcha in `motion-signature.md`.

---

## Plan and checks

In `brag-plan.md`, list per scene:
- the anticipations;
- the micro-interactions;
- any spatial layer (a modal or sheet);
- any immersive camera move;
- any live value with its real range;
- any split-pane step table.

`verify-composition.mjs` checks:
- at least **4 anticipations** (tag `data-fx="anticipate"` on elements that wind up);
- at least **3 micro-interactions** (`data-fx="micro"`);
- an **immersive** camera rig (`data-fx="immersive"`: perspective on `#world`, 3+ layers at different `z`);
- `data-fx="live"` on interpolated values when the app has changing numbers (a warning otherwise).
