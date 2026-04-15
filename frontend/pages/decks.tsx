import { useEffect, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import { Alert, Box, Button, Chip, CircularProgress, IconButton, Paper, Stack, Typography } from '@mui/material';

import DeckFormDialog from '../components/deck-form-dialog';
import api, { getApiErrorMessage } from '../lib/api';
import { formatCurrency } from '../lib/format';
import { DeckDetail, DeckPayload, DeckSummary } from '../lib/types';

export default function DecksPage() {
  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [editingDeck, setEditingDeck] = useState<DeckDetail | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const decksResponse = await api.get<DeckSummary[]>('/decks/');
      setDecks(decksResponse.data);
      setError(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const loadDeckDetail = async (deckId: number) => {
    try {
      const response = await api.get<DeckDetail>(`/decks/${deckId}`);
      setEditingDeck(response.data);
      setDialogOpen(true);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  const handleSave = async (payload: DeckPayload) => {
    setSaving(true);
    try {
      if (editingDeck) {
        await api.put(`/decks/${editingDeck.id}`, payload);
      } else {
        await api.post('/decks/', payload);
      }
      setDialogOpen(false);
      setEditingDeck(null);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (deckId: number) => {
    if (!window.confirm('Diese Deckliste wirklich loeschen?')) {
      return;
    }
    try {
      await api.delete(`/decks/${deckId}`);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 3, display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Box>
          <Typography variant="h4">Decklisten</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>
            Main-, Extra- und Side-Decks direkt gegen das Inventar referenzieren.
          </Typography>
        </Box>
        <Button
          startIcon={<AddRoundedIcon />}
          variant="contained"
          onClick={() => {
            setEditingDeck(null);
            setDialogOpen(true);
          }}
        >
          Deck anlegen
        </Button>
      </Paper>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {loading ? (
        <CircularProgress />
      ) : (
        <Stack spacing={2.5}>
          {decks.map((deck) => (
            <Paper key={deck.id} sx={{ p: 2.5 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <Box>
                  <Typography variant="h6">{deck.name}</Typography>
                  <Typography color="text.secondary" sx={{ mt: 0.75 }}>
                    {deck.description || 'Keine Beschreibung'}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1}>
                  <Chip label={deck.format} variant="outlined" color="secondary" />
                  <Chip label={`${deck.card_count} Karten`} variant="outlined" />
                  <Chip label={formatCurrency(deck.total_value, deck.display_currency)} color="primary" variant="outlined" />
                  <IconButton onClick={() => void loadDeckDetail(deck.id)}>
                    <EditRoundedIcon />
                  </IconButton>
                  <IconButton color="error" onClick={() => void handleDelete(deck.id)}>
                    <DeleteOutlineRoundedIcon />
                  </IconButton>
                </Stack>
              </Box>
            </Paper>
          ))}
        </Stack>
      )}

      <DeckFormDialog
        open={dialogOpen}
        title={editingDeck ? `Deck bearbeiten: ${editingDeck.name}` : 'Neues Deck'}
        initialValue={editingDeck}
        loading={saving}
        onClose={() => {
          setDialogOpen(false);
          setEditingDeck(null);
        }}
        onSubmit={handleSave}
      />
    </Stack>
  );
}
