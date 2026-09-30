# Text animation reference

How to animate type so it feels edited rather than faded in. Written for a
seek-driven Hyperframes composition: one paused GSAP timeline, no timers, and
every state a pure function of time.

The parameter model follows what motion-graphics text tools (for example DaVinci
Resolve text Fuses) expose. Each piece of text has:

- a **scope** (the unit that moves);
- an **order** (who goes first);
- **timing** (delay, duration, stagger);
- an **ease**;
- **effects** that are mixed together (fade, slide, blur, rotate, scale, motion blur).

The code below is our own. Use it as a starting point, not a template.

---

## 1. The model

| Parameter | Values | Default | Notes |
|---|---|---|---|
| `scope` | `word`, `line`, `char` | `word` | `char` only for short words (≤ 12 chars). Never per-char on a sentence. |
| `order` | `ltr`, `rtl`, `center`, `edges`, `random` | `ltr` | `rtl` flips within each line and keeps lines top to bottom. `center` starts from the middle unit and goes outwards. `random` is seeded, so every render is the same. |
| `delay` | seconds | 0 | From the scene start to the first unit. |
| `duration` | seconds | 0.55 (word), 0.7 (line) | Time for **one** unit to arrive. |
| `stagger` | seconds | 0.06 (word), 0.12 (line), 0.025 (char) | The gap between unit starts ("delay between"). |
| `ease` | see §3 | `snap` | |
| `slide` | `up`, `down`, `left`, `right`, or an angle in degrees | `up` | The direction the text travels **toward**. `up` means it comes from below. |
| `distance` | px, or `em` as a string | `0.6em` word, `1.1em` line | Scale it to the font size, never a fixed large px. |
| `blur` | px | 0 | Blur-in: starts at N px and ends sharp. 6–14 px for words, 10–20 px for lines. |
| `rotate` | degrees | 0 | With `pivot` (`"50% 100%"` = bottom centre). Keep it to ±8° unless the tone is chaotic. |
| `scale` | from-value | 1 | 0.92–0.96 for a soft "settle"; 1.15+ for a punch. |
| `fade` | bool | true | Opacity 0 → 1 over the first ~60% of the unit's duration. |
| `mask` | bool | false for words, true for lines | Clips each unit to its own line box, so the text rises out of an invisible slot. |
| `out` | same object or `null` | `null` | An exit. It mirrors the entry by default and runs in reverse order ("last in, first out") unless `outOrder` is set. |

**Timing law (auto-fit).** The whole reveal takes
`delay + (n - 1) * stagger + duration`, where `n` is the number of units.
- **If it's longer than the time available before the hold,** shrink `stagger` first, then `duration`, and never below 0.25 s.
- **Keep the ratio `stagger / duration` between 0.08 and 0.35.** Lower than that and it looks like one block. Higher and it looks like a typewriter.

**Reading law.** After the last unit lands, hold for at least ~0.3 s per word
(0.8 s minimum). The exit starts after the hold, never during it.

---

## 2. Splitting text (preserving lines)

Split once, after fonts load, and before building the timeline. Words keep
their trailing space as a separate text node, so kerning and wrapping don't
change. Lines are measured from where the words actually landed (`offsetTop`),
so the split follows the real wrap at this font and width.

