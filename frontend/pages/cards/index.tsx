import Link from 'next/link';
import { useEffect, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import axios from 'axios';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

import CardFormDialog from '../../components/card-form-dialog';
import PageHeader from '../../components/page-header';
import api, { buildQuery, getApiErrorMessage, resolveMediaUrl } from '../../lib/api';
import { formatCurrency, formatPercent } from '../../lib/format';
import { pricingColor, pricingLabel, pricingUpdateLabel } from '../../lib/pricing';
import { CardDetail, CardFilterOptions, CardListResponse, CardPayload, CardSummary } from '../../lib/types';

type DuplicateCardConflict = {
  code: 'duplicate_card';
  message: string;
  existing_item_id: number;
  existing_quantity: number;
  increment_by: number;
  suggested_quantity: number;
  signature?: {
    name?: string;
    set_code?: string | null;
    language?: string;
    condition?: string;
  };
};

function isDuplicateCardConflict(value: unknown): value is DuplicateCardConflict {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return candidate.code === 'duplicate_card' && typeof candidate.existing_item_id === 'number' && typeof candidate.existing_quantity === 'number';
}

export default function CardsPage() {
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(12);
  const [filters, setFilters] = useState<CardFilterOptions | null>(null);
  const [query, setQuery] = useState('');
  const [language, setLanguage] = useState('');
  const [rarity, setRarity] = useState('');
  const [condition, setCondition] = useState('');
  const [storageLocationId, setStorageLocationId] = useState('');
  const [hasImage, setHasImage] = useState('all');
  const [hasPrice, setHasPrice] = useState('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingCard, setEditingCard] = useState<CardDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [duplicateSaveLoading, setDuplicateSaveLoading] = useState(false);
  const [pendingCreatePayload, setPendingCreatePayload] = useState<CardPayload | null>(null);
  const [duplicateConflict, setDuplicateConflict] = useState<DuplicateCardConflict | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadCards = async () => {
    setLoading(true);
    try {
      const queryString = buildQuery({
        page: page + 1,
        page_size: pageSize,
        q: query,
        language: language || undefined,
        rarity,
        condition,
        storage_location_id: storageLocationId || undefined,
        has_image: hasImage === 'all' ? undefined : hasImage === 'yes',
        has_price: hasPrice === 'all' ? undefined : hasPrice === 'yes',
      });
      const response = await api.get<CardListResponse>(`/cards/${queryString}`);
      setCards(response.data.items);
      setTotal(response.data.total);
      setError(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadCards();
  }, [page, pageSize, query, language, rarity, condition, storageLocationId, hasImage, hasPrice]);

  useEffect(() => {
    let active = true;
    const loadFilters = async () => {
      try {
        const response = await api.get<CardFilterOptions>('/cards/filters');
        if (active) {
          setFilters(response.data);
        }
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      }
    };
    void loadFilters();
    return () => {
      active = false;
    };
  }, []);

  const openCreateDialog = () => {
    setEditingCard(null);
    setDuplicateConflict(null);
    setPendingCreatePayload(null);
    setDialogOpen(true);
  };

  const openEditDialog = async (cardId: number) => {
    try {
      const response = await api.get<CardDetail>(`/cards/${cardId}`);
      setEditingCard(response.data);
      setDuplicateConflict(null);
      setPendingCreatePayload(null);
      setDialogOpen(true);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  const handleSave = async (payload: CardPayload) => {
    setSaving(true);
    try {
      if (editingCard) {
        await api.put(`/cards/${editingCard.id}`, payload);
      } else {
        await api.post('/cards/', payload);
      }
      setDialogOpen(false);
      setEditingCard(null);
      setDuplicateConflict(null);
      setPendingCreatePayload(null);
      await loadCards();
    } catch (requestError) {
      if (!editingCard && axios.isAxiosError(requestError) && requestError.response?.status === 409) {
        const detail = requestError.response?.data?.detail;
        if (isDuplicateCardConflict(detail)) {
          setPendingCreatePayload(payload);
          setDuplicateConflict(detail);
          setError(null);
          return;
        }
      }
      setError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const handleIncreaseDuplicateQuantity = async () => {
    if (!pendingCreatePayload || !duplicateConflict) {
      return;
    }
    setDuplicateSaveLoading(true);
    try {
      await api.post('/cards/', {
        ...pendingCreatePayload,
        increment_existing_quantity_on_duplicate: true,
      });
      setDuplicateConflict(null);
      setPendingCreatePayload(null);
      setDialogOpen(false);
      setEditingCard(null);
      await loadCards();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setDuplicateSaveLoading(false);
    }
  };

  const handleDelete = async (cardId: number) => {
    if (!window.confirm('Diese Kartenposition wirklich löschen?')) {
      return;
    }

    try {
      await api.delete(`/cards/${cardId}`);
      await loadCards();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Karten"
        description="Inventar durchsuchen, Preise prüfen und Karten bearbeiten."
        action={
          <Button startIcon={<AddRoundedIcon />} variant="contained" onClick={openCreateDialog}>
            Karte anlegen
          </Button>
        }
      />

      {error ? <Alert severity="error">{error}</Alert> : null}

      <Paper sx={{ p: 2.5 }}>
        <Box sx={{ display: 'grid', gap: 1.25, gridTemplateColumns: { xs: '1fr', md: '2fr 1fr 1fr 1fr 1fr 1fr' } }}>
          <TextField label="Suche" value={query} onChange={(event) => setQuery(event.target.value)} />
          <TextField select label="Sprache" value={language} onChange={(event) => setLanguage(event.target.value)}>
            <MenuItem value="">Alle</MenuItem>
            <MenuItem value="de">Deutsch</MenuItem>
            <MenuItem value="en">Englisch</MenuItem>
            <MenuItem value="fr">Französisch</MenuItem>
          </TextField>
          <TextField select label="Seltenheit" value={rarity} onChange={(event) => setRarity(event.target.value)}>
            <MenuItem value="">Alle</MenuItem>
            {(filters?.rarities || []).map((option) => (
              <MenuItem key={option} value={option}>
                {option}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Zustand" value={condition} onChange={(event) => setCondition(event.target.value)}>
            <MenuItem value="">Alle</MenuItem>
            {(filters?.conditions || []).map((option) => (
              <MenuItem key={option} value={option}>
                {option}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Lagerort" value={storageLocationId} onChange={(event) => setStorageLocationId(event.target.value)}>
            <MenuItem value="">Alle</MenuItem>
            {(filters?.storage_locations || []).map((location) => (
              <MenuItem key={location.id} value={location.id}>
                {location.path_cache}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Bild" value={hasImage} onChange={(event) => setHasImage(event.target.value)}>
            <MenuItem value="all">Alle</MenuItem>
            <MenuItem value="yes">Mit Bild</MenuItem>
            <MenuItem value="no">Ohne Bild</MenuItem>
          </TextField>
          <TextField select label="Preis" value={hasPrice} onChange={(event) => setHasPrice(event.target.value)}>
            <MenuItem value="all">Alle</MenuItem>
            <MenuItem value="yes">Mit Preis</MenuItem>
            <MenuItem value="no">Ohne Preis</MenuItem>
          </TextField>
        </Box>
      </Paper>

      <Paper sx={{ overflow: 'hidden' }}>
        {loading ? (
          <Box sx={{ p: 5, display: 'grid', placeItems: 'center' }}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Karte</TableCell>
                  <TableCell>Set</TableCell>
                  <TableCell>Lagerort</TableCell>
                  <TableCell align="right">Menge</TableCell>
                  <TableCell align="right">Marktpreis</TableCell>
                  <TableCell align="right">7d</TableCell>
                  <TableCell align="right">Aktionen</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {cards.map((card) => {
                  const pricingTooltip = [
                    card.pricing.note,
                    card.pricing.source ? `Quelle: ${card.pricing.source}` : null,
                    card.pricing.last_updated_at
                      ? `Letztes Preisupdate: ${new Date(card.pricing.last_updated_at).toLocaleString('de-DE')}`
                      : null,
                    [card.set_code, card.rarity, card.language?.toUpperCase()].filter(Boolean).join(' | '),
                  ]
                    .filter(Boolean)
                    .join(' \n');

                  return (
                    <TableRow key={card.id} hover>
                      <TableCell>
                        <Stack direction="row" spacing={1.5} alignItems="center">
                          <Avatar src={resolveMediaUrl(card.image_url)} variant="rounded" sx={{ width: 54, height: 72 }} />
                          <Box>
                            <Link href={`/cards/${card.id}`}>
                              <Typography fontWeight={700}>{card.name}</Typography>
                            </Link>
                            <Typography variant="body2" color="text.secondary">
                              {card.card_type || 'Keine Typinfo'} {card.attribute ? `| ${card.attribute}` : ''}
                            </Typography>
                            <Stack direction="row" spacing={0.75} sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
                              {card.rarity ? <Chip label={card.rarity} size="small" variant="outlined" /> : null}
                              <Chip label={card.condition} size="small" color="secondary" variant="outlined" />
                              <Tooltip title={pricingTooltip || 'Kein Preisstatus vorhanden'}>
                                <Chip label={pricingLabel(card.pricing)} size="small" color={pricingColor(card.pricing)} variant="outlined" />
                              </Tooltip>
                              {pricingUpdateLabel(card.pricing) ? (
                                <Chip label={pricingUpdateLabel(card.pricing)} size="small" color="warning" variant="outlined" />
                              ) : null}
                            </Stack>
                          </Box>
                        </Stack>
                      </TableCell>
                      <TableCell>
                        <Typography fontWeight={700}>{card.set_code || 'Kein Setcode'}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {card.set_name || 'Kein Setname'}
                        </Typography>
                      </TableCell>
                      <TableCell>{card.storage_path || 'Nicht zugewiesen'}</TableCell>
                      <TableCell align="right">{card.quantity}</TableCell>
                      <TableCell align="right">{formatCurrency(card.current_market_price, card.current_price_currency)}</TableCell>
                      <TableCell align="right">
                        <Typography color={(card.price_change_7d || 0) >= 0 ? 'success.main' : 'error.main'}>{formatPercent(card.price_change_7d)}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <IconButton onClick={() => void openEditDialog(card.id)}>
                          <EditRoundedIcon />
                        </IconButton>
                        <IconButton color="error" onClick={() => void handleDelete(card.id)}>
                          <DeleteOutlineRoundedIcon />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <TablePagination
              component="div"
              count={total}
              page={page}
              onPageChange={(_, nextPage) => setPage(nextPage)}
              rowsPerPage={pageSize}
              onRowsPerPageChange={(event) => {
                setPageSize(parseInt(event.target.value, 10));
                setPage(0);
              }}
              rowsPerPageOptions={[12, 24, 48]}
            />
          </>
        )}
      </Paper>

      <Dialog
        open={Boolean(duplicateConflict)}
        onClose={() => {
          if (duplicateSaveLoading) {
            return;
          }
          setDuplicateConflict(null);
          setPendingCreatePayload(null);
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Identische Karte bereits vorhanden</DialogTitle>
        <DialogContent>
          <Typography>
            {duplicateConflict?.message ||
              'Diese Kartenposition existiert bereits. Du kannst die bestehende Menge erhöhen oder die Eingaben weiter bearbeiten.'}
          </Typography>
          {duplicateConflict ? (
            <Typography color="text.secondary" sx={{ mt: 1.25 }}>
              Bestand aktuell: {duplicateConflict.existing_quantity}. Vorschlag: +{duplicateConflict.increment_by} auf {duplicateConflict.suggested_quantity}.
            </Typography>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDuplicateConflict(null);
              setPendingCreatePayload(null);
            }}
            disabled={duplicateSaveLoading}
          >
            Weiter bearbeiten
          </Button>
          <Button
            variant="contained"
            onClick={() => void handleIncreaseDuplicateQuantity()}
            disabled={duplicateSaveLoading}
          >
            {duplicateSaveLoading
              ? 'Erhöhe Menge...'
              : `Menge um +${duplicateConflict?.increment_by ?? 1} erhöhen`}
          </Button>
        </DialogActions>
      </Dialog>

      <CardFormDialog
        open={dialogOpen}
        title={editingCard ? `Karte bearbeiten: ${editingCard.name}` : 'Neue Kartenposition'}
        initialValue={editingCard}
        storageLocations={filters?.storage_locations || []}
        loading={saving || duplicateSaveLoading}
        onClose={() => {
          setDialogOpen(false);
          setEditingCard(null);
          setDuplicateConflict(null);
          setPendingCreatePayload(null);
        }}
        onSubmit={handleSave}
      />
    </Stack>
  );
}
