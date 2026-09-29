# Launch-video skills (app/builder/video.py)

Vendored, unmodified, so a video is made the same way every time:

- `brag/`: the /brag skill, https://github.com/latent-spaces/brag (MIT, see
  brag/LICENSE). SKILL.md and references only; its music and sound effects
  are baked into the vivid-video sandbox template (sandbox-templates/vivid-video).
- `hyperframes/`: the Hyperframes agent skills brag loads (core, animation,
  creative, keyframes, cli, audio) from https://github.com/heygen-com/hyperframes
  at v0.8.91 (commit dcff547), Apache-2.0, see hyperframes/LICENSE. The template
  installs the same hyperframes@0.8.91 from npm.

To update: copy the new versions over these folders, and bump the npm version in
sandbox-templates/vivid-video/template.py to match.