```js
// Split el into word spans; group words into line spans. Returns { words, lines, chars }.
function splitText(el, { chars = false, mask = false } = {}) {
  const text = el.textContent.replace(/\s+/g, " ").trim();
  el.textContent = "";
  const words = [];
  text.split(" ").forEach((w, i, all) => {
    const span = document.createElement("span");
    span.className = "tw";
    span.style.display = "inline-block";
    span.style.whiteSpace = "pre";
    span.textContent = w;
    el.appendChild(span);
    if (i < all.length - 1) el.appendChild(document.createTextNode(" "));
    words.push(span);
  });
  // Group by rendered line.
  const rows = [];
  words.forEach((w) => {
    const top = Math.round(w.offsetTop);
    let row = rows.find((r) => Math.abs(r.top - top) < 4);
    if (!row) rows.push((row = { top, words: [] }));
    row.words.push(w);
  });
  el.textContent = "";
  const lines = rows.map((row) => {
    const line = document.createElement("span");
    line.className = "tl";
    line.style.display = "block";
    if (mask) { line.style.overflow = "hidden"; line.style.paddingBottom = "0.12em"; line.style.marginBottom = "-0.12em"; }
    const inner = document.createElement("span");
    inner.className = "tl-inner";
    inner.style.display = "inline-block";
    row.words.forEach((w, i) => {
      inner.appendChild(w);
      if (i < row.words.length - 1) inner.appendChild(document.createTextNode(" "));
    });
    line.appendChild(inner);
    el.appendChild(line);
    return inner;             // animate the inner span; the outer one is the mask
  });
  let charSpans = [];
  if (chars) {
    words.forEach((w) => {
      const letters = [...w.textContent];
      w.textContent = "";
      letters.forEach((c) => {
        const s = document.createElement("span");
        s.className = "tc";
        s.style.display = "inline-block";
        s.textContent = c;
        w.appendChild(s);
        charSpans.push(s);
      });
    });
  }
  return { words, lines, chars: charSpans };
}
```

- **Set the element's final font, size and width before you split,** or the lines will be measured wrong.
- **Explicit line breaks** (a headline you want on two lines): put each line in its own element and split each one. Don't rely on the wrap.
- **When masking words** (`scope: word, mask: true`), wrap each word the same way as lines, with an outer `overflow:hidden` span.

---

## 3. Eases

Every unit uses the same ease. The feel comes from the curve's shape, so choose on purpose:

| Name | Curve | Feel | Use for |
|---|---|---|---|
| `snap` | a mix of expo-out and quart-out (below) | fast arrival, long soft landing | the default for text; reads as "edited" |
| `glide` | `power3.out` | even deceleration | lines and subtitles, polished |
| `whip` | `expo.out` | almost instant, then settles | chaotic, punchy hooks |
| `settle` | `back.out(1.4)` | a small overshoot | playful single words; never on lines |
| `drift` | `sine.inOut` | slow, cinematic | cinematic title cards, with long durations |
| `exit` | `power2.in` or `expo.in` | leaves fast | every exit: the ease-*in* of the entry curve |

Mixing two curves gives an ease between them. `k` = 0 is pure expo-out (sharp), and `k` = 1 is pure quart-out (softer):

```js
const expoOut = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
const quartOut = (t) => 1 - Math.pow(1 - t, 4);
const snap = (k = 0.4) => (t) => expoOut(t) * (1 - k) + quartOut(t) * k;
// GSAP accepts a function as an ease: { ease: snap(0.4) }
```

**Rules:**
- **Entries decelerate** (`.out`) and **exits accelerate** (`.in`). Never use `.inOut` on a unit that enters from off-mask; it looks like it hesitates.
- **Opacity eases faster than position.** Give the fade ~60% of the duration with `power1.out`, so the unit is visible while it is still moving.
- **Blur clears before the move ends.** Blur runs over ~70% of the duration, so the landing is sharp.
- **One family per video.** Don't mix `back.out` and `expo.out` titles in one edit unless the tone is chaotic.

---

## 4. The reveal helper

The helper builds one tween per unit at an explicit time, so the timeline is fully seekable.

