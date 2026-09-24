// Screenshot the running app's web preview at an iPhone and an Android size.
//   node scripts/screenshot.mjs <url> <outDir>
// Writes iphone.jpg, android.jpg and report.json (console errors, page
// errors, whether the app rendered anything). Used by the builder's critique
// step; Chromium comes from the template image. The names and widths match
// the mobile target's `shots` in the backend (app/builder/targets.py).
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";

const [url = "http://localhost:8081", outDir = "/tmp/shots"] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const executablePath = process.env.CHROMIUM_PATH || "/usr/bin/chromium";
const browser = await chromium.launch({
  executablePath,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});
const shots = [
  { name: "iphone", width: 390, height: 844 },
  { name: "android", width: 412, height: 915 },
];
const report = { errors: [], rendered: {}, overlay: null };
// What Metro and React Native Web show instead of the app when it breaks.
const BROKEN = /(Unable to resolve module|SyntaxError|Uncaught Error|Render Error|TransformError|Text strings must be rendered within a <Text> component)/;

// Metro bundles on the first request, which can take a while on a fresh
// sandbox; one warm-up visit absorbs it so the captures see the settled app.
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: "load", timeout: 90000 });
    await page.waitForTimeout(3000);
  } catch {}
  await ctx.close();
}

async function settle(page) {
  try {
    await page.waitForFunction(
      () => (document.querySelector("#root")?.innerText ?? "").trim().length > 0,
      null,
      { timeout: 20000 },
    );
  } catch {}
  await page.waitForTimeout(1000);
  const text = await page.evaluate(() => (document.body?.innerText ?? "").trim());
  const match = text.match(BROKEN);
  const overlay = match ? text.slice(Math.max(0, match.index - 40), match.index + 560) : null;
  const rendered = await page.evaluate(
    () => (document.querySelector("#root")?.innerText ?? "").trim().length > 0,
  );
  return { overlay, rendered };
}

for (const s of shots) {
  const ctx = await browser.newContext({
    viewport: { width: s.width, height: s.height },
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => report.errors.push(`[${s.name}] ${String(e.message ?? e).slice(0, 300)}`));
  page.on("console", (m) => {
    if (m.type() === "error") report.errors.push(`[${s.name}] console: ${m.text().slice(0, 300)}`);
  });
  await page.goto(url, { waitUntil: "load", timeout: 60000 });
  const { overlay, rendered } = await settle(page);
  report.rendered[s.name] = rendered;
  if (overlay) report.overlay = overlay.slice(0, 600);
  // A phone screen, not the whole scroll: the critique judges what fits.
  await page.screenshot({ path: `${outDir}/${s.name}.jpg`, type: "jpeg", quality: 72, fullPage: false });
  await ctx.close();
}
report.errors = [...new Set(report.errors)].slice(0, 12);
writeFileSync(`${outDir}/report.json`, JSON.stringify(report));
await browser.close();
console.log("ok");
