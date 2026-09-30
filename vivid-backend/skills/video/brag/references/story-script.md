# Story and script

A strong edit can't save a weak story. Write the story before the storyboard, and write the script before you pick any sounds.

Distilled from HeyGen's `product-launch-video` skill (Hyperframes repo, Apache-2.0: story arcs, script patterns, handoffs), Every's `product-launch-video` skill (MIT: the hero moment, before/after, the real-copy rules), and Corey Haines' `marketingskills` (MIT: `ad-creative` hook system, `video` edit anatomy).

---

## 1. The product truth (write these six lines first)

```
Audience:   the narrow slice this video talks to (a situation, not a market)
Pain/desire:in their words, recognisable without explanation
Promise:    ONE line: the thesis of the whole video
Hero moment:the one thing only this product can do: it gets the most screen time
Proof:      the real UI moments / numbers that show the promise (from feature-map.md)
CTA:        the real call to action and URL from the product
```

- **Build around the promise, not a feature list.** A website is an information layout; a video is an emotional sequence. Never follow the page order.
- **Don't spread time evenly across features.** The hero moment gets the most time, and everything else sets it up. If the product has a before/after, that's the money shot: land the *before* for 0.7–1 s, then crash in the *after*.
- **Use only real claims.** Take every line of UI copy, label, number and tagline from the code or the landing page. Invented labels are the #1 reason launches feel fake.

---

## 2. Pick one arc

| Arc | Use when | Beats (≈25 s) |
|---|---|---|
| **PAS** (problem–agitate–solve) | the pain is known and urgent | pain 0–3 → agitate 3–6 → product 6–9 → proof ×2–3 9–20 → CTA 20–25 |
| **BAB** (before–after–bridge) | it replaces an old habit | before 0–3 → after (teased) 3–5 → the product as the bridge 5–8 → step 1 → step 2 → the wow → CTA |
| **Demo loop** | the UI explains itself | a question 0–2 → product 2–4 → demo cycle 1 → demo cycle 2 → trust → CTA |
| **Future pacing** | a new category | "imagine…" 0–3 → the name 3–5 → the pain removed → how it works → the outcome → CTA |
| **Feature cascade** | many capabilities, or status/desire driven | category hook → (feature → benefit) ×2–3 → climax → CTA |