```js
function orderUnits(units, order, seed = 7) {
  const idx = units.map((u, i) => i);
  if (order === "rtl") {
    // reverse within each line, keep lines top-to-bottom
    const byLine = new Map();
    units.forEach((u, i) => {
      const k = Math.round(u.getBoundingClientRect().top);
      (byLine.get(k) || byLine.set(k, []).get(k)).push(i);
    });
    return [...byLine.keys()].sort((a, b) => a - b).flatMap((k) => byLine.get(k).reverse());
  }
  if (order === "center" || order === "edges") {
    const mid = (units.length - 1) / 2;
    const sorted = idx.slice().sort((a, b) => Math.abs(a - mid) - Math.abs(b - mid));
    return order === "center" ? sorted : sorted.reverse();
  }
  if (order === "random") {
    const hash = (i) => { const x = Math.sin((i + 1) * 12.9898 + seed * 78.233) * 43758.5453; return x - Math.floor(x); };
    return idx.slice().sort((a, b) => hash(a) - hash(b));
  }
  return idx; // ltr
}

function slideVector(slide, distance) {
  const deg = { up: 90, down: 270, left: 180, right: 0 }[slide] ?? Number(slide);
  const r = (deg * Math.PI) / 180;
  // travel TOWARD the direction, so start on the opposite side
  return { x: -Math.cos(r) * distance, y: Math.sin(r) * distance };
}

// Add a text reveal to tl at time `at`. Returns the time the last unit lands.
function revealText(tl, el, at, o = {}) {
  const scope = o.scope || "word";
  const split = splitText(el, { chars: scope === "char", mask: o.mask ?? scope === "line" });
  const units = scope === "line" ? split.lines : scope === "char" ? split.chars : split.words;
  const fontPx = parseFloat(getComputedStyle(el).fontSize);
  const dist = typeof o.distance === "string" && o.distance.endsWith("em")
    ? parseFloat(o.distance) * fontPx
    : o.distance ?? (scope === "line" ? 1.1 : 0.6) * fontPx;
  const dur = o.duration ?? (scope === "line" ? 0.7 : scope === "char" ? 0.4 : 0.55);
  let stagger = o.stagger ?? (scope === "line" ? 0.12 : scope === "char" ? 0.025 : 0.06);
  if (o.fitWithin) {                      // auto-fit the whole reveal into a window
    const n = units.length;
    const need = (n - 1) * stagger + dur;
    if (need > o.fitWithin && n > 1) stagger = Math.max(0.02, (o.fitWithin - dur) / (n - 1));
  }
  const ease = o.ease || snap(0.4);
  const { x, y } = slideVector(o.slide || "up", dist);
  const start = at + (o.delay || 0);

  gsap.set(units, {
    x, y,
    opacity: o.fade === false ? 1 : 0,
    filter: o.blur ? `blur(${o.blur}px)` : "none",
    rotation: o.rotate || 0,
    scale: o.scale ?? 1,
    transformOrigin: o.pivot || "50% 100%",
    willChange: "transform, opacity, filter",
  });

  orderUnits(units, o.order || "ltr", o.seed).forEach((i, k) => {
    const u = units[i];
    const t = start + k * stagger;
    tl.to(u, { x: 0, y: 0, rotation: 0, scale: 1, duration: dur, ease }, t);
    if (o.fade !== false) tl.to(u, { opacity: 1, duration: dur * 0.6, ease: "power1.out" }, t);
    if (o.blur) tl.to(u, { filter: "blur(0px)", duration: dur * 0.7, ease: "power2.out" }, t);
  });
  return start + (units.length - 1) * stagger + dur;
}

// Exit: reverse order by default ("last in, first out"), accelerating.
function exitText(tl, el, at, o = {}) {
  const scope = o.scope || "word";
  const units = [...el.querySelectorAll(scope === "line" ? ".tl-inner" : scope === "char" ? ".tc" : ".tw")];
  const fontPx = parseFloat(getComputedStyle(el).fontSize);
  const { x, y } = slideVector(o.slide || "up", (o.distance ?? 0.5) * fontPx);
  const dur = o.duration ?? 0.35;
  const stagger = o.stagger ?? 0.03;
  const seq = orderUnits(units, o.order || "ltr", o.seed);
  (o.lifo === false ? seq : seq.reverse()).forEach((i, k) => {
    tl.to(units[i], {
      x: -x, y: -y, opacity: 0, duration: dur, ease: "power2.in",
      ...(o.blur ? { filter: `blur(${o.blur}px)` } : {}),
    }, at + k * stagger);
  });
  return at + (units.length - 1) * stagger + dur;
}
```

