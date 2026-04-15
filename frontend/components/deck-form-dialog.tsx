import { useEffect, useMemo, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';

import CardSearchPicker from './card-search-picker';
import { CardSearchOption } from '../lib/card-search';
import { DeckDetail, DeckPayload } from '../lib/types';

type DeckEditorRow = DeckPayload['cards'][number] & {
  selectedCard?: CardSearchOption | null;
};

interface DeckFormDialogProps {
  open: boolean;
  title: string;
  initialValue?: DeckDetail | null;
  loading?: boolean;
  onClose: () => void;
  onSubmit: (payload: DeckPayload) => Promise<void>;
}

function buildSelectedCard(card: DeckDetail['cards'][number]): CardSearchOption | null {
  if (!card.inventory_item_id) {
    return null;
  }

  return {
    id: card.inventory_item_id,
    name: card.card_name,
    set_code: card.set_code,
    card_number: null,
    rarity: null,
    language: null,
    image_url: null,
    current_price_currency: null,
    storage_path: null,
    quantity: undefined,
    card_type: null,
    attribute: null,
    monster_type: null,
  };
}

export default function DeckFormDialog({
  open,
  title,
  initialValue,
  loading = false,
  onClose,
  onSubmit,
}: DeckFormDialogProps) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'));
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [format, setFormat] = useState('Advanced');
  const [cards, setCards] = useState<DeckEditorRow[]>([]);

  useEffect(() => {
    if (!open) {
      return;
    }

    setName(initialValue?.name || '');
    setDescription(initialValue?.description || '');
    setFormat(initialValue?.format || 'Advanced');
    setCards(
      initialValue?.cards.map((card) => ({
        inventory_item_id: card.inventory_item_id,
        quantity: card.quantity,
        section: card.section,
        is_missing: card.is_missing,
        notes: card.notes || '',
        selectedCard: buildSelectedCard(card),
      })) || []
    );
  }, [initialValue, open]);

  const updateCard = (index: number, patch: Partial<DeckEditorRow>) => {
    setCards((current) => current.map((entry, currentIndex) => (currentIndex === index ? { ...entry, ...patch } : entry)));
  };

  const selectedCardCount = useMemo(() => cards.filter((entry) => entry.inventory_item_id).length, [cards]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth fullScreen={fullScreen} maxWidth="lg">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 2, sm: 3 } }}>
        <Grid container spacing={2} sx={{ mt: 0.25 }}>
          <Grid item xs={12} md={6}>
            <TextField label="Deckname" fullWidth value={name} onChange={(event) => setName(event.target.value)} />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField label="Format" fullWidth value={format} onChange={(event) => setFormat(event.target.value)} />
          </Grid>
          <Grid item xs={12}>
            <TextField label="Beschreibung" fullWidth multiline minRows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
          </Grid>

          <Grid item xs={12}>
            <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2 }, borderColor: 'rgba(255,255,255,0.08)' }}>
              <Stack spacing={1.5}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 2, flexWrap: 'wrap' }}>
                  <Box>
                    <Typography variant="h6">Kartenzuordnung</Typography>
                    <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                      Suche Karten direkt per Tippen statt ueber ein statisches Dropdown. Die Vorschlaege laden live und lassen sich auf allen
                      Bildschirmgroessen gut bedienen.
                    </Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary">
                    {selectedCardCount} von {cards.length} Zeilen zugeordnet
                  </Typography>
                </Box>

                {cards.map((entry, index) => (
                  <Paper
                    key={`${initialValue?.id ?? 'new'}-${entry.inventory_item_id ?? 'new'}-${index}`}
                    variant="outlined"
                    sx={{
                      p: { xs: 1.5, sm: 2 },
                      borderColor: entry.selectedCard ? 'rgba(216,169,76,0.2)' : 'rgba(255,255,255,0.08)',
                      background: entry.selectedCard ? 'rgba(216,169,76,0.04)' : 'rgba(255,255,255,0.02)',
                    }}
                  >
                    <Stack spacing={1.5}>
                      <CardSearchPicker
                        label="Karte suchen"
                        selectedCard={entry.selectedCard || null}
                        placeholder="Name, Set, Setcode, Seltenheit oder Sprache"
                        onSelect={(card) =>
                          updateCard(index, {
                            inventory_item_id: card?.id,
                            selectedCard: card,
                          })
                        }
                      />

                      <Box
                        sx={{
                          display: 'grid',
                          gridTemplateColumns: { xs: '1fr', sm: '140px 120px minmax(0, 1fr) 44px' },
                          gap: 1,
                          alignItems: 'start',
                        }}
                      >
                        <TextField select label="Sektion" value={entry.section} onChange={(event) => updateCard(index, { section: event.target.value })}>
                          <MenuItem value="main">Main</MenuItem>
                          <MenuItem value="extra">Extra</MenuItem>
                          <MenuItem value="side">Side</MenuItem>
                        </TextField>
                        <TextField
                          label="Menge"
                          type="number"
                          value={entry.quantity}
                          onChange={(event) => updateCard(index, { quantity: Number(event.target.value) })}
                          inputProps={{ min: 1, step: 1, inputMode: 'numeric' }}
                        />
                        <TextField
                          label="Notiz"
                          value={entry.notes || ''}
                          onChange={(event) => updateCard(index, { notes: event.target.value })}
                          placeholder="Optional"
                        />
                        <IconButton
                          color="error"
                          onClick={() => setCards((current) => current.filter((_, currentIndex) => currentIndex !== index))}
                          sx={{ alignSelf: 'center', justifySelf: 'flex-end', minWidth: 44, minHeight: 44 }}
                        >
                          <DeleteOutlineRoundedIcon />
                        </IconButton>
                      </Box>
                    </Stack>
                  </Paper>
                ))}

                <Button
                  startIcon={<AddRoundedIcon />}
                  variant="outlined"
                  onClick={() => setCards((current) => [...current, { quantity: 1, section: 'main', is_missing: false, selectedCard: null }])}
                  sx={{ alignSelf: 'flex-start' }}
                >
                  Karte hinzufuegen
                </Button>
              </Stack>
            </Paper>
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions sx={{ px: { xs: 2, sm: 3 }, py: 2, position: fullScreen ? 'sticky' : 'static', bottom: 0, bgcolor: 'background.paper' }}>
        <Button onClick={onClose} disabled={loading}>
          Abbrechen
        </Button>
        <Button
          variant="contained"
          disabled={loading || !name.trim()}
          onClick={() =>
            void onSubmit({
              name,
              description: description || undefined,
              format,
              cards: cards
                .filter((entry) => entry.inventory_item_id)
                .map(({ selectedCard: _selectedCard, ...entry }) => entry),
            })
          }
        >
          Speichern
        </Button>
      </DialogActions>
    </Dialog>
  );
}
