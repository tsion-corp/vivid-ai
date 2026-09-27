// Finds the JSX that rendered an element the person clicked in the preview,
// and returns the sources with it removed. Nothing is written here: the
// backend writes the files, typechecks, and keeps or restores them.
//
//   node .vivid/remove-jsx.mjs <request.json>
//
// The request names the element as the page shows it (the preview has no
// source locations): {tag, id, classes, texts, src}. It is matched against
// host JSX elements of the same tag whose text (or image src) contains what
// the page showed. The project's own `typescript` parses the TSX, so ranges
// are exact. Prints one line of JSON:
//   {status: "applied", files: {path: content}, removed: {file, tag, component?}}
//   {status: "not_found" | "ambiguous" | "not_simple", reason}

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const root = process.cwd();
const request = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const ts = createRequire(path.join(root, "package.json"))("typescript");

function out(result) {
  process.stdout.write(JSON.stringify(result) + "\n");
  process.exit(0);
}

// ------------------------------------------------------------------ files
function walk(dir, found = []) {
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const e of entries) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, found);
    else if (/\.(tsx|jsx|ts|js)$/.test(e.name) && !/\.d\.ts$/.test(e.name)) found.push(full);
  }
  return found;
}

const files = walk(path.join(root, "src"));
// All sources, for the constants pages show (contact details, prices);
// only .tsx/.jsx hold elements to remove.
const allSources = new Map();
for (const file of files) {
  const text = fs.readFileSync(file, "utf8");
  const kind = /\.(tsx|jsx)$/.test(file) ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  allSources.set(file, { text, sf: ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind) });
}
const sources = new Map([...allSources].filter(([f]) => /\.(tsx|jsx)$/.test(f)));

// ------------------------------------------------------------------- text
const ENTITIES = {
  "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'", "&#39;": "'", "&nbsp;": " ",
  "&rsquo;": "'", "&lsquo;": "'", "&ldquo;": '"', "&rdquo;": '"', "&mdash;": "—", "&ndash;": "–",
  "&hellip;": "…", "&copy;": "©", "&middot;": "·", "&bull;": "•",
};
function norm(s) {
  return String(s || "")
    .replace(/&[a-z#0-9]+;/gi, (m) => ENTITIES[m.toLowerCase()] ?? m)
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/ /g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

// ------------------------------------------------------------- constants
// Text a page shows from a constant (`{HUB_ADDRESS}`, `{SITE.phone}`) is
// part of what the element shows, so constants are resolved by name:
// `const X = "..."` and string fields of `const X = { a: "...", b: { c } }`.
const constants = new Map();
function literal(e) {
  while (e && (ts.isAsExpression(e) || ts.isSatisfiesExpression?.(e) || ts.isParenthesizedExpression(e))) e = e.expression;
  return e;
}
function collect(name, init) {
  const e = literal(init);
  if (!e) return;
  if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) {
    const list = constants.get(name) || [];
    list.push(e.text);
    constants.set(name, list);
  } else if (ts.isObjectLiteralExpression(e)) {
    for (const prop of e.properties) {
      if (ts.isPropertyAssignment(prop) && (ts.isIdentifier(prop.name) || ts.isStringLiteral(prop.name))) {
        collect(`${name}.${prop.name.text}`, prop.initializer);
      }
    }
  }
}
for (const [, { sf }] of allSources) {
  for (const st of sf.statements) {
    if (!ts.isVariableStatement(st)) continue;
    for (const d of st.declarationList.declarations) {
      if (ts.isIdentifier(d.name) && d.initializer) collect(d.name.text, d.initializer);
    }
  }
}
function constantText(e) {
  if (!(ts.isIdentifier(e) || ts.isPropertyAccessExpression(e))) return null;
  const values = constants.get(e.getText().replace(/\?\./g, "."));
  return values && values.length ? values.join(" ") : null;
}

/** Every piece of text under a node: JSX text, string literals, and the
 *  constants it shows by name. */
function textOf(node) {
  const parts = [];
  const visit = (n) => {
    if (ts.isJsxExpression(n) && n.expression) {
      const known = constantText(n.expression);
      if (known !== null) { parts.push(known); return; }
    }
    if (ts.isTemplateSpan(n)) {
      const known = constantText(n.expression);
      if (known !== null) parts.push(known);
    }
    if (ts.isJsxText(n)) parts.push(n.text);
    else if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) parts.push(n.text);
    else if (ts.isTemplateExpression(n)) {
      parts.push(n.head.text);
      n.templateSpans.forEach((s) => parts.push(s.literal.text));
    }
    ts.forEachChild(n, visit);
  };
  visit(node);
  return norm(parts.join(" "));
}

// -------------------------------------------------------------------- jsx
const tagOf = (n) =>
  ts.isJsxElement(n) ? n.openingElement.tagName.getText() : ts.isJsxSelfClosingElement(n) ? n.tagName.getText() : null;
const attrsOf = (n) => (ts.isJsxElement(n) ? n.openingElement.attributes : n.attributes);

function attr(n, name) {
  for (const a of attrsOf(n).properties) {
    if (!ts.isJsxAttribute(a) || a.name.getText() !== name || !a.initializer) continue;
    if (ts.isStringLiteral(a.initializer)) return a.initializer.text;
    if (ts.isJsxExpression(a.initializer) && a.initializer.expression) {
      const e = a.initializer.expression;
      if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) return e.text;
      return textOf(e);
    }
  }
  return null;
}

