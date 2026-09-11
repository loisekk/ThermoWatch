/* Headless diagnosis: load the app in Edge, capture every console message,
   page error, failed request, and the final state of #root. */
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

page.on('console', (m) => console.log(`[console:${m.type()}]`, m.text().slice(0, 500)));
page.on('pageerror', (e) => console.log(`[PAGEERROR] ${e.message}\n${(e.stack || '').split('\n').slice(0, 8).join('\n')}`));
page.on('requestfailed', (r) => console.log(`[reqfail] ${r.url()} :: ${r.failure()?.errorText}`));
page.on('response', (r) => { if (r.status() >= 400) console.log(`[http ${r.status()}] ${r.url()}`); });

try {
  await page.goto('http://localhost:5173/', { waitUntil: 'domcontentloaded', timeout: 30000 });
} catch (e) { console.log('[goto-fail]', e.message); }
await new Promise((r) => setTimeout(r, 6000));

const state = await page.evaluate(() => {
  const root = document.getElementById('root');
  return {
    url: location.href,
    rootChildren: root ? root.children.length : -1,
    rootHtmlStart: root ? root.innerHTML.slice(0, 800) : 'NO #ROOT',
    bodyText: document.body.innerText.replace(/\s+/g, ' ').slice(0, 400),
    canvases: document.querySelectorAll('canvas').length,
  };
});
console.log('[STATE]', JSON.stringify(state, null, 2));
await page.screenshot({ path: 'scripts\\diag_blank.png' });
console.log('[screenshot] scripts/diag_blank.png written');
await browser.close();
