import type { AppProps } from 'next/app';
import '@fontsource/manrope/400.css';
import '@fontsource/manrope/700.css';
import '@fontsource/manrope/800.css';
import '@fontsource/ibm-plex-mono/400.css';
import { CssBaseline, ThemeProvider } from '@mui/material';

import { AppSettingsProvider } from '../components/app-settings-provider';
import AppShell from '../components/app-shell';
import theme from '../lib/theme';
import '../styles/globals.css';

export default function App({ Component, pageProps }: AppProps) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppSettingsProvider>
        <AppShell>
          <Component {...pageProps} />
        </AppShell>
      </AppSettingsProvider>
    </ThemeProvider>
  );
}