function jsxNodes(sf, pred) {
  const found = [];
  const visit = (n) => {
    if ((ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) && pred(n)) found.push(n);
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return found;
}

const skipParens = (n) => {
  while (n.parent && ts.isParenthesizedExpression(n.parent)) n = n.parent;
  return n;
};

// ----------------------------------------------------------------- match
const want = {
  tag: String(request.tag || "").toLowerCase(),
  id: request.id || null,
  classes: (request.classes || []).map(String),
  texts: [...new Set((request.texts || []).map(norm).filter((t) => t.length >= 2))],
  src: request.src ? String(request.src).split("?")[0] : null,
};
if (!want.tag) out({ status: "not_found", reason: "no tag" });

function srcMatches(value) {
  if (!value || !want.src) return false;
  const a = value.split("?")[0];
  return a === want.src || want.src.endsWith(a) || a.endsWith(want.src);
}

const isComponent = (tag) => !!tag && (/^[A-Z]/.test(tag) || tag.includes("."));

/** The JSX element a node sits in as a child (not across a function). */
function parentJsx(n) {
  for (let p = n.parent; p; p = p.parent) {
    if (ts.isJsxElement(p)) return p;
    if (ts.isFunctionLike(p) || ts.isSourceFile(p)) return null;
  }
  return null;
}

/** The returned root tag of a component defined in the project, if any. */
function rootTagOf(name) {
  for (const [, { sf }] of sources) {
    let found = null;
    const visit = (n) => {
      if (found) return;
      if ((ts.isFunctionDeclaration(n) && n.name?.text === name) ||
          (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === name && n.initializer)) {
        const body = ts.isFunctionDeclaration(n) ? n : n.initializer;
        const inner = (b) => {
          if (found) return;
          if ((ts.isJsxElement(b) || ts.isJsxSelfClosingElement(b)) && componentRootOf(b)) { found = tagOf(b); return; }
          ts.forEachChild(b, inner);
        };
        inner(body);
        return;
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    if (found) return found;
  }
  return null;
}

// Every element is scored by how much of what the page showed it holds:
// its text (literals, constants, and text passed as props to components
// inside it), or an image's src.
const scored = [];
for (const [file, { sf }] of sources) {
  for (const node of jsxNodes(sf, () => true)) {
    let score = 0;
    if (want.texts.length) {
      const text = textOf(node);
      score = want.texts.filter((t) => text.includes(t)).length;
    } else if (want.src) {
      score = srcMatches(attr(node, "src")) ? 1 : 0;
    }
    if (score) scored.push({ file, node, score });
  }
}
if (!scored.length) out({ status: "not_found", reason: "no element with that text in the code" });

// The innermost elements holding the most of it...
const best = Math.max(...scored.map((c) => c.score));
let inner = scored.filter((c) => c.score === best);
inner = inner.filter(
  (c) => !inner.some((o) => o !== c && o.file === c.file && o.node.getStart() >= c.node.getStart() && o.node.end <= c.node.end),
);

// ...each resolved to what rendered the clicked element: itself when it has
// the clicked tag, a component (a <Card> renders the div, a <FeatureCard
// title="..."> holds its own text), or else the nearest enclosing one.
const resolved = new Map();
for (const c of inner) {
  let n = c.node;
  while (n && tagOf(n) !== want.tag && !isComponent(tagOf(n))) n = parentJsx(n);
  if (!n) continue;
  if (isComponent(tagOf(n)) && tagOf(n) !== want.tag) {
    // A part inside a component that renders it from props (clicking the
    // <p> of a <FeatureCard>) is the component's own layout, not this use.
    const root = rootTagOf(tagOf(n));
    if (root && root !== want.tag && !isComponent(root)) continue;
  }
  resolved.set(`${c.file}:${n.getStart()}`, { file: c.file, node: n });
}
let pool = [...resolved.values()];
if (!pool.length) out({ status: "not_simple", reason: "part of a component used in several places" });
if (pool.length > 1) {
  const overlapOf = (c) => {
    const id = attr(c.node, "id");
    const cls = (attr(c.node, "className") || "").split(/\s+/);
    return want.classes.filter((k) => cls.includes(k)).length + (want.id && id === want.id ? 5 : 0);
  };
  const top = Math.max(...pool.map(overlapOf));
  pool = pool.filter((c) => overlapOf(c) === top);
}
if (pool.length > 1) out({ status: "ambiguous", reason: `${pool.length} elements match`, count: pool.length });
const picked = pool[0];

/** A wrapper component left holding nothing (<Reveal>, <Button asChild>)
 *  goes with its only child. */
function withWrappers(node) {
  let n = node;
  for (;;) {
    const top = skipParens(n);
    const p = top.parent;
    if (!p || !ts.isJsxElement(p) || !isComponent(tagOf(p))) return n;
    const others = p.children.filter((ch) => ch !== top && !(ts.isJsxText(ch) && !ch.text.trim()));
    if (others.length) return n;
    n = p;
  }
}
const target = { file: picked.file, node: withWrappers(picked.node) };

// ---------------------------------------------------------------- remove

/** The enclosing function's name when `node` is its whole returned JSX. */
function componentRootOf(node) {
  const top = skipParens(node);
  const parent = top.parent;
  let fn = null;
  if (parent && ts.isReturnStatement(parent)) {
    fn = parent.parent;
    while (fn && !ts.isFunctionLike(fn)) fn = fn.parent;
  } else if (parent && ts.isArrowFunction(parent) && parent.body === top) {
    fn = parent;
  }
  if (!fn) return null;
  if (fn.name) return fn.name.getText();
  const decl = fn.parent;
  if (decl && ts.isVariableDeclaration(decl)) return decl.name.getText();
  if (decl && ts.isCallExpression(decl) && decl.parent && ts.isVariableDeclaration(decl.parent)) {
    return decl.parent.name.getText(); // memo(...), forwardRef(...)
  }
  return fn.parent && ts.isExportAssignment(fn.parent) ? "default" : null;
}

function insideMap(node) {
  const top = skipParens(node);
  let fn = top.parent;
  if (fn && ts.isReturnStatement(fn)) {
    fn = fn.parent;
    while (fn && !ts.isFunctionLike(fn)) fn = fn.parent;
  }
  if (!fn || !(ts.isArrowFunction(fn) || ts.isFunctionExpression(fn))) return false;
  const call = fn.parent;
  return !!(call && ts.isCallExpression(call) && /\.(map|flatMap)$/.test(call.expression.getText()));
}

/**
 * The text range to cut so the file still parses: the element, or the whole
 * `{cond && ...}` around it; `{a ? <X/> : <Y/>}` keeps its other branch.
 * Null when the element sits somewhere a cut would not be simple.
 */
function cutFor(node, text) {
  const top = skipParens(node);
  const parent = top.parent;
  if (ts.isJsxElement(parent) || ts.isJsxFragment(parent)) return lineRange(text, node.getStart(), node.end);
  if (ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken && parent.right === top) {
    const holder = skipParens(parent).parent;
    if (holder && ts.isJsxExpression(holder)) return lineRange(text, holder.getStart(), holder.end);
  }
  if (ts.isConditionalExpression(parent)) {
    return { start: top.getStart(), end: top.end, with: "null" };
  }
  return null;
}

/** A range widened to whole lines when the element had lines of its own. */
function lineRange(text, start, end) {
  let s = start;
  while (s > 0 && (text[s - 1] === " " || text[s - 1] === "\t")) s--;
  let e = end;
  while (e < text.length && (text[e] === " " || text[e] === "\t")) e++;
  const ownLine = (s === 0 || text[s - 1] === "\n") && (e >= text.length || text[e] === "\n" || text[e] === "\r");
  if (ownLine) return { start: s, end: text[e] === "\r" ? e + 2 : Math.min(e + 1, text.length) };
  return { start, end };
}

function apply(text, cuts) {
  let result = text;
  for (const c of [...cuts].sort((a, b) => b.start - a.start)) {
    result = result.slice(0, c.start) + (c.with || "") + result.slice(c.end);
  }
  return result;
}

if (insideMap(target.node)) {
  out({ status: "not_simple", reason: "one item of a list the page builds from data" });
}

const changed = {};
const rel = (f) => path.relative(root, f).split(path.sep).join("/");
const component = componentRootOf(target.node);

if (!component) {
  const { text } = sources.get(target.file);
  const cut = cutFor(target.node, text);
  if (!cut) out({ status: "not_simple", reason: "the element is passed as a value, not placed in the page" });
  changed[rel(target.file)] = apply(text, [cut]);
  out({ status: "applied", files: changed, removed: { file: rel(target.file), tag: want.tag } });
}

// The element is a component's whole output (a Hero.tsx returning <section>):
// remove the places that render the component, and their now unused imports.
if (component === "default" || component === "App") {
  out({ status: "not_simple", reason: "that is the whole page" });
}
let usages = 0;
for (const [file, { text, sf }] of sources) {
  if (file === target.file) continue;
  const uses = jsxNodes(sf, (n) => tagOf(n) === component);
  if (!uses.length) continue;
  const cuts = [];
  for (const use of uses) {
    if (insideMap(use)) out({ status: "not_simple", reason: `${component} is rendered in a list` });
    const cut = cutFor(use, text);
    if (!cut) out({ status: "not_simple", reason: `${component} is passed as a value` });
    cuts.push(cut);
  }
  usages += uses.length;
  let next = apply(text, cuts);
  // Drop the import when nothing else in the file names the component.
  const rest = next.replace(/^\s*import[^;]*;?\s*$/gm, "");
  if (!new RegExp(`\\b${component}\\b`).test(rest)) {
    next = next.replace(new RegExp(`^\\s*import\\s+${component}\\s+from\\s+[^;\\n]+;?[ \\t]*\\r?\\n`, "m"), "");
    next = next.replace(/^([ \t]*import\s*\{)([^}]*)(\}\s*from\s*[^;\n]+;?)[ \t]*(\r?\n)?/gm, (m, a, names, b, nl) => {
      if (!names.split(",").some((s) => s.trim() === component)) return m;
      const kept = names.split(",").map((s) => s.trim()).filter((s) => s && s !== component);
      return kept.length ? `${a} ${kept.join(", ")} ${b}${nl || ""}` : "";
    });
  }
  changed[rel(file)] = next;
}
if (!usages) out({ status: "not_found", reason: `nothing renders ${component}` });
out({ status: "applied", files: changed, removed: { file: rel(target.file), tag: want.tag, component } });
