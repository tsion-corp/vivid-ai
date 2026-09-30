#!/usr/bin/env node
// Gate a brag composition before render: required motion signature, audible SFX, sane mix.
//
//   node verify-composition.mjs <output-dir>/composition [--tone deadpan] [--no-music] [--no-sfx]
//
// Exits 1 with a list of failures. Fix them and run again; don't render until it passes.

import { readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";

const dir = resolve(process.argv[2] || ".");
const flags = new Set(process.argv.slice(3));
const tone = (process.argv.find((a, i, all) => all[i - 1] === "--tone") || "default").toLowerCase();
const html = readFileSync(join(dir, "index.html"), "utf8");
const fail = [], warn = [];

// ---------- motion signature ----------
// Each move must be tagged with data-fx on the element it moves AND be really animated in the script.
const tagged = (fx) => new RegExp(`data-fx=["'][^"']*\\b${fx}\\b`).test(html);
const has = (re) => re.test(html);
const maxAbs = (re) => Math.max(0, ...[...html.matchAll(re)].map((m) => Math.abs(parseFloat(m[1])) || 0));
const signature = {
  "pop-out": {
    need: () => has(/\b(z|translateZ|rotationX|rotationY)\s*:/) && has(/scale\s*:\s*1\.[0-9]/) && has(/boxShadow|filter\s*:\s*["'`]?drop-shadow/),
    why: "a UI element lifts out of the screen toward the camera (z/scale ≥1.05, a growing shadow)",
  },
  tilt: {
    need: () => has(/perspective/) && maxAbs(/\brotation[XY]\s*:\s*(-?[\d.]+)/g) >= 12,
    why: "perspective shots: a screen or device angled ≥12° in 3D (perspective on the parent), gliding or settling flat",
  },
  skew: {
    need: () => maxAbs(/\bskew[XY]\s*:\s*(-?[\d.]+)/g) >= 5,
    why: "skew on a fast move: the moving layer leans ≥5° in its direction of travel and straightens as it lands",
  },
  morph: {
    need: () => has(/morphSVG|clipPath\s*:|clip-path|borderRadius\s*:/),
    why: "a shape morph: MorphSVG path, a clip-path shape, or a container morph (scale + borderRadius in one tween)",
  },
};
for (const [fx, s] of Object.entries(signature)) {
  if (!tagged(fx)) fail.push(`motion: no element tagged data-fx="${fx}" — required: ${s.why}`);
  else if (!s.need()) fail.push(`motion: data-fx="${fx}" is tagged but the script doesn't animate it — required: ${s.why}`);
}
const tiltCount = (html.match(/data-fx=["'][^"']*\btilt\b/g) || []).length;
if (tiltCount < 2) fail.push(`motion: ${tiltCount} tilt shot(s) — use perspective in at least 2 scenes, one held ≥1.2s at an angle (tiltGlide), not a single quick settle`);

// ---------- depth & interaction (depth-and-interaction.md) ----------
const count = (fx) => (html.match(new RegExp(`data-fx=["'][^"']*\\b${fx}\\b`, "g")) || []).length;
if (count("anticipate") < 4) fail.push(`motion: ${count("anticipate")} anticipation(s) — tag data-fx="anticipate" on at least 4 elements that wind up before their move (presses, exits, pop-outs, camera pushes)`);
if (count("micro") < 3) fail.push(`motion: ${count("micro")} micro-interaction(s) — tag data-fx="micro" on at least 3 controls with a press / busy / done / select state change`);
if (count("immersive") < 1) fail.push('motion: no immersive camera rig (data-fx="immersive": perspective + a camera layer + 3+ layers at different z)');
else {
  const zs = new Set([...html.matchAll(/\bz\s*:\s*(-?\d+(?:\.\d+)?)/g)].map((m) => m[1]));
  if (zs.size < 3) fail.push(`motion: the immersive rig uses ${zs.size} depth value(s) — put 3+ layers at different z so the camera move has parallax`);
}
if (/\d+\.\d+x|\$\d|%\s*<|\bcount/i.test(html) && count("live") < 1) warn.push('motion: the video shows numbers but none is tagged data-fx="live" — interpolate changing values (number + path + colour from one proxy)');

// ---------- scene flow ----------
const scenes = [...new Set([...html.matchAll(/data-scene=["']([^"']+)["']/g)].map((m) => m[1]))];
const flows = [...html.matchAll(/data-flow=["']([^"']+)["']/g)].map((m) => m[1]);
if (scenes.length < 3) fail.push(`flow: ${scenes.length} data-scene roots — mark every scene root data-scene="<n>" (a brag has 4+ scenes)`);
else {
  const kinds = flows.map((f) => f.split(/\s+/)[0]);
  const covered = new Set(flows.flatMap((f) => f.split(/\s+/).filter((w) => /^\d+-\d+$/.test(w))));
  for (let i = 0; i < scenes.length - 1; i++) {
    const key = `${scenes[i]}-${scenes[i + 1]}`;
    if (!covered.has(key)) fail.push(`flow: boundary ${key} has no data-flow device (morph / carry / curve / zoom / inverse / waterfall) — scene-flow.md`);
  }
  if (!kinds.includes("morph")) fail.push('flow: no cross-scene morph (data-flow="morph a-b") — something from one scene must change shape into the next');
  if (!kinds.includes("carry")) fail.push('flow: no carry (data-flow="carry a-b") — keep one element on screen across a cut');
  const bad = kinds.filter((k) => !["morph", "carry", "curve", "zoom", "inverse", "waterfall"].includes(k));
  if (bad.length) fail.push(`flow: unknown device(s) ${bad.join(", ")}`);
}
const extras = ["glow", "glass", "stagger-pop", "exploded"].filter(tagged);
if (!["deadpan", "yc-parody"].includes(tone) && extras.length === 0)
  warn.push("motion: no finishing extra (glow / glass / skew / stagger-pop / exploded) — most tones want at least one");

// ---------- audio ----------
const audios = [...html.matchAll(/<audio\b[^>]*>/g)].map((m) => {
  const tag = m[0];
  const attr = (k) => tag.match(new RegExp(`${k}=["']([^"']*)["']`))?.[1];
  return { tag, id: attr("id"), src: attr("src"), vol: parseFloat(attr("data-volume") ?? "1"), dur: attr("data-duration"), start: parseFloat(attr("data-start") ?? "0") };
});
const probe = (f) => {
  try { return parseFloat(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).toString()); }
  catch { return NaN; }
};
const isMusic = (a) => /music/i.test(a.id || "") || /\/music\//.test(a.src || "");
const isVoice = (a) => /^vo|voice/i.test(a.id || "") || /voice/.test(a.src || "");
const sfx = audios.filter((a) => !isMusic(a) && !isVoice(a));
const music = audios.filter(isMusic);
const voice = audios.filter(isVoice);

const score = audios.find((a) => /score\.wav$/.test(a.src || ""));
if (score) {
  // synth route: one mixed score (music + SFX + voice) written by audio/score.mjs
  const scoreJs = join(dir, "audio", "score.mjs");
  if (!existsSync(scoreJs)) fail.push("audio: score.wav is used but composition/audio/score.mjs is missing");
  else {
    const src = readFileSync(scoreJs, "utf8");
    const calls = (name) => (src.match(new RegExp(`\\b${name}\\(`, "g")) || []).length;
    if (!flags.has("--no-sfx")) {
      if (calls("click") < 1) fail.push("audio: score.mjs voices no clicks — every press gets click() (+ blip) at vel 0.9–1");
      if (calls("whoosh") + calls("swish") < 1) fail.push("audio: score.mjs has no whoosh/swish for transitions and pop-outs");
      if (calls("pop") + calls("blip") + calls("ding") + calls("success") < 1) fail.push("audio: score.mjs has no tuned UI sounds (pop / blip / ding / success)");
      if (calls("impact") + calls("boom") + calls("braam") < 1) warn.push("audio: no impact/boom — the name reveal and big moments usually want one");
      const lowClick = [...src.matchAll(/\bclick\([^)]*vel\s*:\s*(0?\.\d+)/g)].map((m) => parseFloat(m[1])).filter((v) => v < 0.6);
      if (lowClick.length) fail.push(`audio: clicks at vel ${lowClick.join(", ")} will be buried — 0.9–1.0`);
    }
    if (!flags.has("--no-music") && calls("kick") + calls("pad") + calls("pluck") + calls("keys") + calls("bell") + calls("sub") + calls("lead") + calls("bassLine") < 2)
      fail.push("audio: score.mjs writes almost no music — compose the bed from a genre card (sound-design.md §3)");
    if (/sample\([^)]*bus\s*:\s*['"]voice/.test(src) && !/automate\(\s*['"`]?\w*['"`]?\s*,\s*['"]gain/.test(src) && !/automate\(\s*bus\s*,\s*['"]gain/.test(src))
      fail.push("audio: voiceover is placed but nothing ducks the music under it (automate gain −8…−10 dB per line)");
  }
  // mix under the voice: run the score's own report and read the per-section bus table
  if (existsSync(scoreJs)) {
    const rep = spawnSync("node", ["audio/score.mjs", "--report"], { cwd: dir, encoding: "utf8" });
    const lines = (rep.stdout + rep.stderr).split("\n");
    const hi = lines.findIndex((l) => /drums\s+bass\s+music/.test(l));
    if (hi >= 0) {
      const cols = lines[hi].trim().split(/\s+/);
      for (const row of lines.slice(hi + 1)) {
        const m = row.match(/^(.+?)\s+((?:-?[\d.]+|-|NaN)(?:\s+(?:-?[\d.]+|-|NaN))+)\s*$/);
        if (!m) continue;
        const vals = m[2].trim().split(/\s+/).map((v) => (v === "-" ? -Infinity : parseFloat(v)));
        const get = (c) => vals[cols.indexOf(c)];
        const voiceL = get("voice"), fx = get("fx");
        const bed = Math.max(get("drums"), get("bass"), get("music"), get("lead"));
        if (!Number.isFinite(voiceL) || voiceL === -Infinity) continue;
        if (bed < voiceL - 16) fail.push(`mix: section "${m[1].trim()}": the music bed (${bed.toFixed(1)}) is ${(voiceL - bed).toFixed(0)} dB under the voice — duck 4–6 dB, not into silence (keep it within ~12 dB)`);
        const harm = Math.max(get("music"), get("lead"));
        if (harm > -Infinity && harm < voiceL - 18) fail.push(`mix: section "${m[1].trim()}": the harmony (music/lead ${harm.toFixed(1)}) is ${(voiceL - harm).toFixed(0)} dB under the voice — pads/keys/leads are what make it feel musical; keep them within ~15 dB`);
        if (Number.isFinite(fx) && fx > -Infinity && fx < voiceL - 8) fail.push(`mix: section "${m[1].trim()}": SFX (${fx.toFixed(1)}) are ${(voiceL - fx).toFixed(0)} dB under the voice — keep UI sounds within ~6 dB; never duck the fx bus`);
        if (Number.isFinite(fx) && fx > voiceL - 2) fail.push(`mix: section "${m[1].trim()}": SFX (${fx.toFixed(1)}) are as loud as the voice (${voiceL.toFixed(1)}) — the voice leads: keep the fx bus 3–7 dB under it`);
      }
    }
    // voice coverage
    try {
      const cues = readFileSync(join(dir, "audio", "cues.mjs"), "utf8");
      const dur = parseFloat(cues.match(/DURATION\s*=\s*([\d.]+)/)?.[1]);
      const vo = [...cues.matchAll(/\[\s*[\d.]+\s*,\s*['"][^'"]*vo[^'"]*['"]\s*,\s*([\d.]+)\s*\]/g)].reduce((a, m) => a + parseFloat(m[1]), 0);
      if (dur && vo / dur > 0.62) fail.push(`mix: voiceover covers ${Math.round((vo / dur) * 100)}% of the video — keep it ≤ ~55% so the music and the signature moves get their own moments`);
    } catch {}
  }
  const wavPath = join(dir, score.src);
  if (!existsSync(wavPath)) fail.push(`audio: ${score.src} not rendered — run node audio/score.mjs`);
  else {
    const log = spawnSync("ffmpeg", ["-hide_banner", "-nostats", "-i", wavPath, "-af", "ebur128=peak=true", "-f", "null", "-"], { encoding: "utf8" }).stderr || "";
    const summary = log.slice(log.lastIndexOf("Summary:"));
    const I = parseFloat(summary.match(/I:\s+(-?[\d.]+) LUFS/)?.[1]);
    const tp = parseFloat(summary.match(/Peak:\s+(-?[\d.]+) dBFS/)?.[1]);
    if (Number.isFinite(I) && (I < -18 || I > -10)) fail.push(`audio: score loudness ${I} LUFS — target −16…−12 (sound-design.md §7)`);
    if (Number.isFinite(tp) && tp > -0.5) fail.push(`audio: score true peak ${tp} dBFS — keep ≤ −1`);
    if (!Number.isFinite(I)) warn.push("audio: could not measure score loudness (ffmpeg ebur128)");
  }
  const others = audios.filter((a) => a !== score && !isVoice(a));
  if (others.length) warn.push(`audio: ${others.length} extra <audio> next to the score — put SFX and music inside score.mjs so they share one mix`);
} else {
  // library route (bundled tracks + library SFX): only when the user asked for stock music
  warn.push("audio: no synth score (assets/audio/score.wav) — the library route sounds generic; use it only if the user asked for stock music");
  if (!flags.has("--no-music") && music.length === 0) fail.push("audio: no music bed");
  if (!flags.has("--no-sfx")) {
    if (sfx.length < 6) fail.push(`audio: only ${sfx.length} SFX — clicks on every press plus transition/pop/hit accents`);
    const clicks = sfx.filter((a) => /click|mouseclick|tap/i.test((a.id || "") + (a.src || "")));
    for (const c of clicks) if (c.vol < 0.6) fail.push(`audio: click ${c.id} at volume ${c.vol} will be buried under the music — use 0.7–0.95`);
    if (!sfx.some((a) => /whoosh|swish/.test(a.src || ""))) fail.push("audio: transitions have no whoosh/swish");
  }
  for (const a of [...sfx, ...voice]) {
    const f = join(dir, a.src || "");
    if (!a.src || !existsSync(f)) { fail.push(`audio: ${a.id} src missing (${a.src})`); continue; }
    const real = probe(f);
    if (a.dur !== undefined && Number.isFinite(real) && parseFloat(a.dur) < real - 0.02)
      fail.push(`audio: ${a.id} data-duration=${a.dur} cuts the sound (file is ${real.toFixed(2)}s) — omit it or set ≥ ${real.toFixed(2)}`);
  }
  if (voice.length && !(/duck|carve|hf-audio-group/.test(html) || music.every((m) => m.vol <= 0.16)))
    fail.push("audio: voiceover present but the music isn't ducked under it");
}

// ---------- open / close ----------
if (!/data-fx=["'][^"']*\bname-open\b/.test(html)) fail.push('open: tag the frame-0 product name with data-fx="name-open" (visible at t=0, no fade from black)');
if (!/data-fx=["'][^"']*\bname-close\b/.test(html)) fail.push('close: tag the final product-name lockup with data-fx="name-close"');

for (const w of warn) console.log(`warn  ${w}`);
for (const f of fail) console.log(`FAIL  ${f}`);
console.log(fail.length ? `\n${fail.length} failure(s). Fix and re-run before rendering.` : "\ncomposition passes the brag gate.");
process.exit(fail.length ? 1 : 0);
