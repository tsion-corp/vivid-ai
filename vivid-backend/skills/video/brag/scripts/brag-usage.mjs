#!/usr/bin/env node
// Tokens used by each /brag run in Claude Code, read from the session logs.
//
//   node ~/.claude/skills/brag/scripts/brag-usage.mjs [project-dir] [--all]
//
// project-dir defaults to the current directory. Lists every session in that project that ran
// /brag (or wrote a brag-output folder), newest first, with its tokens: fresh input, cache
// writes, cache reads, output, and the total. Subagent sessions are included in their parent.
// --all lists every session, brag or not.

import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

const args = process.argv.slice(2);
const dir = resolve((args.find((a) => !a.startsWith("--")) || process.cwd()).replace(/[.\/]+$/, "") || "/");
const all = args.includes("--all");
const logs = join(homedir(), ".claude", "projects", dir.replace(/[^A-Za-z0-9]/g, "-"));
if (!existsSync(logs)) {
  console.error(`no Claude Code sessions for ${dir} (looked in ${logs})`);
  process.exit(1);
}

function sum(file, seen, acc) {
  for (const line of readFileSync(file, "utf8").split("\n")) {
    if (!line.includes('"usage"')) continue;
    let rec;
    try { rec = JSON.parse(line); } catch { continue; }
    const m = rec.message;
    if (!m?.usage || rec.type !== "assistant") continue;
    const key = m.id || rec.requestId || rec.uuid;          // one API call can span several log lines
    if (seen.has(key)) continue;
    seen.add(key);
    const u = m.usage;
    acc.input += u.input_tokens || 0;
    acc.cacheWrite += u.cache_creation_input_tokens || 0;
    acc.cacheRead += u.cache_read_input_tokens || 0;
    acc.output += u.output_tokens || 0;
    acc.calls += 1;
    if (m.model) acc.models.add(m.model);
  }
}

const rows = [];
for (const f of readdirSync(logs).filter((f) => f.endsWith(".jsonl"))) {
  const path = join(logs, f);
  const text = readFileSync(path, "utf8");
  const isBrag = /<command-name>\/?brag<\/command-name>|"skill":"brag"|brag-output/.test(text);
  if (!isBrag && !all) continue;
  const acc = { input: 0, cacheWrite: 0, cacheRead: 0, output: 0, calls: 0, models: new Set() };
  const seen = new Set();
  sum(path, seen, acc);
  const subs = join(logs, f.replace(/\.jsonl$/, ""), "subagents");     // subagents' own logs
  if (existsSync(subs)) for (const s of readdirSync(subs).filter((s) => s.endsWith(".jsonl"))) sum(join(subs, s), seen, acc);
  const out = [...new Set([...text.matchAll(/brag-output(?:-\d{4}-\d{2}-\d{2}-\d{6})?/g)].map((m) => m[0]))].pop() || "";
  rows.push({ session: f.slice(0, 8), when: statSync(path).mtime, out, ...acc });
}
rows.sort((a, b) => b.when - a.when);

const n = (x) => x.toLocaleString("en-US");
const pad = (s, w) => String(s).padStart(w);
console.log(`${"session".padEnd(9)} ${"last active".padEnd(16)} ${pad("calls", 6)} ${pad("input", 9)} ${pad("cache write", 12)} ${pad("cache read", 12)} ${pad("output", 9)} ${pad("total", 12)}  model / output folder`);
for (const r of rows) {
  const total = r.input + r.cacheWrite + r.cacheRead + r.output;
  console.log(`${r.session.padEnd(9)} ${r.when.toISOString().slice(0, 16).replace("T", " ").padEnd(16)} ${pad(r.calls, 6)} ${pad(n(r.input), 9)} ${pad(n(r.cacheWrite), 12)} ${pad(n(r.cacheRead), 12)} ${pad(n(r.output), 9)} ${pad(n(total), 12)}  ${[...r.models].join(",")} ${r.out}`);
}
if (!rows.length) console.log("(no /brag sessions found; pass --all to list every session)");
console.log("\nCache reads are billed at about a tenth of fresh input, so 'total' overstates cost; compare runs by output + input + cache write.");
