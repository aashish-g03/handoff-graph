// Renders cards/intro.html frame by frame: node render-intro.js <seconds> [fps]
const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const D = parseFloat(process.argv[2]), FPS = parseInt(process.argv[3] || "30"), OFF = parseFloat(process.argv[4] || "0");
  fs.rmSync("frames", { recursive: true, force: true }); fs.mkdirSync("frames");
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.goto("file://" + __dirname + "/cards/intro.html", { waitUntil: "networkidle" });
  await p.evaluate(() => document.fonts.ready);
  const n = Math.round(D * FPS);
  for (let i = 0; i < n; i++) {
    await p.evaluate((t) => window.render(t), i / FPS - OFF);
    await p.screenshot({ path: `frames/f${String(i).padStart(4, "0")}.png` });
  }
  await b.close();
  console.log("frames", n);
})();
