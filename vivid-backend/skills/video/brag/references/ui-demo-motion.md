# UI demo motion

How to show the app being *used*, not just displayed: the cursor, clicks, where the eye goes, how long a screen stays up, and how one screen gives way to the next. The helpers are seek-safe GSAP for a Hyperframes composition: every tween sits on the one paused timeline at an explicit time, with no callbacks, timers or randomness.

The defects this reference prevents:

| Defect | Looks like | Rule |
|---|---|---|
| Black or empty frames | the video drops to black between scenes | something from the product is always on screen; `blackdetect` must find nothing (§5) |
| Dead waiting | a static spinner fills half the screen for seconds | compress real waits and keep them moving: a skeleton, a streaming log, a progress bar (§2a) |
| Payoff missed | the feature's key state change flashes past | hold the before state, animate the change, hold the after state (§2b) |
| Unexplained jumps | one module cuts to another with no framing | a short headline names each module as it arrives (§5a) |
| Typing in blocks | the prompt appears word by word | type character by character with a caret (§1a) |
| Robot cursor | straight lines at constant speed | eased, slightly curved moves; duration grows with distance (§1) |
| Screen gone before it's read | dense UI flashes past | dwell for 1.5–2 s on dense screens (§2) |
| Invisible clicks | the screen just changes | press, ripple, then the result 0.1–0.15 s later (§3) |
| Hunt the action | the whole desktop at small size | push in on the thing that matters, then back out (§4) |
| Jarring context jumps | a hard cut between unrelated screens | pan, a short fade/slide, or a skeleton bridge (§5) |

---

## 0. Stage structure

Put every screen inside one camera layer. The cursor and click effects go inside the camera too, so they zoom with the UI.

```html
<div id="root" data-composition-id="main" data-width="1920" data-height="1080" ...>
  <div id="camera" data-layout-allow-overflow style="position:absolute;inset:0;transform-origin:0 0">
    <div class="screen" id="s-home">...</div>
    <div class="screen" id="s-detail">...</div>
    <div id="fx" style="position:absolute;inset:0;pointer-events:none"></div>
    <svg id="cursor" width="28" height="28" viewBox="0 0 28 28"
         style="position:absolute;left:0;top:0;transform-origin:4px 3px;z-index:50">
      <path d="M4 3 L4 22 L9.5 17 L13 25 L16 23.6 L12.6 15.8 L20 15.6 Z"
            fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>
    </svg>
  </div>
</div>
```

Keep `overflow:hidden` on the root. `data-layout-allow-overflow` on `#camera` is required: zooms and pans push content past the frame edges on purpose, and without it `hyperframes check` fails with `text_box_overflow`.

Coordinates below are in camera space (the stage at scale 1). Measure targets when you build the timeline, before any camera tween has run:

```js
const cam = document.querySelector("#camera");
function centerOf(sel, dx = 0, dy = 0) {
  const r = document.querySelector(sel).getBoundingClientRect();
  const c = cam.getBoundingClientRect();
  const k = c.width / cam.offsetWidth || 1;           // in case the stage is scaled to fit
  return { x: (r.left - c.left) / k + r.width / k / 2 + dx, y: (r.top - c.top) / k + r.height / k / 2 + dy,
           w: r.width / k, h: r.height / k };
}
```

For screens that aren't visible yet (opacity 0), measure them in place: opacity doesn't change layout. Never measure an element that is `display:none`.

---

## 1. Cursor: human paths

People accelerate, then decelerate, and their hand arcs a little. Tween x and y with **different** eases. The path then bends naturally, and the move lands slightly past the target and corrects.

