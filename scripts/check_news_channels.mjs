// Resolves/verifies YouTube channel IDs for the LIVE WIRE broadcast strip.
// Exit 1 while any entry is unresolved — paste verified IDs into
// client/src/features/news/channels.ts, re-run until exit 0.
const HANDLES = [
  ["aje", "aljazeeraenglish"],
  ["dw", "dwnews"],
  ["cnbc", "cnbc"],
  ["sky", "skynews"],
  ["wion", "WION"],
  ["f24", "FRANCE24"],
];

let pending = 0;
for (const [key, handle] of HANDLES) {
  try {
    const r = await fetch(`https://www.youtube.com/@${handle}/live`, {
      headers: { "user-agent": "Mozilla/5.0", "accept-language": "en" },
    });
    const html = await r.text();
    const m = html.match(/"channelId":"(UC[\w-]{22})"/)
      || html.match(/"externalId":"(UC[\w-]{22})"/);
    console.log(`${key}\t${m ? m[1] : "NOT_FOUND"}\t@${handle}`);
    if (!m) pending++;
  } catch (e) {
    console.log(`${key}\tFETCH_ERROR\t${e.message}`);
    pending++;
  }
}
process.exit(pending ? 1 : 0);