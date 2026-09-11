import { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import SaveIcon from '@mui/icons-material/Save';
import SettingsIcon from '@mui/icons-material/Settings';
import SendIcon from '@mui/icons-material/Send';
import { runAgent } from './agentOrchestrator';
import { useAgentStore, type AgentSettings } from './agentStore';

export function AgentChatPanel() {
  const messages = useAgentStore((s) => s.messages);
  const busy = useAgentStore((s) => s.busy);
  const settings = useAgentStore((s) => s.settings);
  const saveSettings = useAgentStore((s) => s.saveSettings);
  const [text, setText] = useState('');
  const [cfgOpen, setCfgOpen] = useState(false);
  const [draft, setDraft] = useState<AgentSettings>(settings);
  const [savedFlash, setSavedFlash] = useState(false);
  const [testState, setTestState] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');

  const dirty = useMemo(
    () => draft.baseUrl !== settings.baseUrl || draft.model !== settings.model || draft.key !== settings.key,
    [draft, settings],
  );

  const testConnection = async () => {
    setTestState('testing');
    try {
      const res = await fetch(`${draft.baseUrl.replace(/\/$/, '')}/models`, {
        headers: { authorization: `Bearer ${draft.key}` },
      });
      setTestState(res.ok ? 'ok' : 'fail');
    } catch {
      setTestState('fail');
    }
  };

  const send = () => {
    const t = text.trim();
    if (!t || busy) return;
    setText('');
    void runAgent(t);
  };

  return (
    <Paper sx={{ display: 'flex', flexDirection: 'column', height: '100%', p: 1.5, gap: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="overline" color="text.secondary">AI Ops Agent · BYO key</Typography>
        <IconButton size="small" onClick={() => setCfgOpen((v) => !v)} aria-label="Agent settings"><SettingsIcon fontSize="inherit" /></IconButton>
      </Box>

      {cfgOpen && (
        <Box sx={{ display: 'grid', gap: 1.5, borderRadius: 1, border: '1px solid', borderColor: 'divider', p: 1.5 }}>
          <TextField label="Base URL" size="small" fullWidth value={draft.baseUrl} onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })} />
          <TextField label="Model" size="small" fullWidth value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} />
          <TextField label="API key (stored locally only)" size="small" fullWidth type="password" value={draft.key} onChange={(e) => setDraft({ ...draft, key: e.target.value })} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Button
              variant="contained" size="small" startIcon={<SaveIcon />} disabled={!dirty}
              onClick={() => { saveSettings(draft); setSavedFlash(true); window.setTimeout(() => setSavedFlash(false), 1600); }}
            >
              Save
            </Button>
            <Button variant="outlined" size="small" disabled={!dirty} onClick={() => setDraft(settings)}>Cancel</Button>
            <Button variant="text" size="small" onClick={testConnection} disabled={!draft.key || testState === 'testing'}>
              {testState === 'testing' ? 'Testing…' : 'Test connection'}
            </Button>
            {savedFlash && <Chip size="small" color="success" label="saved ✓" />}
            {testState === 'ok' && <Chip size="small" color="success" label="endpoint reachable" />}
            {testState === 'fail' && <Chip size="small" color="error" label="unreachable / bad key" />}
          </Box>
          <Typography variant="caption" color="text.secondary">
            The key never leaves this browser — requests go directly to your provider.
          </Typography>
        </Box>
      )}

      <Box sx={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1 }}>
        {messages.map((m, i) => (
          <Box key={i} sx={{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%', borderRadius: 1, px: 1.2, py: 0.8, fontSize: 12, lineHeight: 1.5, bgcolor: m.role === 'user' ? 'primary.main' : m.role === 'tool' ? 'background.default' : 'action.selected', color: m.role === 'user' ? '#07090D' : 'text.primary', fontFamily: m.role === 'tool' ? 'IBM Plex Mono, monospace' : undefined }}>
            {m.content}
          </Box>
        ))}
        {busy && <CircularProgress size={16} sx={{ alignSelf: 'center' }} />}
      </Box>

      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField fullWidth placeholder="Ask or command the agent…" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} />
        <Button variant="contained" onClick={send} disabled={busy} aria-label="Send"><SendIcon fontSize="small" /></Button>
      </Box>
    </Paper>
  );
}
