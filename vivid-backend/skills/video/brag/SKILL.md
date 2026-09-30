---
name: brag
description: Turn the current project website into a short, polished, shareable launch video using Hyperframes. Use when someone says "/brag", "let's brag about this", "make a launch video", "turn this into a video", or wants to share what they built. Reads the project code directly — no live URL or screenshots needed.
---

# /brag

You built it. Now let's brag about it.

## Invocation dispatch (must happen first)

**Always run this full workflow.** Use brag-slim (`<skill-dir>/slim.md`) only when the user explicitly asks for `/brag-slim` or "the slim brag". The full workflow is the one with the motion signature, the synth score, the voiceover decision and the verification gate.

Before inspecting the project, parse the complete `/brag` invocation.

`/brag` turns the current project website or app into a short, polished, shareable launch video using Hyperframes. It is narrow, opinionated, and fun.

## What this skill does

1. Reads the current project code to understand the app.
2. Plans a short brag concept specific to this project.
3. Scripts and storyboards the video.
4. Hands a focused composition brief to Hyperframes.
5. Validates, renders, and writes share copy.

## Parsing the invocation

The user may invoke with natural language or flags:

```
/brag
/brag --tone chaotic
/brag --tone polished --format vertical
/brag this. Make it feel like a ridiculous startup launch.
```

Parse these options:

| Option | Values | Default |
|---|---|---|
| `--tone` | preset or freeform description | inferred |
| `--format` | `landscape`, `vertical`, `square` | `landscape` |
| `--duration` | seconds | auto (15-30s: about 4s per highlight) |
| `--no-music` | flag | music on |
| `--no-sfx` | flag | sfx on |
| `--title` | string | inferred from project |
| `--voice` / `--no-voice` | flag | **decided per video** (`references/sound-design.md` §6) |
| `--library-music` | flag | off: an original synth score is composed |

Voiceover is **your decision** for each video, made in the plan with a reason (sound-design.md §6). `--voice` forces it on, and `--no-voice` forces it off. Use Kokoro via `npx hyperframes tts` (one provider).

Tone can be a preset (`default`, `polished`, `yc-parody`, `chaotic`, `deadpan`, `cinematic`, `app-store`) or a creative direction such as "fake Series A launch from 2016", "museum exhibit", or "overproduced mobile game ad".

When the user gives freeform tone direction, map it to the nearest preset for pacing and structure, but preserve the user's direction in the plan and composition brief.

## Narration guidance

When the video has a voiceover, write narration that complements the visuals, does
not simply read visible text, matches scene pacing, sounds natural and
conversational, and moves smoothly between scenes. Keep the script concise and
specific to the product so the voice feels like part of the edit rather than a
separate narration track.

---

## Output directory

By default, output goes to `brag-output/`. To avoid overwriting previous runs, use a timestamped directory:

```
brag-output-2026-05-04-143022/
```

Use a timestamp when:
- The user explicitly asks for a new run without overriding previous results
- A `brag-output/` directory already exists in the project

Generate the timestamp at the start of the run (`YYYY-MM-DD-HHmmss`) and use it consistently for all output paths in that run: plan, brief, composition, render, and share copy.

## Skill directory

`<skill-dir>` is the directory containing this `SKILL.md`. Claude Code prints it as "Base directory for this skill" when the skill loads; for other agents it's wherever the skill was installed. Bundled assets are under `<skill-dir>/assets/` and scripts under `<skill-dir>/scripts/`. Don't guess an install path: a plugin install, a `~/.claude/skills/` copy, and this repo all put it somewhere different.

---

## Step 1: Inspect the project

**Read:** [references/step-1-inspect.md](references/step-1-inspect.md)

Create `<output-dir>` first (`mkdir -p <output-dir>`). Read the whole codebase, not just the landing page: every route and screen, the data model, the logic and integrations. Write `<output-dir>/feature-map.md` and choose the 3-4 feature highlights the video is built on.

**Gate:** `<output-dir>/feature-map.md` exists: every route or screen, every feature found in the code (rated), the flows, and 3-4 chosen highlights from real screens. You can answer all 9 questions in the brag planning rubric.

---

## Step 2: Plan and storyboard

**Read:** [references/step-2-plan.md](references/step-2-plan.md)
**Read:** [references/story-script.md](references/story-script.md) (product truth, arc, hook, lines, voice delivery; answer its self-test in the plan)

