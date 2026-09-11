import { create } from 'zustand';

export interface ChatMsg { role: 'user' | 'assistant' | 'tool'; content: string; name?: string }
export interface AgentSettings { baseUrl: string; model: string; key: string }

const LS_KEY = 'tw.agent.settings';
const load = (): AgentSettings => {
  try { return { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', key: '', ...JSON.parse(localStorage.getItem(LS_KEY) ?? '{}') }; }
  catch { return { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', key: '' }; }
};

interface AgentState {
  messages: ChatMsg[];
  busy: boolean;
  settings: AgentSettings;
  push: (m: ChatMsg) => void;
  setBusy: (b: boolean) => void;
  saveSettings: (s: AgentSettings) => void;
  clear: () => void;
}

export const useAgentStore = create<AgentState>()((set) => ({
  messages: [{ role: 'assistant', content: 'ThermoWatch agent online. Ask about fire events, persistence or spread — or let me run the ML model for you. (Add your own LLM API key in Settings for full reasoning; without a key I run the local rules engine.)' }],
  busy: false,
  settings: load(),
  push: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setBusy: (busy) => set({ busy }),
  saveSettings: (settings) => { localStorage.setItem(LS_KEY, JSON.stringify(settings)); set({ settings }); },
  clear: () => set({ messages: [] }),
}));