```js
const cursor = "#cursor";
let cur = { x: 0, y: 0 };
function cursorAt(tl, at, p) { tl.set(cursor, { x: p.x, y: p.y }, at); cur = { x: p.x, y: p.y }; }

// Move to p starting at `at`. Returns the time the cursor has settled.
function cursorTo(tl, at, p, o = {}) {
  const dist = Math.hypot(p.x - cur.x, p.y - cur.y);
  const dur = o.duration ?? Math.min(1.1, Math.max(0.45, 0.32 + dist / 1700));   // longer trips take longer
  // overshoot: land a few px past the target along the direction of travel, then correct
  const ux = dist ? (p.x - cur.x) / dist : 0, uy = dist ? (p.y - cur.y) / dist : 0;
  const over = Math.min(10, dist * 0.02);
  tl.to(cursor, { x: p.x + ux * over, duration: dur, ease: "power3.inOut" }, at);
  tl.to(cursor, { y: p.y + uy * over, duration: dur, ease: o.arc === false ? "power3.inOut" : "sine.inOut" }, at);
  tl.to(cursor, { x: p.x, y: p.y, duration: 0.14, ease: "power2.out" }, at + dur);
  cur = { x: p.x, y: p.y };
  return at + dur + 0.14;
}
```

- **Aim at the target's centre, or a little left of the label.** People don't click an exact geometric centre: offset by a few px (`centerOf(sel, -6, 2)`).
- **Pause before and after.** Rest 0.15–0.3 s before a move and 0.1–0.2 s after landing before the click. Moving is followed by aiming.
- **Keep it in view and don't wander.** Only move to things that are about to be used. Park the cursor at the edge, or fade it out, during scenes with no interaction.
- **Typing:** see §1a. Never reveal typed input by words or in blocks.

### 1a. Typing into a field

A prompt typed into a field should look like a person typing: one character at a time, at an uneven but steady pace, with a caret. Revealing whole words or chunks reads as a glitch.

```js
// Seconds per character, cycled. People type in bursts, so the pattern is uneven but never random.
const TYPE_GAPS = [0.055, 0.07, 0.045, 0.085, 0.06, 0.05, 0.11, 0.065, 0.048, 0.075];
// Type `text` into el starting at `at`. Returns the time the last character appears.
function typeText(tl, el, at, text, o = {}) {
  const speed = o.speed ?? 1;             // 1 ≈ 14 chars/s; use 1.4–1.8 for long prompts
  el.textContent = "";
  const chars = [...text].map((c) => {
    const s = document.createElement("span");
    s.textContent = c;
    s.style.whiteSpace = "pre";
    s.style.display = "none";
    el.appendChild(s);
    return s;
  });
  const caret = document.createElement("span");
  Object.assign(caret.style, { display: "inline-block", width: "2px", height: "1.1em",
    marginLeft: "1px", verticalAlign: "-0.15em", background: "currentColor" });
  el.appendChild(caret);                  // sits right after the last visible char
  tl.set(caret, { opacity: 1 }, Math.max(0, at - 0.3));
  let t = at;
  chars.forEach((s, i) => {
    tl.set(s, { display: "inline" }, t);
    const c = text[i];
    let gap = TYPE_GAPS[i % TYPE_GAPS.length] / speed;
    if (c === " ") gap += 0.03 / speed;               // tiny beat between words
    if (/[,.!?]/.test(c)) gap += 0.14 / speed;         // pause after punctuation
    t += gap;
  });
  // blink after typing (finite, seek-safe)
  const blinkFor = o.blinkFor ?? 1.2;
  for (let b = 0; b < blinkFor / 0.5; b++) tl.set(caret, { opacity: b % 2 ? 1 : 0 }, t + 0.25 + b * 0.5);
  if (o.hideCaretAt) tl.set(caret, { opacity: 0 }, o.hideCaretAt);
  return t;
}
```

- **Keep typed prompts to ~60 characters.** If the real prompt is longer, type the first clause at speed 1, then the rest at 1.8. Never jump the text.
- **Sound:** a keypress SFX on every 2nd–3rd character, at 0.3–0.45 volume, from the `keyboard/` set in a fixed rotation. Leave out spaces.
- **Submit it like a person:** a short pause (0.2–0.35 s) after the last character, then a click on the send button with the full click cue (§3), or an Enter keypress with the field flashing briefly.

---

## 2. Dwell time

Count from when the screen has **settled** (its last element has landed), not from when it first appears.

