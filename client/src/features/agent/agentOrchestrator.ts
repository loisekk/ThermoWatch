import { useAgentStore, type ChatMsg } from './agentStore';
import { TOOL_DEFS, executeTool } from './tools';
import { API_TARGET, apiDiagnostic } from '@/services/api/client';
import { useFireStore } from '@/store/useFireStore';
import { computeKpis, topPersistent } from '@/selectors/fireSelectors';

const SYSTEM = `You are the ThermoWatch operations agent (SIH26162, NTRO). You answer using tools that query a
near-real-time (FIRMS 3-6h latency) industrial fire classification system. Classes: industrial, persistent,
wildfire, agricultural. Always state confidence/limits honestly. Never claim real-time.`;

/** BYO-key tool-calling loop. Key stays in the browser; tools hit our FastAPI only. */
export async function runAgent(userText: string): Promise<void> {
  const st = useAgentStore.getState();
  st.push({ role: 'user', content: userText });
  st.setBusy(true);
  const history: ChatMsg[] = [{ role: 'assistant', content: SYSTEM }, ...st.messages.slice(-12)];

  if (!st.settings.key) { localRulesEngine(userText); st.setBusy(false); return; }

  try {
    let messages = [...history.map((m) => ({ role: m.role, content: m.content, name: m.name }))];
    for (let hop = 0; hop < 4; hop++) {
      const res = await fetch(`${st.settings.baseUrl.replace(/\/$/, '')}/chat/completions`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${st.settings.key}` },
        body: JSON.stringify({ model: st.settings.model, messages, tools: TOOL_DEFS, tool_choice: 'auto' }),
      });
      if (!res.ok) throw new Error(`LLM ${res.status}`);
      const data = await res.json();
      const msg = data.choices?.[0]?.message;
      if (!msg?.tool_calls?.length) {
        useAgentStore.getState().push({
          role: 'assistant',
          content: msg?.content ?? `I couldn't reach the backend via ${API_TARGET}. ${apiDiagnostic()}. Fix: Vercel → Settings → Environment Variables → VITE_API_URL → Redeploy; or locally run the API on 127.0.0.1:8000 (same-origin dev proxy) — restart npm run dev after any vite.config.ts change.`,
        });
        return;
      }
      messages = [...messages, msg];
      for (const call of msg.tool_calls) {
        const out = await executeTool(call.function.name, JSON.parse(call.function.arguments || '{}'));
        useAgentStore.getState().push({ role: 'tool', content: `${call.function.name} → ${out.slice(0, 220)}`, name: call.function.name });
        messages = [...messages, { role: 'tool', tool_call_id: call.id, content: out } as never];
      }
    }
    useAgentStore.getState().push({ role: 'assistant', content: 'Reasoning budget exhausted — see tool outputs above.' });
  } catch (e) {
    useAgentStore.getState().push({ role: 'assistant', content: `Agent error: ${(e as Error).message}. Falling back to local rules.` });
    localRulesEngine(userText);
  } finally {
    useAgentStore.getState().setBusy(false);
  }
}

/** Zero-key deterministic fallback so the demo always answers. */
function localRulesEngine(q: string): void {
  const s = useFireStore.getState();
  const t = q.toLowerCase();
  const k = computeKpis(s.events);
  let out: string;
  if (/how many|count|active/.test(t)) out = `Active (24h): ${k.active24} · industrial share ${Math.round(k.industrialShare)}% · mean confidence ${Math.round(k.meanConfidence)}%. Near-real-time (FIRMS 3-6h latency).`;
  else if (/persist|chronic/.test(t)) {
    const top = topPersistent(s.events, 3);
    out = top.length ? `Top chronic sources: ${top.map((e) => `${e.id} (${e.persistence.consecutiveDays}d)`).join(', ')}.` : 'No persistent sources in window.';
  } else if (/spread|predict|model/.test(t)) out = 'Open the PREDICT panel to run the classification model with your own parameters, or add an LLM API key so I can run it inline via tw_run_model.';
  else out = `KPI snapshot — active24: ${k.active24}, persistent: ${k.persistentCount}, open alerts: ${s.alerts.filter((a) => a.status !== 'resolved').length}. Ask "how many fires", "persistent sources", or "predict".`;
  useAgentStore.getState().push({ role: 'assistant', content: out });
}
