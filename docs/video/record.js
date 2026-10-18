// Records the demo clips. Usage: node record.js <clip>   (clip: page | browser)
const { chromium } = require("playwright");
const fs = require("fs");
const URL = "https://handoff-graph.up.railway.app/";
const FB = "http://localhost:3001";
const FBQ = FB + "/graph?graph=hg:microsoft:vscode&query=MATCH+(a:Person+%7Blogin:'benibenj'%7D)-%5Bh:HANDED_OFF%5D-%3E(b:Person)%0ARETURN+a,+h,+b+LIMIT+60&view=Graph&layout=force";
const W = 1920, H = 1080;

// A visible cursor (headless recordings have none) and a click ripple.
const CURSOR = `
(() => {
  if (window.__cur) return; window.__cur = 1;
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);transition:transform .05s';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const add = () => document.body && document.body.appendChild(c);
  add(); document.addEventListener('DOMContentLoaded', add);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', e => {
    const r = document.createElement('div');
    r.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;border-radius:50%;border:3px solid #2F5FE0;left:'+(e.clientX-7)+'px;top:'+(e.clientY-7)+'px;transition:all .45s ease-out;opacity:.9';
    document.body.appendChild(r);
    requestAnimationFrame(() => { r.style.transform = 'scale(3.2)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
})();`;

const log = [];
let t0;
const mark = (name) => { log.push({ name, t: (Date.now() - t0) / 1000 }); console.log(name, ((Date.now() - t0) / 1000).toFixed(2)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function glide(page, loc, opts = {}) {
  await loc.scrollIntoViewIfNeeded(); await sleep(350);
  const b = await loc.boundingBox();
  const x = b.x + (opts.dx ?? b.width / 2), y = b.y + (opts.dy ?? b.height / 2);
  await page.mouse.move(x, y, { steps: 28 });
  await sleep(250);
  return { x, y };
}
async function click(page, loc, opts) { const { x, y } = await glide(page, loc, opts); await page.mouse.down(); await sleep(70); await page.mouse.up(); }

async function waitLive(page) {
  // A live answer replaces the "Recorded answer" note; wait for the request to finish.
  await page.waitForResponse((r) => r.url().includes("/api/route") && r.request().method() === "POST", { timeout: 60000 });
  await page.waitForFunction(() => !document.querySelector("#verdict .recorded"), null, { timeout: 15000 }).catch(() => {});
  await sleep(400);
}

(async () => {
  const which = process.argv[2];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1,
    recordVideo: { dir: `clips/raw-${which}`, size: { width: 1920, height: 1080 } } });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  t0 = Date.now();

  if (which === "page") {
    await page.goto(URL, { waitUntil: "networkidle" });
    await page.mouse.move(W * 0.25, H * 0.35);
    await sleep(1500); mark("s1_start"); await sleep(15000);

    // Shot 2a: route
    mark("s2a_start");
    await click(page, page.locator('#issues button[data-i="0"]'));
    await sleep(600);
    const go = page.locator("#go");
    const p1 = waitLive(page); await click(page, go); await p1; mark("s2a_result"); await sleep(17000);
    // Shot 2b: ask a human (#341402)
    mark("s2b_start");
    const b = page.locator('#issues button[data-i="6"]');
    await b.scrollIntoViewIfNeeded(); await sleep(400);
    await click(page, b); await sleep(600);
    const p2 = waitLive(page); await click(page, go); await p2; mark("s2b_result"); await sleep(10000);
    // Shot 2c: keep (#341245)
    mark("s2c_start");
    const c = page.locator('#issues button[data-i="2"]');
    await c.scrollIntoViewIfNeeded(); await sleep(400);
    await click(page, c); await sleep(600);
    const p3 = waitLive(page); await click(page, go); await p3; mark("s2c_result"); await sleep(15000);

    // Shot 4: results via the command palette
    mark("s4_start");
    await page.keyboard.press("Meta+k"); await sleep(900);
    await page.keyboard.type("Results", { delay: 90 }); await sleep(700);
    await page.keyboard.press("Enter"); await sleep(1500);
    mark("s4_band"); await sleep(34000);
    // Shot 5: limits
    mark("s5_start");
    await page.evaluate(() => document.querySelector("#limits").scrollIntoView({ behavior: "smooth", block: "start" }));
    await sleep(1500); mark("s5_limits"); await sleep(26000);
    // Shot 6: palette with the MCP item
    mark("s6_start");
    await page.evaluate(() => scrollTo({ top: 0, behavior: "smooth" })); await sleep(1200);
    await page.keyboard.press("Meta+k"); await sleep(900);
    await page.keyboard.type("MCP", { delay: 110 }); await sleep(9000);
    mark("s6_end");
  }

  if (which === "browser") {
    await page.goto(FB + "/login", { waitUntil: "networkidle" });
    await page.getByLabel("Host").fill("localhost").catch(() => page.locator("input").nth(0).fill("localhost"));
    await page.getByLabel("Port").fill("6379").catch(() => page.locator("input").nth(1).fill("6379"));
    await page.getByRole("button", { name: "Log in" }).click();
    await sleep(3000);
    await page.goto(FBQ, { waitUntil: "networkidle" });
    await sleep(2000);
    for (const t of ["Skip Tutorial"]) await page.getByText(t).click({ timeout: 2000 }).catch(() => {});
    mark("s3_start");
    await page.mouse.move(W * 0.5, H * 0.5);
    const run = page.getByRole("button", { name: /run the query/i });
    await click(page, run);
    await sleep(3500); mark("s3_graph"); await sleep(32000);
    mark("s3_end");
  }

  fs.writeFileSync(`clips/marks-${which}.json`, JSON.stringify(log, null, 1));
  await ctx.close(); await browser.close();
  const dir = `clips/raw-${which}`; const f = fs.readdirSync(dir).find((x) => x.endsWith(".webm"));
  fs.renameSync(`${dir}/${f}`, `clips/${which}.webm`);
  console.log("saved", `clips/${which}.webm`);
})();
