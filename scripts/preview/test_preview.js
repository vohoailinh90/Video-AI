// Load a built preview page in headless Chromium the way the viewer does (a skeleton around the content) under four media
// content-security policies, then switch voice and jump to a line.
//
// usage: NODE_PATH=$(npm root -g) node scripts/preview/test_preview.js build/preview/index.html build/preview/test
//
// Needs Playwright (present in the Claude Code cloud image). That Chromium has no H.264, so it plays the WebM fallback; a
// passing run proves the page logic, not that a given viewer allows blob: or data: media.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [built, outDir] = process.argv.slice(2);
if (!built || !outDir) {
  console.error("usage: node test_preview.js <built-index.html> <out-dir>");
  process.exit(2);
}
const content = fs.readFileSync(built, "utf8");
fs.mkdirSync(outDir, { recursive: true });

const skeleton = (csp) =>
  '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">' +
  (csp ? `<meta http-equiv="Content-Security-Policy" content="${csp}">` : "") +
  "</head><body>" + content + "</body></html>";

const CASES = [
  ["A no CSP", "", "expect: plays"],
  ["B media-src data: only (blob blocked)", "media-src data:", "expect: plays through the data: fallback"],
  ["C media-src blob: only (data blocked)", "media-src blob:", "expect: plays through blob:"],
  ["D media-src 'none'", "media-src 'none'", "expect: the diagnostic message, no crash"],
];

const state = (page) =>
  page.evaluate(() => {
    const v = document.getElementById("player");
    return {
      status: document.getElementById("status").textContent,
      readyState: v.readyState,
      duration: v.duration ? +v.duration.toFixed(2) : null,
      srcKind: (v.currentSrc || "").split(":")[0],
      errorCode: v.error ? v.error.code : null,
    };
  });
const settled = (page) =>
  page.waitForFunction(() => /^(Đang dùng|Không phát)/.test(document.getElementById("status").textContent), null, { timeout: 90000 });

(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  console.log("browser:", browser.version());
  let failed = 0;
  for (const [name, csp, expectation] of CASES) {
    const file = path.resolve(outDir, name.split(" ")[0] + ".html");
    fs.writeFileSync(file, skeleton(csp));
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
    await page.goto(require("url").pathToFileURL(file).href);
    try { await settled(page); } catch (e) { errors.push("timeout waiting for a final status"); }
    const info = await state(page);
    console.log(`\n[${name}] ${expectation}\n  ${JSON.stringify(info)}`, errors.length ? errors : "");
    const playing = info.readyState >= 1;
    if ((name.startsWith("D") && playing) || (!name.startsWith("D") && !playing) || errors.length) failed++;

    if (name.startsWith("A") && playing) {
      await page.screenshot({ path: path.join(outDir, "desktop.png"), fullPage: true });
      await page.click('.timeline button[data-t="4.1"]');
      await page.waitForTimeout(1500);
      const seek = await page.evaluate(() => { const v = document.getElementById("player"); return { t: +v.currentTime.toFixed(2), paused: v.paused }; });
      console.log("  after clicking the 0:04 line:", JSON.stringify(seek));
      if (seek.t < 4.1 || seek.paused) failed++;

      const voices = await page.$$(".voice");
      if (voices.length > 1) {
        const before = await page.evaluate(() => document.getElementById("player").currentSrc);
        await voices[1].click();
        await page.waitForFunction(() => /^Đang dùng/.test(document.getElementById("status").textContent), null, { timeout: 90000 });
        await page.waitForTimeout(800);
        const after = await page.evaluate(() => {
          const v = document.getElementById("player");
          return { src: v.currentSrc, t: +v.currentTime.toFixed(2), paused: v.paused, pressed: [...document.querySelectorAll(".voice")].map((b) => b.getAttribute("aria-pressed")) };
        });
        console.log("  after switching voice:", JSON.stringify({ srcChanged: after.src !== before, t: after.t, paused: after.paused, pressed: after.pressed }));
        if (after.src === before || after.t < 4.1 || after.pressed.join() !== "false,true") failed++;
      }
      await page.setViewportSize({ width: 390, height: 800 });
      await page.screenshot({ path: path.join(outDir, "phone.png"), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      console.log("  horizontal overflow at 390px:", overflow);
      if (overflow > 0) failed++;
    }
    await page.close();
  }
  await browser.close();
  console.log(failed ? `\nFAILED checks: ${failed}` : "\nall checks passed");
  process.exit(failed ? 1 : 0);
})();
