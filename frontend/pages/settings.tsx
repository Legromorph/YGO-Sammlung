import { ChangeEvent, useEffect, useRef, useState } from 'react';
import CloudUploadRoundedIcon from '@mui/icons-material/CloudUploadRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';

import api, { getApiErrorMessage } from '../lib/api';
import PageHeader from '../components/page-header';
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
  const [downloading, setDownloading] = useState<'csv' | 'json' | 'backup' | null>(null);
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const restoreInputRef = useRef<HTMLInputElement | null>(null);

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

  const downloadBlob = async (endpoint: string, fallbackFilename: string) => {
    const response = await api.get<Blob>(endpoint, { responseType: 'blob' });
    const disposition = response.headers['content-disposition'] || '';
    const filename =
      disposition.match(/filename="?([^";]+)"?/i)?.[1] ||
      fallbackFilename;
    const objectUrl = URL.createObjectURL(response.data);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  };

  const handleDownload = async (format: 'csv' | 'json') => {
    setDownloading(format);
    setSaveError(null);
    try {
      const endpoint = format === 'csv' ? '/exports/inventory.csv' : '/exports/collection.json';
      await downloadBlob(endpoint, `ygo-sammlung.${format}`);
    } catch (requestError) {
      setSaveError(getApiErrorMessage(requestError));
    } finally {
      setDownloading(null);
    }
  };

  const handleBackupDownload = async () => {
    setDownloading('backup');
    setSaveError(null);
    setMessage(null);
    try {
      await downloadBlob('/backups/download', 'ygo-sammlung-backup.zip');
    } catch (requestError) {
      setSaveError(getApiErrorMessage(requestError));
    } finally {
      setDownloading(null);
    }
  };

  const handleRestoreFileSelected = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    event.target.value = '';
    if (!file) {
      return;
    }
    setRestoreFile(file);
    setRestoreConfirmOpen(true);
    setSaveError(null);
    setMessage(null);
  };

  const handleRestore = async () => {
    if (!restoreFile) {
      return;
    }
    setRestoring(true);
    setSaveError(null);
    setMessage(null);
    try {
      const formData = new FormData();
      formData.append('backup', restoreFile);
      await api.post('/backups/restore', formData);
      setMessage('Backup eingespielt. Die Seite wird neu geladen...');
      window.setTimeout(() => window.location.reload(), 900);
    } catch (requestError) {
      setSaveError(getApiErrorMessage(requestError));
    } finally {
      setRestoring(false);
      setRestoreConfirmOpen(false);
      setRestoreFile(null);
    }
  };

  return (
    <Stack spacing={3}>
      <PageHeader title="Einstellungen" description="Standards für Sprache, Suche, Preise und Währung." />

      {loading ? <Alert severity="info">Einstellungen werden geladen...</Alert> : null}
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {saveError ? <Alert severity="error">{saveError}</Alert> : null}
      {message ? <Alert severity="success">{message}</Alert> : null}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="h6">Währung & Sprache</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Diese Werte steuern die Standardanzeige im UI, die Suchdialoge und die Preisauflösung.
            </Typography>
          </Box>

          <Stack spacing={2} direction={{ xs: 'column', md: 'row' }}>
            <TextField
              select
              fullWidth
              label="Bevorzugte Währung"
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
              helperText="Mehrfachauswahl möglich. Standard ist DE und EN."
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

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Typography variant="h6">Sammlung exportieren</Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
            <Button
              startIcon={<DownloadRoundedIcon />}
              variant="outlined"
              disabled={downloading !== null}
              onClick={() => void handleDownload('csv')}
            >
              {downloading === 'csv' ? 'CSV wird erstellt...' : 'Inventar als CSV'}
            </Button>
            <Button
              startIcon={<DownloadRoundedIcon />}
              variant="outlined"
              disabled={downloading !== null}
              onClick={() => void handleDownload('json')}
            >
              {downloading === 'json' ? 'JSON wird erstellt...' : 'Sammlung als JSON'}
            </Button>
          </Stack>
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h6">Backup</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Erstellt ein ZIP-Backup mit Datenbankexport und gespeicherten Kartenbildern.
            </Typography>
          </Box>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
            <Button
              startIcon={<DownloadRoundedIcon />}
              variant="contained"
              disabled={downloading !== null || restoring}
              onClick={() => void handleBackupDownload()}
            >
              {downloading === 'backup' ? 'Backup wird erstellt...' : 'Backup herunterladen'}
            </Button>
            <Button
              startIcon={<CloudUploadRoundedIcon />}
              variant="outlined"
              color="warning"
              disabled={downloading !== null || restoring}
              onClick={() => restoreInputRef.current?.click()}
            >
              {restoring ? 'Backup wird eingespielt...' : 'Backup einspielen'}
            </Button>
            <input
              ref={restoreInputRef}
              type="file"
              accept=".zip,application/zip"
              hidden
              onChange={handleRestoreFileSelected}
            />
          </Stack>
        </Stack>
      </Paper>

      <Dialog
        open={restoreConfirmOpen}
        onClose={() => {
          if (!restoring) {
            setRestoreConfirmOpen(false);
          }
        }}
      >
        <DialogTitle>Backup einspielen?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Das aktuelle Inventar, Decks, Sammlungen, Preisverläufe, Jobs und gespeicherte Bilder werden durch das ausgewählte Backup ersetzt.
          </DialogContentText>
          {restoreFile ? (
            <Typography sx={{ mt: 2 }} variant="body2">
              Datei: {restoreFile.name}
            </Typography>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button disabled={restoring} onClick={() => setRestoreConfirmOpen(false)}>
            Abbrechen
          </Button>
          <Button color="warning" variant="contained" disabled={restoring} onClick={() => void handleRestore()}>
            {restoring ? 'Wird eingespielt...' : 'Einspielen'}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
