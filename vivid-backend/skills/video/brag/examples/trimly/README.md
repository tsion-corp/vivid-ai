# Worked example: Trimly (12 s)

A tested composition that uses the whole toolkit. It passes `verify-composition.mjs` and `hyperframes check`, and has no black frames.

- **Frame 0:** the product name is already on screen (`name-open`).
- **Continuous cut:** velocity-matched, with a panned whoosh.
- **Tilt:** the app screen arrives tilted and settles flat, with a module headline above it.
- **Stagger-pop:** the slots pop in with tuned pops, plus an app-world "scissor snip".
- **Cursor:** eased, arcing moves.
- **Pop-out:** the CTA lifts while the screen dims, and is pressed while lifted (click + blip + thud, with a ripple).
- **Shape morph:** the button collapses into a green circle, and its arrow morphs into a tick. `success()` plays on the change.
- **Circle reveal:** it opens into the name lockup (`name-close`), with the sonic-logo bell motif and an impact.
- **Sound:** one synth score. Warm funk backbeat, 100 BPM, E♭ major. Two Kokoro voiceover lines (`am_michael`) with the music ducked 9 dB under them.

`audio/cues.mjs` is the one cue table that both the picture and the score read.

To use it, copy the folder, run `node <skill-dir>/scripts/voice.mjs vo.json --out assets/vo`, then `node audio/score.mjs --report`, `node <skill-dir>/scripts/verify-composition.mjs .` and `npx hyperframes render`.
