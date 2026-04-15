import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#d8a94c',
      light: '#f0c979',
      dark: '#8f6420',
    },
    secondary: {
      main: '#4ea28a',
      light: '#7bc3ad',
      dark: '#225f50',
    },
    background: {
      default: '#091110',
      paper: '#0f1b1b',
    },
    text: {
      primary: '#f7f4ea',
      secondary: '#b9c0b1',
    },
    success: {
      main: '#79c582',
    },
    error: {
      main: '#ef6f6c',
    },
    warning: {
      main: '#f4b860',
    },
  },
  typography: {
    fontFamily: '"Manrope", sans-serif',
    h1: { fontWeight: 800 },
    h2: { fontWeight: 800 },
    h3: { fontWeight: 800 },
    h4: { fontWeight: 800 },
    h5: { fontWeight: 750 },
    h6: { fontWeight: 750 },
    button: {
      textTransform: 'none',
      fontWeight: 700,
    },
  },
  shape: {
    borderRadius: 18,
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(216, 169, 76, 0.12)',
          boxShadow: '0 18px 60px rgba(0, 0, 0, 0.22)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          paddingLeft: 18,
          paddingRight: 18,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
        },
      },
    },
  },
});

export default theme;