| Screen | Dwell |
|---|---|
| A single message, toast or button state | 0.8–1.0 s |
| A normal screen with one focal point | 1.0–1.4 s |
| **Dense**: a grid of options, a table, a generated spec, a form, a dashboard with more than ~4 figures, or more than ~25 words | **1.5–2.0 s**, and push in on the part that matters (§4) |
| The result the whole video builds to | 1.8–2.5 s |

If the video gets too long, cut a scene. Don't shorten the dwell on the scenes you keep. During a dwell, the frame can still breathe: a slow 1–2% camera drift, or a counter finishing its count. It must not be frozen, and it must not be busy.

---

## 2a. Waiting, compressed

Real products wait: the workspace boots, the build runs, the AI generates. A static spinner in half the frame for seconds is dead screen time. **Show every wait as a time-lapse of 0.8–1.5 s that keeps moving.**

- **Show real progress,** taken from the app:
  - **Loading UI:** its own skeleton, filling in block by block.
  - **Logs and steps:** its real log or step messages (from the code: the strings it streams, its status labels), streaming line by line.
  - **Progress bars:** filling.
  - **Elements:** building in one by one.
- **Something must change at least every 0.25 s** in the waiting area.
- **Say the wait was cut,** if it matters: a small "sped up" chip, or a clock or counter ticking fast. Never show the real duration of a spinner.
- **Keep it in proportion.** A spinner that is the whole story of a wait gets at most 0.6 s. If the wait takes half the screen, the other half keeps working too (the chat streaming, the plan appearing).

## 2b. Payoff states

When the feature *is* a change of state, the viewer must see both sides and the change between them. Examples: an error the product fixes by itself, a failed check that passes, pending → approved, empty → filled, a warning → resolved.

1. **Hold the before state for 1.5–2 s.** Make it clear: a red or amber state, its icon, and the product's own message ("The page crashed — fixing it first"). Push in on it (§4).
2. **Animate the change for 0.4–0.8 s.** The colour morphs (red → green), the icon swaps with a small scale pop, the label changes, and a progress indicator or a streaming fix appears between the two if the app shows one.
3. **Hold the after state for 1.2–1.8 s.** A success SFX lands on the change (a soft `interface/error_*` or `bong` on the failure, then a bell or `impactSoft` on the fix).

Name this beat in the plan as a highlight in its own right. Self-repair, fraud checks and approvals are often the most impressive thing a product does, and flashing past them wastes them.

## 3. Click cues

Give the viewer three beats, in this order: **press**, **ripple**, then the **result** 0.10–0.15 s later. Never change the screen on the same frame as the click.

```js
let rippleN = 0;
// Click at p (camera space) at time `at`; optionally press a target element. Returns when the result may start.
function click(tl, at, p, o = {}) {
  // cursor press
  tl.to(cursor, { scale: 0.82, duration: 0.07, ease: "power2.out" }, at);
  tl.to(cursor, { scale: 1, duration: 0.16, ease: "back.out(2)" }, at + 0.07);
  // the pressed control dips and returns
  if (o.target) {
    tl.to(o.target, { scale: 0.96, duration: 0.07, ease: "power2.out" }, at);
    tl.to(o.target, { scale: 1, duration: 0.2, ease: "back.out(2)" }, at + 0.07);
  }
  // ripple: one element per click, created at build time
  const r = document.createElement("div");
  r.id = `ripple-${rippleN++}`;
  const size = o.size ?? 84;
  Object.assign(r.style, {
    position: "absolute", left: `${p.x - size / 2}px`, top: `${p.y - size / 2}px`,
    width: `${size}px`, height: `${size}px`, borderRadius: "50%",
    background: o.color ?? "rgba(255,255,255,0.55)",
    boxShadow: `0 0 0 3px ${o.ring ?? "rgba(255,255,255,0.9)"}`, opacity: 0, zIndex: 40,
  });
  document.querySelector("#fx").appendChild(r);
  tl.fromTo(r, { scale: 0.15, opacity: 1 }, { scale: 1.5, opacity: 0, duration: 0.5, ease: "power2.out", immediateRender: false }, at);
  return at + 0.12;
}
```

