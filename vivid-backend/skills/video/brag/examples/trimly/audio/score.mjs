// Sound brief: local-services booking app (barbers) → warm funk/boogie backbeat, 100 BPM, E♭ major, ui-led.
// Sonic logo: E♭–G–B♭ bell motif on the name (frame 0 and the lockup). App-world sound: scissor snips on the slots.
// Voice: Kokoro am_michael through scripts/voice.mjs (−18 LUFS clips). Music ducks 5 dB under speech; SFX never duck.
import * as A from '<skill-dir>/scripts/synth/index.mjs';   // replace with the absolute path
import { BPM, DURATION, CUE } from './cues.mjs';

A.init({ duration: DURATION, bpm: BPM, seed: 23 });
const GAIN = { drums: -4, bass: -10, music: -6, lead: -8 };
A.bus('drums', { gain: GAIN.drums, lp: 9000 });
A.bus('bass', { gain: GAIN.bass, duck: 0.5 });
A.bus('music', { gain: GAIN.music, duck: 0.35, verb: 0.2, hp: 160 });
A.bus('lead', { gain: GAIN.lead, verb: 0.25 });
A.bus('fx', { gain: 1, verb: 0.1 });
A.bus('voice', { gain: 8, hp: 90 });
const b = A.beats;
const key = A.scale('Eb', 'major');
const prog = ['Ebmaj7', 'Cm7', 'Abmaj7', 'Bb7sus4'];

// harmony through the whole piece; filter opens as the app arrives
for (let bar = 0; bar * b(4) < CUE.ctaGap[0]; bar++) A.keys(bar * b(4), b(4), A.chord(prog[bar % 4], 4), { type: 'ep', vel: 0.75 });
A.automate('music', 'lp', [[0, 1400], [CUE.morph1, 2600], [CUE.enter, 12000], [CUE.gap, 12000], [CUE.reveal, 3500], [DURATION, 2000]]);

const motif = (t) => ['Eb5', 'G5', 'Bb5'].forEach((n, i) => A.bell(t + i * b(0.5), n, { ratio: 3.01, vel: 0.75 }));
motif(0.05); A.impact(0, { sub: 'Bb1', air: 0.5, vel: 0.6 });

// groove from the app's arrival to the reveal
const g0 = CUE.enter, g1 = CUE.gap;
for (const h of A.steps('X.....x...X.....', { from: g0, to: g1 })) A.kick(h.t, { type: 'soft', tune: 'Bb1', vel: h.vel });
for (const h of A.steps('....X.......X...', { from: g0, to: g1 })) A.snare(h.t, { type: 'lofi', vel: 0.7 });
for (const h of A.steps('x.x.x.x.x.x.x.xo', { from: g0, to: g1, swing: 0.1 })) A.hat(h.t, { metal: 0.2, tone: 0.9, vel: 0.35 * h.vel });
const line = [];
for (const h of A.steps('X..x..X...X.x...', { from: g0, to: g1 })) line.push({ t: h.t, dur: b(0.4), note: A.chord(prog[Math.floor(h.t / b(4)) % 4], 2).root + 12, vel: h.vel });
A.bassLine(line, { cut: 900 });
A.gap(CUE.gap, CUE.reveal, { buses: ['drums', 'bass'] });

// --- SFX on the picture's cues (fx bus never ducks) ---
A.toneSweep(CUE.morph1, 0.65, { from: 'Eb5', to: 'Bb4', wave: 'sine', env: 'swell', vel: 0.45 });    // wordmark morph
A.whoosh(CUE.morph1, 0.6, { shape: 'swell', f0: 300, f1: 3000, vel: 0.5 });
A.thud(CUE.morph1 + 0.65, { f0: 140, vel: 0.5 });
A.whoosh(CUE.enter - 0.05, 0.5, { shape: 'in', pan: [0.8, -0.2], f0: 300, f1: 6000, vel: 0.9 });      // skewed slide-in
A.tick(CUE.headline, { bright: 5000, vel: 0.5 });
for (let i = 0; i < 4; i++) A.pop(CUE.slots + i * 0.07, key.deg(i * 2, 5), { vel: 0.75, pan: i % 2 ? 0.25 : -0.25 });
A.noiseHit(CUE.slots + 0.35, 0.06, { hp: 5000, decay: 0.03, vel: 0.5 });                              // scissor snip
A.noiseHit(CUE.slots + 0.45, 0.06, { hp: 5500, decay: 0.03, vel: 0.45 });
A.swish(CUE.flatten, { dur: 0.4, pan: [-0.3, 0.3], vel: 0.35 });                                      // tilt flattens
A.whoosh(CUE.popOut - 0.02, 0.32, { shape: 'in', f0: 600, f1: 5000, vel: 0.75 });                      // pop-out lift
A.pop(CUE.popOut + 0.3, key.deg(4, 5), { vel: 0.85 });
A.click(CUE.press, { vel: 1 }); A.blip(CUE.press, key.deg(0, 6), { dur: 0.05, vel: 0.6 }); A.thud(CUE.press, { f0: 150, vel: 0.65 });
A.swish(CUE.press + 0.35, { dur: 0.3, vel: 0.35 });
A.toneSweep(CUE.morph, 0.5, { from: 'Bb4', to: 'Eb5', wave: 'sine', env: 'swell', vel: 0.5 });        // button → tick
A.success(CUE.done, 'Eb5', { vel: 0.85 });
A.reverseCymbal(CUE.reveal, 0.9, { vel: 0.5 });
A.whoosh(CUE.reveal, 0.7, { shape: 'swell', f0: 250, f1: 4000, vel: 0.6 });
A.toneSweep(CUE.brandToName - 0.25, 0.6, { from: 'Bb4', to: 'Eb5', wave: 'sine', env: 'swell', vel: 0.4 }); // brand grows into the name
A.impact(CUE.nameClose, { sub: 'Eb1', air: 0.7, vel: 0.85 });
motif(CUE.nameClose + 0.05);
A.swish(CUE.nameClose + 0.2, { dur: 0.35, vel: 0.35 });                                              // tagline flips up
A.pad(CUE.ctaGap[1], DURATION - CUE.ctaGap[1], A.chord('Ebmaj7', 4), { type: 'warm', attack: 0.4, vel: 1 });
A.keys(CUE.ctaGap[1], DURATION - CUE.ctaGap[1], A.chord('Abmaj7', 4), { type: 'ep', vel: 0.8 });

// --- voice: clips at −18 LUFS from voice.mjs; music ducks 5 dB under speech and drops before the CTA line ---
for (const [t, file] of CUE.vo) A.sample(t, file, { bus: 'voice', align: 'start', vel: 1 });
for (const [bus, g] of Object.entries(GAIN)) {
  const pts = [[0, g]];
  for (const [t, , dur] of CUE.vo) pts.push([t - 0.12, g], [t, g - 5], [t + dur, g - 5], [t + dur + 0.3, g]);
  if (bus !== 'drums' && bus !== 'bass') pts.push([CUE.ctaGap[0], g], [CUE.ctaGap[0] + 0.1, g - 30], [CUE.ctaGap[1], g - 30], [CUE.ctaGap[1] + 0.6, g - 5]);
  A.automate(bus, 'gain', pts.sort((p, q) => p[0] - q[0]));
}

A.render('assets/audio/score.wav', { lufs: -14, truePeak: -1, reverb: 'plate',
  sections: { 'name+vo1': [0.3, 1.45], 'app, no voice': [2.5, 3.3], vo2: [3.3, 5.77], 'pop-out+morph': [5.8, 8.6], 'cta vo3': [10.0, 12.26] } });
