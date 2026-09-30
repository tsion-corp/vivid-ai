#!/usr/bin/env node
// Voice every line of a brag voiceover with per-line direction, process it like broadcast VO, and measure it.
//
//   node voice.mjs vo.json [--out composition/assets/vo] [--provider auto|kokoro|openai|elevenlabs]
//
// vo.json: {
//   "voice": { "kokoro": "am_michael", "openai": "ash", "elevenlabs": "<voice_id>" },
//   "lines": [
//     { "id": "vo-01", "text": "This is Ark.", "speed": 0.96, "direction": "confident, a smile in the voice, land on 'Ark'" },
//     { "id": "vo-02", "parts": ["Trade anything.", "Fifty times leverage.", "One tap."], "gap": 0.18, "speed": 1.06,
//       "direction": "building energy, punchy, each phrase a beat" }
//   ]
// }
// - "parts" voices each phrase separately and joins them with `gap` seconds of air: this gives Kokoro rhythm
//   and emphasis it can't do inside one long sentence.
// - "direction" is sent as acting instructions to OpenAI (gpt-4o-mini-tts) and mapped to style/stability for
//   ElevenLabs; Kokoro ignores it (use speed, parts and punctuation there).
// Keys are read from the environment only (OPENAI_API_KEY, ELEVENLABS_API_KEY) and never printed.
// Output: <out>/<id>.wav (48 kHz stereo, processed, −18 LUFS) and <out>/vo.timeline.json with each clip's duration.

import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const argv = process.argv.slice(2);
const opt = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
const spec = JSON.parse(readFileSync(argv[0], "utf8"));
const OUT = resolve(opt("--out", "composition/assets/vo"));
const TMP = join(OUT, ".raw");
mkdirSync(TMP, { recursive: true });

const provider = (() => {
  const p = opt("--provider", "auto");
  if (p !== "auto") return p;
  if (process.env.OPENAI_API_KEY) return "openai";
  if (process.env.ELEVENLABS_API_KEY && spec.voice?.elevenlabs) return "elevenlabs";
  return "kokoro";
})();

const run = (cmd, args, o = {}) => {
  const r = spawnSync(cmd, args, { encoding: "utf8", ...o });
  if (r.status !== 0) throw new Error(`${cmd} failed: ${(r.stderr || r.stdout || "").slice(-400)}`);
  return r;
};
const duration = (f) => parseFloat(run("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).stdout);

async function kokoro(text, file, line) {
  const env = { ...process.env };
  // a local Kokoro venv (sound-design.md §6) when the environment doesn't name one
  const home = process.env.HOME || "";
  for (const py of [`${home}/.cache/brag-tts/bin/python`, "/opt/tts/bin/python"])   // local venv, or the video sandbox's
    if (!env.HYPERFRAMES_PYTHON && existsSync(py)) env.HYPERFRAMES_PYTHON = py;
  // macOS: the espeakng-loader wheel points at a CI path; prefer a system espeak-ng when present
  for (const [lib, data] of [["/opt/homebrew/lib/libespeak-ng.1.dylib", "/opt/homebrew/share/espeak-ng-data"], ["/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1", "/usr/lib/x86_64-linux-gnu/espeak-ng-data"], ["/usr/lib/aarch64-linux-gnu/libespeak-ng.so.1", "/usr/lib/aarch64-linux-gnu/espeak-ng-data"]])
    if (!env.PHONEMIZER_ESPEAK_LIBRARY && existsSync(lib)) { env.PHONEMIZER_ESPEAK_LIBRARY = lib; env.ESPEAK_DATA_PATH = data; }
  const voice = line.voice || spec.voice?.kokoro || "am_michael";
  // the installed hyperframes (pinned in the video sandbox) if there is one; npx otherwise
  const installed = spawnSync("sh", ["-c", "command -v hyperframes"], { encoding: "utf8" }).status === 0;
  const [cmd, pre] = installed ? ["hyperframes", []] : ["npx", ["-y", "hyperframes"]];
  run(cmd, [...pre, "tts", text, "-v", voice, "-s", String(line.speed ?? 1.0), "-o", file], { env });
}

async function openai(text, file, line) {
  const r = await fetch("https://api.openai.com/v1/audio/speech", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: spec.openaiModel || "gpt-4o-mini-tts",
      voice: line.voice || spec.voice?.openai || "ash",
      input: text,
      instructions: [spec.direction, line.direction].filter(Boolean).join(" ") || "Natural, confident product-launch delivery with varied pitch.",
      speed: line.speed ?? 1.0,
      response_format: "wav",
    }),
  });
  if (!r.ok) throw new Error(`openai tts ${r.status}: ${(await r.text()).slice(0, 200)}`);
  writeFileSync(file, Buffer.from(await r.arrayBuffer()));
}

