import { useEffect, useState } from 'react';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';

import api, { getApiErrorMessage } from '../lib/api';
import { AppSettings } from '../lib/types';
import { useAppSettings } from '../components/app-settings-provider';

const languageOptions = [
  { value: 'de', label: 'Deutsch (de)' },
  { value: 'en', label: 'Englisch (en)' },
  { value: 'fr', label: 'Französisch (fr)' },
];

const currencyOptions = [
  { value: 'EUR', label: 'Euro (EUR)' },
  { value: 'USD', label: 'US Dollar (USD)' },
];

function parseSearchLanguages(value: string | undefined): string[] {
  return Array.from(
    new Set(
      (value || 'de,en')
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean),
    ),
  );
}

export default function SettingsPage() {
  const { settings, loading, error, refreshSettings } = useAppSettings();
  const [form, setForm] = useState<AppSettings>(settings);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setForm(settings);
  }, [settings]);

  const updateForm = (patch: Partial<AppSettings>) => setForm((current) => ({ ...current, ...patch }));

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setMessage(null);
    try {
      const response = await api.put<AppSettings>('/settings/', form);
      setForm(response.data);
      await refreshSettings();
      setMessage('Einstellungen gespeichert.');
    } catch (requestError) {
      setSaveError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 3 }}>
        <Typography variant="h4">Einstellungen</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.75 }}>
          Globale Defaults fuer Sprache, Suche, Preisabfragen und Waehrungsanzeige.
        </Typography>
      </Paper>

      {loading ? <Alert severity="info">Einstellungen werden geladen...</Alert> : null}
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {saveError ? <Alert severity="error">{saveError}</Alert> : null}
      {message ? <Alert severity="success">{message}</Alert> : null}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="h6">Waehrung & Sprache</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Diese Werte steuern die Standardanzeige im UI, die Suchdialoge und die Preisaufloesung.
            </Typography>
          </Box>

          <Stack spacing={2} direction={{ xs: 'column', md: 'row' }}>
            <TextField
              select
              fullWidth
              label="Bevorzugte Waehrung"
              value={form.preferred_currency}
              onChange={(event) => updateForm({ preferred_currency: event.target.value as AppSettings['preferred_currency'] })}
            >
              {currencyOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              fullWidth
              label="Bevorzugte Kartensprache"
              value={form.preferred_card_language}
              onChange={(event) => updateForm({ preferred_card_language: event.target.value })}
            >
              {languageOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
          </Stack>

          <Stack spacing={2} direction={{ xs: 'column', md: 'row' }}>
            <TextField
              select
              fullWidth
              label="Bevorzugte Suchsprache"
              value={parseSearchLanguages(form.preferred_search_language)}
              onChange={(event) =>
                updateForm({
                  preferred_search_language: (Array.isArray(event.target.value) ? event.target.value : [event.target.value]).join(','),
                })
              }
              SelectProps={{
                multiple: true,
                renderValue: (selected) => (Array.isArray(selected) ? selected.join(', ').toUpperCase() : String(selected)),
              }}
              helperText="Mehrfachauswahl moeglich. Standard ist DE und EN."
            >
              {languageOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              fullWidth
              label="Bevorzugte Preis-Sprache"
              value={form.preferred_price_language}
              onChange={(event) => updateForm({ preferred_price_language: event.target.value })}
            >
              {languageOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
          </Stack>

          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button startIcon={<SaveRoundedIcon />} variant="contained" onClick={() => void handleSave()} disabled={saving}>
              {saving ? 'Speichern...' : 'Einstellungen speichern'}
            </Button>
          </Box>
        </Stack>
      </Paper>
    </Stack>
  );
}