- **The ripple must contrast with what's under it.** On a filled button (accent background), use the defaults: a white fill and a white ring. On a plain light surface, use the app's accent: `color` at ~0.25 alpha and `ring` at ~0.7. Never use the accent on an accent button, because it disappears. Check a still 0.1 s after the click.
- **Every click that submits, sends or changes the screen gets the full cue,** even when the button also changes its label ("Processing…", "Sending…"). The label change is the result, not the feedback. On touch screens, the touch dot squeezes and ripples in the same way.
- **Only the clicks that cause something get a cue.** Every cue also gets a soft click SFX: `interface/click_*` or `ui/mouseclick1` at 0.5–0.65.
- **On a phone mock-up:** there is no cursor. Draw a touch dot (a 44 px, 25% opacity circle) that appears, squeezes and ripples in the same way.

---

## 4. Focus and zoom (the camera)

A viewer should never have to hunt. Push in on the action and the result, then pull back out to give context again.

```js
const W = 1920, H = 1080;   // the composition size
// Frame the rect r (camera space, from centerOf) so it fills `fill` of the screen, max zoom `max`.
function focus(tl, at, r, o = {}) {
  const fill = o.fill ?? 0.55, max = o.max ?? 1.8;
  const s = Math.min(max, Math.max(1, Math.min((W * fill) / r.w, (H * fill) / r.h)));
  const x = Math.min(0, Math.max(W - W * s, W / 2 - r.x * s));   // clamp: never show past the stage edge
  const y = Math.min(0, Math.max(H - H * s, H / 2 - r.y * s));
  tl.to("#camera", { x, y, scale: s, duration: o.duration ?? 0.8, ease: o.ease ?? "power3.inOut" }, at);
  return at + (o.duration ?? 0.8);
}
function wide(tl, at, o = {}) {
  tl.to("#camera", { x: 0, y: 0, scale: 1, duration: o.duration ?? 0.7, ease: "power3.inOut" }, at);
  return at + (o.duration ?? 0.7);
}
```

- **Fill the frame.** A full desktop UI at 1920 wide makes its text tiny, and in a dark app the frame reads as empty. In every UI scene the part being shown (the chat, the spec, the phone, the build row) fills at least **55–60% of the frame width** while it's being read. Push in on it, or crop to that pane. Show the whole app only for the ~1 s establishing beat.
- **Zoom range:** 1.2–1.8×. Anything bigger reads as a jump. Zooms take 0.6–0.9 s, eased `power3.inOut`, and never linear.
- **When to push in:** as the cursor starts its last approach, so the zoom and the move finish together. Or on the result: the toast, the updated preview, the generated item.
- **One zoom per beat.** In → dwell → out, or in → cut to the next scene. Don't wobble in and out on the same screen.
- **Keep the UI sharp.** Build screens at the stage's real size in HTML/CSS (not screenshots) so a 1.8× zoom stays crisp. If you must use a screenshot, capture it at 2× and cap the zoom at 1.4×.
- **Motion blur:** don't use it on zooms. Keep the UI readable.

---

## 5. Context transitions

Choose the transition by how far apart the two screens are:

| Relationship | Transition | Timing |
|---|---|---|
| **Same app, next step** (list → detail, form → confirmation) | **Spatial pan.** Lay the screens side by side on one wide canvas inside `#camera` and pan the camera. Or use the app's own navigation motion (a sheet rising, a page pushing in). | 0.5–0.7 s, `power3.inOut` |
| **Same app, different area** (customer app → admin dashboard) | **Slide and fade:** the old screen moves out 60–120 px and fades, then the new one comes in from the other side. The two overlap by at most 0.1 s. | 0.2–0.3 s each |
| **Before → after, or input → output** (a text spec → the rendered UI; a prompt → the result) | **A bridge:** 0.4–0.6 s of the app's own loading state (a skeleton, a spinner, a progress bar, "Generating…"), then the result builds in piece by piece. | 0.4–0.6 s of bridge |
| **Unrelated contexts** (two separate modules, or a title card) | **A lateral slide:** the whole frame slides left as the next module slides in from the right, like one continuous strip. Or push through a scaled-up field in the brand colour that carries the next module's headline (§5a). | 0.35–0.5 s |