Write `<output-dir>/brag-plan.md` (where `<output-dir>` is `brag-output/` or the timestamped variant chosen above). Answer the planning rubric. Commit to a creative angle. Write the beat-by-beat storyboard including scenes, text, timing, transitions, and SFX cues.

When music is selected, include a compact `Music cue guidance` section: read the bundled track's cue preset from `<skill-dir>/assets/music/cues/` if present, otherwise note cues will be detected at composition time (any track now supports beat sync — see `references/audio.md`). Cue metadata is optional timing guidance only: story, readability, pacing, and product clarity stay primary.

**Gate:** `<output-dir>/brag-plan.md` exists with a full storyboard: one scene per feature highlight from feature-map.md. Scene durations sum to 15–30 seconds.

---

## Step 3: Hand off to Hyperframes

**Read:** The Hyperframes domain skills — `hyperframes-core`, `hyperframes-animation`, `hyperframes-creative`, `hyperframes-keyframes`, `hyperframes-cli`. /brag is its own workflow: do not enter the `hyperframes` entry-point intent interview or route into its generic promo / launch-video workflow.
**Read:** [references/step-3-compose.md](references/step-3-compose.md)
**Read:** [references/audio.md](references/audio.md)
**Read:** [references/text-animation.md](references/text-animation.md)
**Read:** [references/ui-demo-motion.md](references/ui-demo-motion.md)
**Read:** [references/motion-signature.md](references/motion-signature.md) (required moves; study `examples/trimly/`)
**Read:** [references/scene-flow.md](references/scene-flow.md) (every scene hands something to the next)
**Read:** [references/depth-and-interaction.md](references/depth-and-interaction.md) (spatial UI, immersive 3D, micro-interactions, anticipation, live data, split panes; see `examples/live-depth/`)
**Read:** [references/effects.md](references/effects.md)
**Read:** [references/sound-design.md](references/sound-design.md) and [references/genre-cards.md](references/genre-cards.md) (the score, SFX map, voiceover)

Write the composition brief and use Hyperframes to create the video implementation in `<output-dir>/composition/`.

`/brag` owns the product angle, source material, storyboard, tone, format, audio selection, music cue guidance, and delivery expectations. Hyperframes owns the concrete composition structure, exact animation timing, animation mechanics, runtime choices, linting rules, and render workflow.

**Gate:** `npx hyperframes check` passes with zero errors inside `<output-dir>/composition/` (the single browser gate before render — see hyperframes-cli for what it audits).

---

## Step 4: Validate, render, and deliver

**Read:** [references/step-4-deliver.md](references/step-4-deliver.md)

Validate, preview, render to `<output-dir>/brag.mp4`, pick the best poster frame into `<output-dir>/brag.jpg`, bake that poster as the video's frame 0 so it's the idle thumbnail everywhere, and write `<output-dir>/share-copy.txt`.

**Gate:** `verify-composition.mjs` and `hyperframes check` pass before rendering; `blackdetect` finds nothing after. `<output-dir>/brag.mp4` exists. A best-frame poster `<output-dir>/brag.jpg` is picked (not an arbitrary frame) and baked as frame 0 of `brag.mp4`. Share copy is written.

---

## Tone system

Seven tone presets ship with `/brag`. Each changes scripting energy, pacing, typography personality, and transition style. Presets are defaults, not limits.

Full definitions: [references/tones.md](references/tones.md)

| Tone | Energy | One-liner |
|---|---|---|
| `default` | Playful, clean, postable | The good-vibes default |
| `polished` | Serious, elegant | For projects that are not jokes |
| `yc-parody` | Deadpan startup energy | Fake seriousness applied to absurd projects |
| `chaotic` | Fast, loud, aggressive | Over-the-top and unhinged |
| `deadpan` | Calm, dry, understated | The joke is that nothing is a joke |
| `cinematic` | Dramatic, trailer-scale | Big motion, bigger claims |
| `app-store` | Smooth, feature-card clean | Corporate but not boring |

Always allow a freeform creative direction to refine or override the preset.

---

## Creative laws

These apply to every brag video regardless of tone.

**Short.** 15–30 seconds: about 4 seconds per highlight. Not one second more without a reason.

**Readable.** Keep the pace high through motion and cuts, never by flashing text. Every line a viewer must read holds long enough to read it (short label ~0.8s settled; a sentence ~0.3s per word). Fast-in, then hold — never fast-in, then gone.

**Specific.** The video must feel like it was made for this exact project, not any project.

