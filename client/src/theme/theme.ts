import { createTheme } from '@mui/material/styles';

/** MUI layer tuned to the ThermoWatch instrument tokens (single coherent system). */
export const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#FF6B35' },
    secondary: { main: '#FFB800' },
    error: { main: '#FF4444' },
    success: { main: '#3FB950' },
    info: { main: '#7D8DA1' },
    background: { default: '#07090D', paper: '#0E141B' },
    text: { primary: '#E8EEF5', secondary: '#8CA0B3' },
  },
  typography: {
    fontFamily: '"Space Grotesk", system-ui, sans-serif',
    button: { textTransform: 'none', fontWeight: 600 },
  },
  shape: { borderRadius: 6 },
  components: {
    MuiPaper: { styleOverrides: { root: { backgroundImage: 'none', border: '1px solid #1D2833' } } },
    MuiButton: { styleOverrides: { root: { letterSpacing: '0.06em' } } },
    MuiTextField: { defaultProps: { size: 'small' } },
  },
});
