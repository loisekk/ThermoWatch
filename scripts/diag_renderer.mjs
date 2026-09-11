/* Renderer repro: load app → click MAPLIBRE (2D) → capture crash → click CANVAS →
   switch 3D → click GL → capture state. Ground truth for the renderer-toggle bugs. */
import { existsSync } from 'node:fs';
import puppeteer from 'puppeteer-core';

const EXES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
];
const exe = EXES.find((p) => existsSync(p));
if (!exe) { console.error('NO BROWSER FOUND'); process.exit(2); }

const browser = await puppeteer.launch({
  executablePath: exe,
  headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1400,900'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

page.on('pageerror', (e) => console.log(`[PAGEERROR] ${e.message.slice(0, 200)}\n  ${(e.stack || '').split('\n').slice(1, 4).join(' | ').slice(0, 220)}`));
page.on('console', (m) => { const t = m.text(); if (!t.startsWith('[vite]') && !t.includes('React DevTools')) console.log(`[console:${m.type()}]`, t.slice(0, 220)); });

const clickBtn = async (label) => {
  const ok = await page.evaluate((lbl) => {
    const els = [...document.querySelectorAll('button')];
    const el = els.find((b) => b.textContent.trim().toLowerCase() === lbl.toLowerCase());
    if (!el) return false;
    el.click();
    return true;
  }, label);
  console.log(`[click ${label}] ${ok ? 'ok' : 'BUTTON NOT FOUND'}`);
  return ok;
};

await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 30000 });
await new Promise((r) => setTimeout(r, 5000));

console.log('--- 1) click MAPLIBRE (2D) ---');
await clickBtn('maplibre');
await new Promise((r) => setTimeout(r, 4000));
const s1 = await page.evaluate(() => ({
  badge: [...document.querySelectorAll('span')].map((s) => s.textContent).find((t) => t.includes('ORTHO-2D')) ?? 'none',
  maplibreCanvas: document.querySelectorAll('.maplibregl-canvas').length,
  rootChildren: document.getElementById('root')?.children.length ?? -1,
  bodyTail: document.body.innerText.replace(/\s+/g, ' ').slice(-260),
}));
console.log('[2D-ML]', JSON.stringify(s1));

console.log('--- 2) click CANVAS (2D) ---');
await clickBtn('canvas');
await new Promise((r) => setTimeout(r, 2000));
const s2 = await page.evaluate(() => ({
  badge: [...document.querySelectorAll('span')].map((s) => s.textContent).find((t) => t.includes('ORTHO-2D')) ?? 'none',
  canvasMap: document.querySelectorAll('canvas').length,
}));
console.log('[2D-CV]', JSON.stringify(s2));

console.log('--- 3) 3D + GL ---');
await page.keyboard.press('2');
await new Promise((r) => setTimeout(r, 1500));
await clickBtn('gl');
await new Promise((r) => setTimeout(r, 5000));
const s3 = await page.evaluate(() => ({
  badge: [...document.querySelectorAll('span')].map((s) => s.textContent).find((t) => t.includes('ORB-3D')) ?? 'none',
  glCanvas: document.querySelectorAll('.scene-canvas, canvas').length,
  loadingText: document.body.innerText.includes('Loading globe texture'),
  polygons: document.querySelectorAll('.maplibregl-canvas').length,
}));
console.log('[3D-GL]', JSON.stringify(s3));

await page.screenshot({ path: 'scripts\\diag_renderer.png' });
await browser.close();
console.log('[done] scripts/diag_renderer.png');