- **Never black, never empty.** No transition passes through a black or blank frame. The only exception is the dark background of an app that really is dark, and even then the next module's headline or chrome is already on screen. A fade "to black and back" is a defect. After rendering, `blackdetect` (step 4) must report nothing.
- **Keep the app's frame on screen.** When moving between screens of the same app, keep its persistent chrome (sidebar, top bar, tab bar, the device frame) fixed. Swap only the content area. The viewer stays oriented.
- **Hard cuts** are only for the chaotic tone, and only on a beat.
- **Never crossfade two busy layouts at full opacity.** It makes a muddy double exposure. Stagger them instead: the old one goes out, then the new one comes in.
- **Carry one element across the cut when you can**: the card the viewer clicked grows into the next screen's header, or the cursor stays put while the screen changes under it. That continuity is what makes it read as one product.

---

## 5a. Module headlines

When the video moves to a new module or area, especially one unlike the last (perpetuals trading → an arcade game; a spec → the builder), give it a **headline**. Without one, the viewer doesn't know why the product just changed.

- **Length:** 2–6 words that say what this part does for the user, in the product's own words: "Trade perps with 50× leverage", "Then play while you wait", "Your spec becomes the app". It can't be just a label like "Arcade".
- **Placement:** above the UI or in a clear band beside it, never over the part being shown. It uses the video's display font, with a consistent position and style for every module.
- **Timing:** it lands at the start of the scene, or rides in with the lateral slide. It is revealed with a text-animation recipe (slide by word, or blur in by line) and stays up for the whole scene.
- **Optional counter:** a small module counter ("1/3") or the app's own section name as a kicker, if it helps show that this is one product with several parts.
- **Its role:** the headline is the bridge between modules. With it, the lateral slide between unrelated modules reads as the next chapter rather than a jump.

## 6. A worked beat

```js
// Scene: tap "Place order", show the confirmation, focus on it.
const btn = centerOf("#place-order", -8, 2);
cursorAt(tl, 6.0, { x: 1500, y: 900 });
let t = cursorTo(tl, 6.2, btn);                     // eased, curved approach
t = focus(tl, t - 0.5, centerOf("#order-panel"), { fill: 0.6 });  // push in during the last part of the approach
t = click(tl, t + 0.15, btn, { target: "#place-order", color: "rgba(99,102,241,0.25)" });
tl.to("#order-panel .skeleton", { opacity: 1, duration: 0.15 }, t);   // bridge
tl.to("#order-panel .skeleton", { opacity: 0, duration: 0.2 }, t + 0.45);
const landed = revealText(tl, document.querySelector("#confirm-title"), t + 0.5, { scope: "word", blur: 8 });
wide(tl, landed + 1.6);                             // dwell 1.6s on the result, then pull back
```

---

## 7. Checks before render

- [ ] No cursor move is linear or constant-speed. Moves ease, arc slightly, and land with a small correction.
- [ ] Every click that changes something has a press, a ripple, and the result 0.1–0.15 s later.
- [ ] Dense screens hold for 1.5–2 s after settling, and the key part is zoomed or highlighted.
- [ ] The viewer never has to search for the action: zoom, spotlight, or the cursor points at it.
- [ ] No hard cut between different contexts, except on a beat in the chaotic tone.
- [ ] No black or empty frame anywhere (`blackdetect` finds nothing). The app's chrome stays fixed across its own screens.
- [ ] Every new module arrives with a 2–6 word headline that says what it does.
- [ ] No static loading state lasts more than 0.6 s. Waits are compressed time-lapses that keep moving.
- [ ] Payoff state changes hold before (1.5–2 s), animate, then hold after.
- [ ] Typed input appears character by character with a caret, never in word blocks.
- [ ] Grab stills mid-zoom and mid-transition: the UI stays crisp, and there's no double exposure.
