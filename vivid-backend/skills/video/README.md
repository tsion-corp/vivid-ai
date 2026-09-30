# Launch-video skills (app/builder/video.py)

Vendored so a video is made the same way every time:

- `brag/`: the /brag skill, https://github.com/latent-spaces/brag (MIT, see
  brag/LICENSE), **extended by Vivid**. The extensions add:
  - references: the story and script, scene flow, the motion signature, depth and
    interaction, sound design, text animation, UI demo motion, and effects;
  - `scripts/synth` (an original score per video, from Mort1d/motion-graphics-skills, MIT);
  - `scripts/voice.mjs` (voiceover) and `scripts/verify-composition.mjs` (the pre-render gate);
  - worked examples.

  Credits are in brag/CREDITS.md. Its music and sound effects are baked into the
  vivid-video sandbox template (sandbox-templates/vivid-video).
- `hyperframes/`: the Hyperframes agent skills brag loads (core, animation,
  creative, keyframes, cli, audio) from https://github.com/heygen-com/hyperframes
  at v0.8.91 (commit dcff547), Apache-2.0, see hyperframes/LICENSE. The template
  installs the same hyperframes@0.8.91 from npm.

To update brag: copy the local skill over `brag/` (without `assets/` and `slim.md`). To update
Hyperframes: copy the new versions over these folders, and bump the npm version in
sandbox-templates/vivid-video/template.py to match.