**Show the thing.** Every highlight scene displays a real screen of the working app (from the feature map), not the landing page describing it. No abstract filler.

**Show the whole product.** The highlights come from the whole codebase and, when the product has them, from more than one area (the customer app and the admin, the booking and the payment). A stranger should finish the video knowing what the product does, end to end.

**Open and close on the name.** The very first frame shows the product's name (with its logo if it has one), already readable: no black or empty opening frame. The last frame is the name again as a settled lockup. The hook motion plays around the name, never before it.

**Real icons, never blocks.** Wherever the app shows an icon, the video shows that same icon (from its icon package or SVG files). A grey box or empty square in place of an icon is a defect.

**Type that moves with intent.** Text is revealed by word or by line with staggers, eases and blur-ins from `references/text-animation.md`, chosen per line by its job. A plain fade on every line is a defect.

**Used by a human, not a robot.** When the video shows the app in use: the cursor moves on eased, slightly curved paths; every click that changes something shows a press and a ripple, and the result follows 0.1–0.15s later; the camera pushes in (1.2–1.8×) on the action and its result, so nobody has to hunt; dense screens (grids, specs, tables, forms) hold 1.5–2s after they settle; different contexts are joined by a pan, a 200–300ms slide or fade, or the app's own loading state as a bridge, never a bare hard cut. See `references/ui-demo-motion.md`.

**Never dead, never black.** No frame is black or empty. Transitions slide or fade from one piece of the product to the next, keeping the app's chrome in place; a render with `blackdetect` hits is not finished. Real waits (boot, build, generation) become 0.8–1.5s time-lapses that keep moving (skeletons filling, real log lines streaming), never a static spinner for seconds. Each new module arrives with a 2–6 word headline saying what it does. When the feature is a change of state (an error it fixes itself, a check that passes), hold the before state 1.5–2s, animate the change, and hold the after state. Typed prompts appear character by character with a caret.

**Physical, not flat.** Every big move winds up first (anticipation). Every tap answers immediately (press, busy, done, select states in the app's own copy). Modals and results float over a dimmed, depth-blurred world. At least one scene is a camera moving through layered 3D. Changing numbers interpolate (value, path and colour from one progress value), and split panes resolve together from one step table (`references/depth-and-interaction.md`).

**The story comes first.** Write the product truth, pick one arc, and design the hook as visual + voice + text that never repeat each other. Every line must be specific and real (`references/story-script.md`).

**One continuous film.** Every scene boundary carries something across: a cross-scene morph, a carried element, or a velocity-matched cut. Never a plain cut or crossfade (`references/scene-flow.md`).

**The motion signature is required.** Every video has a pop-out, at least two tilts (one held at an angle), a shape morph, skew on a fast move, and scene flow, each tagged (`references/motion-signature.md`). The tone sets how strong they are, never whether they appear. Before rendering, `node <skill-dir>/scripts/verify-composition.mjs <output-dir>/composition --tone <tone>` must pass.

**An original score, not a stock bed.** Each video gets its own music, composed with the bundled synth: a genre, tempo and key chosen for this app, not four-on-the-floor by habit. Every click, pop, whoosh and hit is voiced from the picture's cue table, loud enough to hear (clicks at vel 0.9–1). Add a voiceover when the product needs explaining, and duck the music under it. See `references/sound-design.md`.

**Finish with purpose.** Use two or three finishing effects from `references/effects.md`, chosen for the tone: shape morphs (button → tick, card → screen), glow on the hero moments, glass callouts over colour, perspective and skew for depth and speed, and continuous cuts (velocity-matched, match cut, zoom-through) between scenes. Each effect has a job, and everything lands flat, sharp and readable.

**Sound fits the app.** The genre, kit, sonic logo and app-world sounds come from this app's category and audience (`references/sound-design.md` §3). The bundled stock tracks (`references/audio.md`) are a fallback only.

**No generic SaaS language.** "Streamline your workflow" is banned. Use the project's actual copy and claims.

**The hook is everything.** The first 2 seconds determine whether someone keeps watching. Plan the hook before anything else.

**Funny earns its place.** Humor should come from the project's absurdity, not from trying to be funny.

**Pattern:**
```
Name on frame 0 + hook (2-3s) → Reveal (2-4s) → 3-4 feature highlights, ~4s each (12-16s) → Punchline/outro ending on the name (2-4s)
```

Adapt this. Not every project needs exactly 3 highlights. The pattern is a starting shape, not a template.
