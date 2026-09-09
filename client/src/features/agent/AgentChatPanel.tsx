import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import Paper from '@mui/material/Paper';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import SettingsIcon from '@mui/icons-material/Settings';
import SendIcon from '@mui/icons-material/Send';
import { runAgent } from './agentOrchestrator';
import { useAgentStore } from './agentStore';

export function AgentChatPanel() {
  const messages = useAgentStore((s) => s.messages);
  const busy = useAgentStore((s) => s.busy);
  const settings = useAgentStore((s) => s.settings);
  const saveSettings = useAgentStore((s) => s.saveSettings);
  const [text, setText] = useState('');
  const [cfgOpen, setCfgOpen] = useState(false);

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
        <Box sx={{ display: 'grid', gap: 1 }}>
          <TextField label="Base URL" value={settings.baseUrl} onChange={(e) => saveSettings({ ...settings, baseUrl: e.target.value })} />
          <TextField label="Model" value={settings.model} onChange={(e) => saveSettings({ ...settings, model: e.target.value })} />
          <TextField label="API key (stored locally only)" type="password" value={settings.key} onChange={(e) => saveSettings({ ...settings, key: e.target.value })} />
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