**Beat rules:**
- **One job per beat.** Each beat has a role (hook / pain / product intro / feature / benefit / proof / brand / CTA), a persuasion move (contrast, friction removed, show-don't-tell, a number, the rule of three…) and an emotion. The emotions run from tension (frustration, overwhelm, curiosity) to relief (clarity, control, ease, awe) to action.
- **A UI demo is a sequence on one surface, not one frame:** input → response → result → benefit.
- **The on-ramp continues the hook.** If the hook asks a question, the next beat starts answering it. It never pivots straight into a pitch.
- **Name a breather.** At least one held beat, usually just before the climax, so the energy has contrast.

---

## 3. The hook (0–3 s)

The name is on frame 0 (a creative law). The hook plays **around** it.

**The hook has three parts that never repeat each other:**
- **visual:** stops the thumb;
- **spoken line:** opens a loop;
- **on-screen text:** anchors the claim for people watching muted.

Write all three explicitly. Bad: the voice says "Book in one tap" while the caption says "Book in one tap".

**Formulas** (pick one that fits the product's truth):

| Formula | Example shape |
|---|---|
| Escalate the key word | "Getting traffic is hard. Insanely hard." |
| Ticker takeover | "A doc? A database? A wiki? No: all of them." |
| Milestone march to "…until now" | "From X to Y to Z, it hasn't changed since 1979. Until now." |
| Cold-open number | "One tap. Four seconds. Booked." |
| Relatable POV | "It's 11pm and you're texting your barber for the third time." |
| Small thing, big claim | "It starts as a search bar. It becomes your whole desk." |
| Overwhelm | "Slack, email, docs, three more tabs, and it all lands on you." |
| The prompt is the hook | "What if you could just… ask?" |
| Contrast / before–after | the old way on screen, the new way crashing in |

**Never open with a company description.** The product is on screen by 3 s.

---

## 4. Writing the lines

**The voice, the on-screen text and the visual divide the work:**
- **The visual is the proof.**
- **The on-screen text is the anchor:** the noun, the number or the claim, in 1–5 words. It must carry the story alone, because most social views are muted.
- **The voice is the human framing around it:** the verb, the why, the feeling. It never reads the on-screen text aloud.

**Rhythm:**
- **Vary the sentence length on purpose:** 9 words, 3 words, 12 words, 2 words.
- **Fragments with full stops make a staccato:** "Pick a slot. Tap once. Booked."
- **An em dash makes the turn:** "It looks like a calendar — it's your whole shop."
- **Put the key word last in its sentence,** where the stress falls naturally.
- **Couplets with a tag:** "Drag the value — the button follows. Pick a unit — the code converts. Live."
- **One idea per line.** Write the voice as discrete cues, and reveal each on-screen element **when the voice names it**, never before.

**Word budget:**
- About 2.4–2.6 words per second of speech.
- **About 45–55 words for 25 s**, with the voice covering **no more than ~55% of the runtime**. The rest belongs to the music, the sound effects and the motion.
- Each spoken beat is 6–20 words.

**Specific beats vague:**
- "Cut reporting from an hour to four minutes" beats "Save time".
- A benefit beats a feature.
- Use the active voice, and numbers only when they're true.

**Banned:** "seamless", "unlock the power of", "streamline your workflow", "revolutionary", "next-level", "game-changer", "best/leading" without proof, "we're excited to", long noun-phrase lists, any line that sounds like ad copy when read aloud.

**The CTA:**
- **End on one headline and one call to action,** in the product's real words.
- **Condense the identity into the click:** "This is Trimly. Book your next cut in one tap."
- **Handle an objection if it's true:** "Free. No card."
- **Say the URL** only if it's short and can't be misheard.

---

## 5. Delivery: making the voice not flat

- **One direction per line** in `vo.json` (`scripts/voice.mjs`): energy, attitude, and the word to land on. OpenAI and ElevenLabs perform it. Kokoro can't, so shape Kokoro with the rest of this list.
- **Energy follows the arc:**
  - the hook is quick and curious (speed 1.04–1.08);
  - the pain is slower and wry (0.96–1.0);
  - the product reveal is confident, with a smile (1.0);
  - the demo is brisk (1.06–1.1);
  - the payoff is slower and warm (0.94–0.98);
  - the CTA is calm and certain (0.95).
- **Split staccato lines into `parts`** with 0.15–0.25 s gaps ("Pick a slot." / "Tap once." / "Booked."). Each part gets its own pitch reset, which is where Kokoro's flatness comes from and goes.
- **Punctuation shapes the pitch:**
  - a question mark lifts the end of a line;
  - "…" before a payoff word holds it back;
  - a full stop after a short fragment punches it.
  
  Avoid exclamation marks. TTS overacts them.
- **Keep flowing sentences whole.** Split only for rhythm. A long thought chopped into clips loses its intonation.
- **Choose the voice by the product's audience** (see `sound-design.md` §6). When `OPENAI_API_KEY` or `ELEVENLABS_API_KEY` is set, `voice.mjs` uses it automatically. Say which provider was used in the delivery.
- **Check the pace** in the output: `voice.mjs` flags lines under 2 or over 3.4 words/s.

---

## 6. Voice, music and SFX together

- **Write voice-free windows into the script.** At least two, of 1–2 s each:
  - the hook's first beat before the first word;
  - the signature moves (the pop-out, the morph, the cross-scene flow);
  - the breather before the climax.
  
  The music swells and the SFX lead in those windows.
- **Duck the music 4–6 dB under speech** (about 50–60% level), with a quick attack and ~0.3 s release, so it breathes back between sentences. Never duck to near-silence.
- **Never duck the sound effects.** Place clicks and pops in the gaps between words, or on the phrase ends. Short transients cut through a voice anyway.
- **Drop the music out for 0.5–1 s** just before the CTA line (a `gap()`), so the last line lands in near-silence, then bring back the sonic logo.
- **End cleanly:** the music fades over the last ~0.8 s, or rings out on the final hit. Never a hard cut to silence.

---

## 7. Self-test before building (answer in `brag-plan.md`)

1. Can the promise be said in one line, and does it land by beat 2?
2. Is the product on screen by 3 s, with the name on frame 0?
3. Does the hook name a recognisable pain, contrast or number, with visual, voice and text each saying something different?
4. Does each beat do exactly one job? Is there one hero moment with the most screen time?
5. Is the voice ≤ ~55 words for 25 s, with at least two voice-free windows and silence before the CTA?
6. Is every line specific and traceable to the code or the site, and does it survive being read aloud?
7. Is the end card one headline + CTA, in real copy?

**After the first render, critique the narrative** (pacing, attention peaks and drops, whether each scene earns its time, CTA strength). Name the scene to cut or shorten, and fix it before delivering.