async function elevenlabs(text, file, line) {
  const dir = `${spec.direction || ""} ${line.direction || ""}`.toLowerCase();
  const lively = /excit|energ|punch|hype|big|build/.test(dir), calm = /calm|soft|warm|premium|slow/.test(dir);
  const id = line.voice || spec.voice?.elevenlabs;
  const r = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${id}?output_format=pcm_44100`, {
    method: "POST",
    headers: { "xi-api-key": process.env.ELEVENLABS_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      text, model_id: spec.elevenlabsModel || "eleven_multilingual_v2",
      voice_settings: { stability: lively ? 0.3 : calm ? 0.6 : 0.45, similarity_boost: 0.8, style: lively ? 0.6 : calm ? 0.2 : 0.4, use_speaker_boost: true, speed: line.speed ?? 1.0 },
    }),
  });
  if (!r.ok) throw new Error(`elevenlabs ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const pcm = Buffer.from(await r.arrayBuffer());
  const raw = file.replace(/\.wav$/, ".pcm");
  writeFileSync(raw, pcm);
  run("ffmpeg", ["-v", "error", "-y", "-f", "s16le", "-ar", "44100", "-ac", "1", "-i", raw, file]);
  rmSync(raw);
}

const synth = { kokoro, openai, elevenlabs }[provider];
if (!synth) throw new Error(`unknown provider ${provider}`);

// broadcast VO chain: trim silence, high-pass, presence, gentle compression, level-match
const CHAIN = [
  "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02",
  "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse",
  "highpass=f=85", "equalizer=f=220:t=q:w=1.2:g=-2", "equalizer=f=3600:t=q:w=1.1:g=3", "equalizer=f=9000:t=h:w=0.7:g=1.5",
  "acompressor=threshold=-22dB:ratio=3:attack=6:release=90:makeup=3",
  "loudnorm=I=-18:TP=-2:LRA=7",
  "aresample=48000", "aformat=channel_layouts=stereo",
].join(",");

const timeline = { provider, lines: [] };
for (const line of spec.lines) {
  const parts = line.parts || [line.text];
  const raws = [];
  for (let i = 0; i < parts.length; i++) {
    const f = join(TMP, `${line.id}-${i}.wav`);
    await synth(parts[i], f, line);
    raws.push(f);
  }
  // join parts with air between them
  let joined = raws[0];
  if (raws.length > 1) {
    const gap = line.gap ?? 0.16;
    const inputs = raws.flatMap((f) => ["-i", f]);
    const filt = raws.map((_, i) => `[${i}:a]aresample=48000,aformat=channel_layouts=mono,silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse${i < raws.length - 1 ? `,apad=pad_dur=${gap}` : ""}[p${i}]`).join(";")
      + ";" + raws.map((_, i) => `[p${i}]`).join("") + `concat=n=${raws.length}:v=0:a=1[out]`;
    joined = join(TMP, `${line.id}-joined.wav`);
    run("ffmpeg", ["-v", "error", "-y", ...inputs, "-filter_complex", filt, "-map", "[out]", joined]);
  }
  const out = join(OUT, `${line.id}.wav`);
  run("ffmpeg", ["-v", "error", "-y", "-i", joined, "-af", CHAIN, "-c:a", "pcm_s16le", out]);
  const d = duration(out);
  const words = parts.join(" ").split(/\s+/).filter(Boolean).length;
  timeline.lines.push({ id: line.id, file: `assets/vo/${line.id}.wav`, dur: +d.toFixed(3), words, wps: +(words / d).toFixed(2) });
  console.log(`${line.id}  ${d.toFixed(2)}s  ${words} words  ${(words / d).toFixed(2)} w/s  (${provider})`);
}
rmSync(TMP, { recursive: true, force: true });
writeFileSync(join(OUT, "vo.timeline.json"), JSON.stringify(timeline, null, 2));
const slow = timeline.lines.filter((l) => l.wps < 2.0), fast = timeline.lines.filter((l) => l.wps > 3.4);
if (slow.length) console.log(`note: slow lines (<2 w/s): ${slow.map((l) => l.id).join(", ")} — raise speed or cut pauses`);
if (fast.length) console.log(`note: rushed lines (>3.4 w/s): ${fast.map((l) => l.id).join(", ")} — cut words or lower speed`);
