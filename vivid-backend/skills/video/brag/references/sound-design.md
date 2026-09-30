# Sound design: an original score, loud clear UI sounds, and a voice when it helps

The picture is half the video. The other half is sound that belongs to **this app**: never the same stock bed under every product. Every brag video gets one mixed score, written in code with the bundled synth (`<skill-dir>/scripts/synth`, 80 calibrated voices, deterministic, no dependencies). It contains:
- **the music**: an original track in a genre, tempo and key chosen for this app;
- **the sound effects**: every click, pop, whoosh and hit, tuned to the music's key and placed on the picture's own cue times;
- **the voiceover**, when the video needs one, with the music ducked under it.

The synth and `genre-cards.md` come from [motion-graphics-skills](https://github.com/Mort1d/motion-graphics-skills) (MIT). The full voice list is in `<skill-dir>/scripts/synth/*.mjs`. `node <skill-dir>/scripts/synth/selftest.mjs` renders every voice.

The bundled ende.app tracks (`audio.md`) are a **fallback only**: use them when the user asks for "stock music" or `--library-music`, or when the synth can't run.

---

## 1. Working without ears

You can't listen to what you make, so rely on:
- **structures known to work** (the genre cards);
- **calibrated voices**: at `vel: 1`, a one-shot peaks near 0 dB, a pad sits around −17 dB RMS and a bass around −6 dB;
- **numbers**: the render prints LUFS and true peak, and `--report` gives a per-bus level for each scene;
- **pictures**: a spectrogram with the cue lines drawn on it (§9).

If the user can listen, ask them to judge the draft. Their ears beat every metric.

---

## 2. The sound brief (write it in `brag-plan.md` before any code)

```
Sound brief
- App world:     <category from the table below> — <audience, the product's personality>
- Groove & genre:<family: no kick | half-time | backbeat | broken | four on the floor> — <genre card> — why
- Tempo & key:   <BPM> (bar = 240/BPM s), <root> <mode>: chosen, not A minor by habit
- Energy map:    <scene → intro / build / drop / break / outro; what enters and leaves>
- Role:          ui-led (every interface event is voiced, groove lighter) | music-led (the track carries the cuts)
- Hook / sonic logo: <voice + 2–4 note motif>: plays on the product name at frame 0 and on the final lockup
- App-world sounds: <1–3 sounds only this app would have> — where each lands
- Voiceover:     yes/no — why (§6); voice id, speed
- Mix & loudness:<LUFS target>, reverb type, what ducks under what
- Not like the last one because: <genre / tempo / key / kit that differ from earlier brag videos in this folder>
```

---

## 3. Choosing the sound from the app

Choose in this order: groove family, genre, tempo, key, kit. A listener recognises a track by its groove first and its chords last. The genre cards (`genre-cards.md`) give the ready patterns.

| App world | Genres to consider (BPM) | Kit character |
|---|---|---|
| Fintech, trading, banking, payments | minimal pulse or half-time (90–110), cinematic hybrid, UK garage (132); trading/crypto: drift phonk or trap half-time | clean, precise: tight kick, snap, bright short hats, dry |
| Dev tools, AI, SaaS, builders | breakbeat (125–135), liquid DnB (174), glitch-pop, minimal pulse, synthwave (100–118) | clean or glitchy; FM plucks, arps |
| Delivery, commerce, marketplaces | future bass half-time (140–150), breakbeat, jersey club (140), playful pop | bright, bouncy; tuned pops |
| Social, dating, community | future bass, UK garage, kids-pop backbeat, amapiano (112–118) | warm or bouncy; claps, vox chops |
| Games, arcade, events, nightlife | chiptune (120–150), phonk, baile funk, house only for nightlife | hard, loud; chip leads, cowbell |
| Food, cafés, local services | lo-fi (75–90, swing), funk/boogie backbeat (95–112), bossa | warm, round, room reverb |
| Health, wellness, clinics | ambient pulse (70–90), soft piano + glass pads, gentle plucks | soft, no kick or a soft one; long tails |
| Education, kids, family | marimba/kalimba pop backbeat (100–125), chiptune, bouncy breakbeat | warm, toy sounds |
| Luxury, fashion, real estate, travel | luxury ambient (60–95), deep minimal, amapiano log drums, cinematic | big, spacious, hall reverb |
| B2B, logistics, industry | cinematic hybrid (braams, pulses; 80–100 or 120 half-time), minimal pulse | big, cinematic |

- **Four on the floor (house or nu-disco at 116–128) is the trap.** Models reach for it for every product, and then every video sounds like one song. Use it only for nightlife, or when the user asks.
- **The key is a choice.** Use darker F, B♭ or C♯ minor; warm E♭ or B♭ major; bright D or E major; funky D or E dorian. Never use the key of the previous video in this folder.
- **Tune the kick to the key** (`tune` = the root in octave 1, or its fifth if that's under 40 Hz).
- **The edit sets the details.** Fast cuts and whips suit 120+ BPM and short sounds. Long holds and luxury suit 70–100 BPM or half-time, with space.
- **The first 2 seconds of sound must already say "this app".**
- **The tone refines the choice:**
  - `polished` and `app-store` lean clean or minimal;
  - `cinematic` adds braams, risers and a hall reverb;
  - `chaotic` pushes energy, drive and density;
  - `deadpan` goes sparse (a pulse or a single instrument), but is **never silent and never a quiet stock bed**.

---

## 4. The energy map

The track follows the story, scene by scene, in whole bars:

| Part | Where | What happens |
|---|---|---|
| Hook | 0–2 s, on the product name | the sonic logo, a hit on the name, the groove or a filtered version of it already moving |
| Build | into the first feature | a riser or a roll, the filter opening, a reverse cymbal ending on the reveal |
| Hole | ⅛–½ beat before the biggest hits | `gap()`: silence makes the next hit twice as big |
| Drop | the core feature, or the payoff | the full groove, an impact, the bass entering |
| Dense UI / voice scenes | the information-heavy parts | thin out the pads and leads; the drums and bass stay |
| Outro | the product-name lockup | the sonic logo again, a last hit, then a tail of 1.5 s or more; nothing new after it |

Keep something changing every 2–4 bars. A one-bar loop repeated for 8 bars sounds like a template.

---

## 5. The SFX map: every visible event gets a decision

UI demos are **ui-led**: every interface event is voiced, tuned to the scale, 0–3 dB under the music. **The clicks must be clearly audible.** That was the biggest failure of the stock setup, where the clicks were thin library files played at 0.3 volume and sometimes cut to 10 ms.

| On screen | Synth call(s) | Level (`vel`) and timing |
|---|---|---|
| Click / tap on a control | `click(t)` **+** `blip(t, scale.deg(i, 6), { dur: 0.05 })` layered, and `thud(t, { f0: 140 })` for a heavy CTA | vel 0.9–1.0, exactly on the press frame (not the result) |
| Button pops out of the screen (pop-out) | `whoosh(t, 0.3, { shape: 'in', f0: 600, f1: 5000 })` + `pop(t + 0.28, note)` | vel 0.6 + 0.8; the pop lands when it reaches full size |
| Items appearing (cards, rows, chips) | `pop(t, scale.deg(i, 5))`, rising through the scale per item, pan by screen x | vel 0.5–0.7; thin out after 5 items |
| Tilt / perspective settle, a device arriving | `whoosh(t, dur, { shape: 'swell' })` + `thud` or a soft `impact` on the landing | lands on the settle frame |
| Shape morph | `toneSweep(t, dur, { from, to, wave: 'sine', env: 'swell' })` between two scale notes + `swish` | dur = the morph duration |
| Continuous cut / whip / slide between modules | `whoosh(t0, dur, { pan: [-0.8, 0.8] })` following the direction of the move; `reverseCymbal(cut, 0.8)` into big ones | starts with the move; never two whooshes at once |
| Module headline slam | `impact(t, { sub: '<root>1', air: 0.6 })` | on the landing frame |
| Typing | `key(t)` per character from the same schedule as `typeText` | vel 0.4–0.5 |
| Number counting | `tick`s where the digits change, pitch rising | follows the easing |
| Loading time-lapse | a riser under it, plus ticks for streamed lines | ends on the result |
| Success / payoff state | `success(t, root)` or `ding(t, note)`; before it, `errorBuzz(t)` for the red state | on the state change |
| Glow / glass / shine | `sparkle(t)` or a high `swish` | with the sweep |
| Product name at frame 0 and the end | the sonic logo motif + `impact` + (end) the tail | frame 0 / the lockup |

**App-world sounds.** Add one to three sounds that only this app would have: `coin` and a till for payments, `shutter` for a camera app, a scooter `toneSweep` for delivery, `paper` for docs, `heartbeat` for health, chip `blip`s for arcade. Build them from `noiseHit`, `toneSweep`, `bell` and `tick`.

**Variety.** A repeated sound varies a little each time: a scale step up or down, or a different pan. The smaller the UI element, the shorter and quieter its sound, but never below vel 0.45 for a press.

---

## 6. Voiceover: decide, don't default

Choose it in the plan and say why. Use a voiceover when **two or more** of these are true:
- the product needs **explaining** (an unfamiliar category, a multi-module product like trading + arcade, a technical or B2B buyer, a workflow with a before/after);
- the tone is `polished`, `app-store`, `cinematic` or `yc-parody` (the parody voice is dry and played straight);
- the picture is **dense UI**, and a voice lets the headlines stay short;
- the user asked for a voice, or the product itself talks (an AI assistant, a voice app).

**Skip it** for `chaotic` and `deadpan`, when the headlines already tell the story in ≤ 5 words per scene, or when the user passed `--no-voice`.

**Script.**
- **One line per scene,** written for the ear: short clauses, one idea per line, numbers spelled as spoken.
- **Word budget:** about 2.6 words/s. That's 40–55 words for 20–25 s.
- **Complement the headline, don't repeat it.** Headline "Trade perps, 50×". Voice: "Go long or short on anything, with up to fifty times leverage."
- **Open on the product name:** "This is Ark."
- **End on the call to action.**

**Voice.**

| Voice | Use |
|---|---|
| `am_michael` | confident, neutral; SaaS, fintech, B2B |
| `af_heart` | warm, friendly; consumer, social, food, health |
| `bm_george` | premium British; luxury, cinematic |
| `af_nova` | bright, young; commerce, social |
| `bf_emma` | polished British; app-store, finance |
| `am_adam` | deep; cinematic trailers |

Use speed 1.0–1.08. Say which voice you picked in the delivery message.

**Generate the lines with `scripts/voice.mjs`**, not raw `tts` calls. It gives each line its own delivery (speed, `parts` for staccato rhythm, acting `direction`). It runs every clip through a broadcast voice chain (trim, high-pass, presence EQ, compression) and level-matches it to −18 LUFS. It also writes `vo.timeline.json` with each clip's duration and flags rushed or slow lines. Write the lines in `vo.json` following `story-script.md` §5:

```bash
node <skill-dir>/scripts/voice.mjs vo.json --out composition/assets/vo
```

- **Provider:** Kokoro by default (free, local, flatter). If `OPENAI_API_KEY` is set, it uses OpenAI `gpt-4o-mini-tts`, which performs each line's `direction`. If `ELEVENLABS_API_KEY` is set and `vo.json` names an ElevenLabs voice, it uses ElevenLabs. Keys come from the environment only. Say which provider was used in the delivery, and that a key gives a more expressive voice.
- **Kokoro rhythm comes from `parts`:** "…" alone doesn't make a pause. Split the line into parts with a 0.2–0.3 s `gap`.

**The voice sets the timeline.** Measure every line. Place line *n* at its scene's start + 0.15 s, with a gap of at least 0.35 s after the previous line. Extend a scene rather than overlap its lines.

**Setup, if `tts` fails.** It needs Python with `kokoro-onnx soundfile` and a working espeak-ng. Run `uv venv ~/.cache/brag-tts && VIRTUAL_ENV=~/.cache/brag-tts uv pip install kokoro-onnx soundfile`. Get espeak-ng with `brew install espeak-ng` on macOS or `apt-get install -y espeak-ng` on Linux. Then run with `HYPERFRAMES_PYTHON=~/.cache/brag-tts/bin/python PHONEMIZER_ESPEAK_LIBRARY=<libespeak-ng path> ESPEAK_DATA_PATH=<espeak-ng-data dir>`:
- **macOS paths:** `/opt/homebrew/lib/libespeak-ng.1.dylib` and `/opt/homebrew/share/espeak-ng-data`.
- **Why the system espeak-ng:** the `espeakng-loader` wheel on macOS points at a CI path and fails. Use the system espeak-ng instead.

If it still can't run, say so in the delivery and ship without a voice. Don't fall back to a robotic voice.

**Check it** without ears: each clip should run 0.3–0.45 s per word. If `npx hyperframes transcribe` is available, transcribe the clips back and compare them with the script.

---

## 7. Writing the score (`composition/audio/score.mjs`)

The composition's timeline and the score share **one cue table**. Write the times once, in `composition/audio/cues.mjs`, and import them in both places (the page loads them with `<script type="module">`, or copy the numbers exactly). Every SFX sits on the same number the tween uses.

```js
// composition/audio/score.mjs  —  node audio/score.mjs [--report]
import * as A from '<skill-dir>/scripts/synth/index.mjs';   // absolute path to the skill
import { BPM, DURATION, CUE } from './cues.mjs';

A.init({ duration: DURATION, bpm: BPM, seed: 11 });
const GAIN = { drums: -4, bass: -10, music: -6, lead: -8 };   // start here; tune with --report
for (const [bus, g] of Object.entries(GAIN)) A.bus(bus, { gain: g, ...(bus === 'bass' && { duck: 0.5 }), ...(bus === 'music' && { duck: 0.4, verb: 0.2, hp: 160 }) });
A.bus('fx', { gain: 1, verb: 0.1 });                // ui-led: UI sounds sit level with the groove, not under it
A.bus('voice', { gain: 8, hp: 90 });                // voice.mjs clips are −18 LUFS: +8 dB sits them on top

const b = A.beats;   // b(n) = n beats in seconds
const key = A.scale('D', 'dorian');
// ... music: harmony table, groove per scene, from the chosen genre card ...

// SFX from the cue table
CUE.clicks.forEach((t, i) => { A.click(t, { vel: 1 }); A.blip(t, key.deg(i % 5, 6), { dur: 0.05, vel: 0.5 }); });
CUE.pops.forEach((t, i) => A.pop(t, key.deg(i, 5), { vel: 0.7, pan: -0.3 + i * 0.15 }));
CUE.whooshes.forEach(([t, dur, dir]) => A.whoosh(t, dur, { pan: dir > 0 ? [-0.8, 0.8] : [0.8, -0.8], vel: 0.8 }));
A.impact(CUE.nameOpen, { sub: 'D1', air: 0.6, vel: 0.8 });

// voiceover: place the clips; duck the music buses 5 dB under each line (NOT into silence). The fx bus never ducks.
// automate('gain') sets ABSOLUTE dB and replaces the bus gain, so ramp from each bus's own gain, one list per bus.
for (const [t, file] of CUE.vo) A.sample(t, file, { bus: 'voice', align: 'start', vel: 1 });
for (const [bus, g] of Object.entries(GAIN)) {
  const pts = [[0, g]];
  for (const [t, , dur] of CUE.vo) pts.push([t - 0.12, g], [t, g - 5], [t + dur, g - 5], [t + dur + 0.3, g]);
  A.automate(bus, 'gain', pts);
}

A.render('assets/audio/score.wav', { lufs: -14, truePeak: -1, reverb: 'plate',
  sections: { hook: [0, 3], feature: [3, 9], outro: [9.5, 12] } });   // for --report
```

Place it in the composition as **one** audio element. Don't add any separate SFX or music `<audio>` tags, and don't use `data-duration` shorter than the file:

```html
<audio id="score" src="assets/audio/score.wav" data-start="0" data-track-index="10" data-volume="1"></audio>
```

- **Bus gains to start from** (dB): drums −4, bass −10, music −6, lead −8, fx +1 (ui-led), voice +8 (with voice.mjs clips). This was tested: under the voice, the harmony sits about 12 dB below it and the SFX 3–7 dB below it, and each section lands at −11…−15.5 LUFS.
- **The voice leads.** Under speech, the fx bus sits **3–7 dB below the voice**: clearly audible, never louder than it. The gate fails SFX that reach the voice's level, and SFX buried more than 8 dB under it.
- **A voiceover never means fewer sounds.** Keep every click, pop and whoosh. Only the music ducks, by 4–6 dB. Put the signature moves in the gaps between lines.
- **Silence before the CTA, not under it.** Drop the music for 0.4–0.5 s before the last line (a `gap` plus a −30 dB gain dip). Then bring back a **warm bed** (pad + keys) under the line, within about 12 dB of the voice. A lone quiet pad under the CTA fails the gate.
- **Bass:** the synth basses are loud. Start the bass at −10 and check it doesn't sit level with the voice.
- **Automation replaces the bus gain.** `automate(bus, 'gain', …)` values are **absolute** dB and **replace** the bus's gain. A ramp from 0 dB silently undoes a −10 dB bus. Always ramp from the bus's own gain, as above, with one list per bus covering every line.
- **One owner of the low end at a time:** duck the bass under the kick (`duck`).
- **Keep pads out of the mud:** high-pass them at 150–250 Hz.
- **Reverb:** 'plate' for pop and tech, 'hall' for cinematic, 'room' for lo-fi and funk, 'huge' for ambient.
- **Loudness:** −14 LUFS for most, −16 for ambient or luxury, −12 for phonk/trap/chaotic. True peak ≤ −1 dBTP.

---

## 8. Never the same twice

Compare the plan with earlier `brag-output*/brag-plan.md` files in this project (and sibling projects if visible). If the genre, tempo (within 10%), key and kit character all match an earlier video, change the groove family or the genre, not just the chords. Each video also needs at least one app-world sound.

---

## 9. Checking

1. **Levels per scene:** `node audio/score.mjs --report`. `sections` is an object: `{ name: [t0, t1] }`. The targets, from a tested mix:
   - **Voice sections:** the voice bus is 8–15 dB above the loudest music bus (drums, bass or music).
   - **UI scenes:** the fx bus is within about 3 dB of the drums.
   - **Master loudness per section:** within ±2.5 LU of the others, so nothing jumps.

   Don't judge speech with `volumedetect`. Its mean counts the pauses between words, so it reads 4–6 dB low.
2. **Loudness:** `ffmpeg -i assets/audio/score.wav -af ebur128=peak=true -f null - 2>&1 | tail -12`. Check I ≈ the target and true peak ≤ −1.
3. **Spectrogram with cues:** `ffmpeg -i assets/audio/score.wav -lavfi showspectrumpic=s=1600x500:legend=1 ../score.png`. Open it:
   - every click should be a bright vertical stripe at its cue time;
   - whooshes should be diagonal sweeps;
   - the hole before the biggest hit should be a dark column;
   - the tail should fade out before the end.
4. **Then render the video**, and make sure the audio in `brag.mp4` is the score (`ffprobe` shows one audio stream).