Use it inside the composition's single build, after fonts load, and register the timeline at the end:

```js
document.fonts.ready.then(() => {
  const tl = gsap.timeline({ paused: true });
  const landed = revealText(tl, document.querySelector("#hook"), 0.2, { scope: "word", blur: 10, ease: snap(0.35) });
  exitText(tl, document.querySelector("#hook"), landed + 1.4, { scope: "word" });
  // ...scenes...
  window.__timelines["main"] = tl;   // last
});
```

---

## 5. Recipes

Each one is a set of options for `revealText`. Pick by the job the text is doing, not at random.

| Recipe | Options | Use for |
|---|---|---|
| **Slide in by word** | `{scope:"word", slide:"up", distance:"0.6em", stagger:0.06, ease:snap(0.4)}` | hooks, short claims (≤ 8 words) |
| **Slide in by line (masked)** | `{scope:"line", mask:true, slide:"up", distance:"1.1em", stagger:0.12, duration:0.75, ease:"power3.out"}` | headlines on two or three lines, taglines |
| **Blur in by word** | `{scope:"word", blur:12, distance:"0.25em", stagger:0.07, duration:0.6}` | calm, premium, polished tones |
| **Blur in by line** | `{scope:"line", mask:false, blur:18, distance:"0.35em", stagger:0.14, duration:0.8, ease:"power2.out"}` | cinematic statements, subtitles |
| **Sideways wipe** | `{scope:"word", slide:"right", distance:"0.8em", order:"ltr", stagger:0.05}` | lists, a label being "typed" by motion |
| **Centre burst** | `{scope:"word", order:"center", scale:0.9, blur:6, stagger:0.05}` | one short punchline |
| **Angle drop** | `{scope:"word", slide:-60, distance:"0.9em", rotate:-6, pivot:"0% 100%"}` | playful, chaotic |
| **Char pop** | `{scope:"char", slide:"up", distance:"0.4em", stagger:0.025, ease:"back.out(1.6)"}` | one short word (the product name) |
| **Stat count** | reveal the label by word, and tween a number object's value with `snap: {value: 1}` | metrics |

**Tone mapping** (combine with `tones.md`):

| Tone | Default text motion |
|---|---|
| `default` | slide by word + `snap` ease; lines masked |
| `polished` / `app-store` | blur in by word or line, `glide`; small distances; no rotation |
| `cinematic` | blur in by line, long durations (0.9–1.2 s), `drift`; letter-spacing opening 0.2em → 0.02em |
| `chaotic` | `whip`, per-char or angle drops, rotation, motion blur on the slams |
| `deadpan` | cut-on or a plain fade (no slide), long holds |
| `yc-parody` | clean masked lines, played straight |

---

## 6. Motion blur on text

- **Blur a unit only while it moves fast** (a whip or slam that crosses more than its own width per frame), and it must land sharp. Use Hyperframes' `motion-blur` component (`data-hf-motion-blur` on the moving element; see the `hyperframes-animation` motion-blur reference). Don't fake it with `filter: blur` on a moving unit.
- **Blur-in is a different effect.** It is a focus pull on text that barely moves. Use the `blur` option above.
- **Never motion-blur text that the viewer must read at that moment.**

---

## 7. Checks before render

- [ ] Every text reveal uses a scope and ease chosen for its job (not the same fade on every line).
- [ ] Lines are split from the rendered wrap at the final font size; no word jumps lines while animating.
- [ ] Masked lines don't clip descenders (the padding trick in `splitText`).
- [ ] The last unit lands, then the text holds for its reading time before any exit.
- [ ] Exits are faster than entries and accelerate.
- [ ] There's no `filter: blur` left on settled text (it ends at `blur(0px)`, or is cleared with `clearProps: "filter"` at the landing time).
- [ ] Seeking to any frame gives the same picture (no `Math.random()`, no timers).
