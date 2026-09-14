/** S25 no-img gate — scene surfaces must never contain <img> elements (the
 *  broken-glyph class); callouts/arrows are inline SVG or canvas sprites. */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const roots = ['client/src/components/detail', 'client/src/features/scene'];
const bad = [];
const walk = (d) => {
  for (const e of readdirSync(d)) {
    const p = join(d, e);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(tsx?|jsx?)$/.test(p) && /<img[\s>]/.test(readFileSync(p, 'utf8'))) bad.push(p);
  }
};
roots.forEach(walk);
if (bad.length) {
  console.error('scene surfaces must not contain <img>:', bad);
  process.exit(1);
}
console.log('no-img gate: ok');