import { useEffect, useMemo, useRef, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import AddTaskRoundedIcon from '@mui/icons-material/AddTaskRounded';
import BoltRoundedIcon from '@mui/icons-material/BoltRounded';
import RemoveRoundedIcon from '@mui/icons-material/RemoveRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import {
  Alert,
  Autocomplete,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  Typography,
} from '@mui/material';

import { useAppSettings } from '../components/app-settings-provider';
import { CONDITION_OPTIONS } from '../components/card-form/inventory-fields';
import PageHeader from '../components/page-header';
import SyncJobLogDialog from '../components/sync-job-log-dialog';
import api, { getApiErrorMessage, resolveMediaUrl } from '../lib/api';
import { formatCurrency, formatDate } from '../lib/format';
import { allocatePurchaseTotal, findQuickEntryMatches, parseQuickEntry } from '../lib/set-import';
import {
  AllocationMode,
  BulkSetImportPayload,
  BulkSetImportResponse,
  CardSetSummary,
  SetCardRow,
  SetCardsResponse,
  StorageLocation,
  SyncJob,
} from '../lib/types';

type QuantityMap = Record<number, number>;
type SortField = 'card_number' | 'name' | 'current_market_price' | 'quantity';

function parseMoney(value: string): number | null {
  const normalized = value.trim().replace(',', '.');
  if (!normalized) {
    return null;
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function compareText(left?: string | null, right?: string | null): number {
  return (left || '').localeCompare(right || '', undefined, { numeric: true, sensitivity: 'base' });
}

export default function SetImportPage() {
  const { settings } = useAppSettings();
  const currency = settings.preferred_currency || 'EUR';
  const quickEntryRef = useRef<HTMLInputElement | null>(null);

  const [setOptions, setSetOptions] = useState<CardSetSummary[]>([]);
  const [setSearch, setSetSearch] = useState('');
  const [selectedSet, setSelectedSet] = useState<CardSetSummary | null>(null);
  const [setCards, setSetCards] = useState<SetCardRow[]>([]);
  const [quantities, setQuantities] = useState<QuantityMap>({});
  const [storageLocations, setStorageLocations] = useState<StorageLocation[]>([]);
  const [purchasePrice, setPurchasePrice] = useState('');
  const [allocationMode, setAllocationMode] = useState<AllocationMode>('market_value');
  const [storageLocationId, setStorageLocationId] = useState('');
  const [condition, setCondition] = useState('near_mint');
  const [language, setLanguage] = useState(settings.preferred_card_language || 'de');
  const [notes, setNotes] = useState('');
  const [quickEntry, setQuickEntry] = useState('');
  const [quickEntryCandidates, setQuickEntryCandidates] = useState<SetCardRow[]>([]);
  const [lastAdded, setLastAdded] = useState<{ row: SetCardRow; quantity: number } | null>(null);
  const [filterText, setFilterText] = useState('');
  const [onlySelected, setOnlySelected] = useState(false);
  const [sortField, setSortField] = useState<SortField>('card_number');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [loadingSets, setLoadingSets] = useState(false);
  const [loadingCards, setLoadingCards] = useState(false);
  const [saving, setSaving] = useState(false);
  const [priceSyncJob, setPriceSyncJob] = useState<SyncJob | null>(null);
  const [logJob, setLogJob] = useState<SyncJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<StorageLocation[]>('/storage-locations/')
      .then((response) => setStorageLocations(response.data))
      .catch((requestError) => setError(getApiErrorMessage(requestError)));
  }, []);

  useEffect(() => {
    if (!selectedSet) {
      setLanguage(settings.preferred_card_language || 'de');
    }
  }, [selectedSet, settings.preferred_card_language]);

  useEffect(() => {
    let active = true;
    const handle = window.setTimeout(async () => {
      setLoadingSets(true);
      try {
        const response = await api.get<CardSetSummary[]>('/sets/', { params: { q: setSearch.trim() || undefined, limit: 24 } });
        if (active) {
          setSetOptions(response.data);
        }
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      } finally {
        if (active) {
          setLoadingSets(false);
        }
      }
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(handle);
    };
  }, [setSearch]);

  const loadSetCards = async (setId: number, languageOverride = language, { keepQuantities = false } = {}) => {
    setLoadingCards(true);
    try {
      const response = await api.get<SetCardsResponse>(`/sets/${setId}/cards`, { params: { language: languageOverride } });
      setSelectedSet(response.data.set);
      setSetCards(response.data.items);
      if (!keepQuantities) {
        setQuantities({});
        setLastAdded(null);
      }
      setError(null);
      window.setTimeout(() => quickEntryRef.current?.focus(), 0);
    } catch (requestError) {
      setSetCards([]);
      setQuantities({});
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoadingCards(false);
    }
  };

  useEffect(() => {
    if (!priceSyncJob || !['pending', 'running'].includes(priceSyncJob.status)) {
      return;
    }
    let active = true;
    const interval = window.setInterval(async () => {
      try {
        const response = await api.get<SyncJob>(`/sync/jobs/${priceSyncJob.id}`);
        if (!active) {
          return;
        }
        setPriceSyncJob(response.data);
        if (response.data.status === 'completed' && selectedSet) {
          await loadSetCards(selectedSet.id, language, { keepQuantities: true });
        }
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      }
    }, 2500);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [priceSyncJob, selectedSet]);

  const changeQuantity = (cardPrintId: number, nextQuantity: number) => {
    setSuccess(null);
    setQuantities((current) => {
      const next = { ...current };
      if (nextQuantity <= 0) {
        delete next[cardPrintId];
      } else {
        next[cardPrintId] = nextQuantity;
      }
      return next;
    });
  };

  const addCard = (row: SetCardRow, amount: number) => {
    changeQuantity(row.card_print_id, (quantities[row.card_print_id] || 0) + amount);
    setLastAdded({ row, quantity: (quantities[row.card_print_id] || 0) + amount });
    setQuickEntry('');
    setQuickEntryCandidates([]);
    quickEntryRef.current?.focus();
  };

  const submitQuickEntry = () => {
    const { term, quantity } = parseQuickEntry(quickEntry);
    const matches = findQuickEntryMatches(setCards, term);
    if (matches.length === 1) {
      addCard(matches[0], quantity);
      return;
    }
    setQuickEntryCandidates(matches.slice(0, 8));
    if (!matches.length) {
      setLastAdded(null);
    }
  };

  const purchaseTotal = parseMoney(purchasePrice);
  const selectedRows = useMemo(() => setCards.filter((card) => (quantities[card.card_print_id] || 0) > 0), [quantities, setCards]);
  const allocation = useMemo(
    () =>
      allocatePurchaseTotal(
        purchaseTotal,
        selectedRows.map((card) => ({
          card_print_id: card.card_print_id,
          quantity: quantities[card.card_print_id],
          market_price: card.current_market_price,
        })),
        allocationMode,
      ),
    [allocationMode, purchaseTotal, quantities, selectedRows],
  );
  const totalQuantity = selectedRows.reduce((sum, card) => sum + quantities[card.card_print_id], 0);
  const marketTotal = selectedRows.reduce((sum, card) => sum + (card.current_market_price || 0) * quantities[card.card_print_id], 0);
  const unpricedCount = selectedRows.filter((card) => !card.current_market_price).length;
  const balance = purchaseTotal !== null ? marketTotal - purchaseTotal : null;

  const visibleRows = useMemo(() => {
    const normalizedFilter = filterText.trim().toLowerCase();
    const rows = setCards.filter((card) => {
      if (onlySelected && !quantities[card.card_print_id]) {
        return false;
      }
      if (!normalizedFilter) {
        return true;
      }
      return [card.name, card.card_number, card.set_code, card.rarity].some((value) => (value || '').toLowerCase().includes(normalizedFilter));
    });
    const direction = sortDirection === 'asc' ? 1 : -1;
    return [...rows].sort((left, right) => {
      let result = 0;
      if (sortField === 'name') {
        result = compareText(left.name, right.name);
      } else if (sortField === 'current_market_price') {
        result = (left.current_market_price ?? -1) - (right.current_market_price ?? -1);
      } else if (sortField === 'quantity') {
        result = (quantities[left.card_print_id] || 0) - (quantities[right.card_print_id] || 0);
      }
      return result * direction || compareText(left.card_number, right.card_number) || compareText(left.rarity, right.rarity);
    });
  }, [filterText, onlySelected, quantities, setCards, sortDirection, sortField]);

  const toggleSort = (field: SortField) => {
    setSortDirection((current) => (sortField === field && current === 'asc' ? 'desc' : 'asc'));
    setSortField(field);
  };

  const handleSave = async () => {
    if (!selectedSet || !selectedRows.length) {
      return;
    }
    setSaving(true);
    setSuccess(null);
    setError(null);
    try {
      const payload: BulkSetImportPayload = {
        set_id: selectedSet.id,
        display_total_price: purchaseTotal,
        allocation_mode: allocationMode,
        currency,
        storage_location_id: storageLocationId ? Number(storageLocationId) : null,
        condition,
        language,
        notes: notes.trim() || null,
        items: selectedRows.map((card) => ({ card_print_id: card.card_print_id, quantity: quantities[card.card_print_id] })),
      };
      const response = await api.post<BulkSetImportResponse>('/inventory/bulk-add-from-set', payload);
      setPriceSyncJob(response.data.price_sync_job || null);
      setSuccess(
        `${response.data.total_quantity} Karten gespeichert${
          purchaseTotal !== null ? ` · Kaufpreis ${formatCurrency(response.data.total_allocated_price, response.data.currency)} verteilt` : ''
        }. Die Preise werden jetzt aktualisiert.`,
      );
      if (response.data.warning) {
        setError(response.data.warning);
      } else if (response.data.price_sync_job_error) {
        setError(response.data.price_sync_job_error);
      }
      setPurchasePrice('');
      setNotes('');
      await loadSetCards(selectedSet.id);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const sortHeader = (field: SortField, label: string, align: 'left' | 'right' = 'left') => (
    <TableCell align={align} sortDirection={sortField === field ? sortDirection : false}>
      <TableSortLabel active={sortField === field} direction={sortField === field ? sortDirection : 'asc'} onClick={() => toggleSort(field)}>
        {label}
      </TableSortLabel>
    </TableCell>
  );

  return (
    <Stack spacing={2.5} sx={{ pb: 12 }}>
      <PageHeader
        title="Display / Set erfassen"
        description="Set wählen, gezogene Karten eintippen, fertig. Ein Kaufpreis (z. B. für ein Display) wird automatisch auf die Karten verteilt."
      />

      {error ? (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}
      {success ? (
        <Alert severity="success" onClose={() => setSuccess(null)}>
          {success}
        </Alert>
      ) : null}
      {priceSyncJob ? (
        <Alert
          severity={priceSyncJob.status === 'failed' ? 'error' : priceSyncJob.status === 'completed' ? 'success' : 'info'}
          onClose={() => setPriceSyncJob(null)}
          action={
            <Button color="inherit" size="small" onClick={() => setLogJob(priceSyncJob)}>
              Details
            </Button>
          }
        >
          {priceSyncJob.status === 'completed'
            ? `Preise aktualisiert (${formatDate(priceSyncJob.completed_at || priceSyncJob.created_at)}).`
            : priceSyncJob.status === 'failed'
              ? `Preisupdate fehlgeschlagen: ${priceSyncJob.error_message || 'Unbekannter Fehler'}`
              : 'Preise der neuen Karten werden abgefragt…'}
        </Alert>
      ) : null}
      <SyncJobLogDialog open={Boolean(logJob)} job={logJob} onClose={() => setLogJob(null)} />

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '2.2fr 1fr 1fr 1.2fr' } }}>
          <Autocomplete<CardSetSummary, false, false, false>
            options={setOptions}
            value={selectedSet}
            inputValue={setSearch}
            loading={loadingSets}
            filterOptions={(options) => options}
            noOptionsText="Keine Sets gefunden"
            loadingText="Lade Sets…"
            onInputChange={(_, value) => setSetSearch(value)}
            onChange={(_, value) => {
              setSelectedSet(value);
              setSuccess(null);
              if (value) {
                void loadSetCards(value.id);
              } else {
                setSetCards([]);
                setQuantities({});
              }
            }}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            getOptionLabel={(option) => (option.set_code ? `${option.name} (${option.set_code})` : option.name)}
            renderOption={(props, option) => (
              <Box component="li" {...props} key={option.id}>
                <Box>
                  <Typography fontWeight={700}>{option.name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {[option.set_code, `${option.expected_card_count || option.card_count} Karten`, option.release_date].filter(Boolean).join(' · ')}
                  </Typography>
                </Box>
              </Box>
            )}
            renderInput={(params) => (
              <TextField
                {...params}
                label="1. Set"
                placeholder="Name oder Code, z. B. Rarity Collection oder RA05"
                InputProps={{
                  ...params.InputProps,
                  endAdornment: (
                    <>
                      {loadingSets ? <CircularProgress size={18} color="inherit" sx={{ mr: 1 }} /> : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                }}
              />
            )}
          />
          <TextField
            select
            label="Sprache"
            value={language}
            onChange={(event) => {
              setLanguage(event.target.value);
              if (selectedSet) {
                void loadSetCards(selectedSet.id, event.target.value);
              }
            }}
          >
            <MenuItem value="de">Deutsch</MenuItem>
            <MenuItem value="en">Englisch</MenuItem>
            <MenuItem value="jp">Japanisch</MenuItem>
          </TextField>
          <TextField
            label="Kaufpreis gesamt"
            placeholder="optional"
            inputMode="decimal"
            value={purchasePrice}
            onChange={(event) => setPurchasePrice(event.target.value)}
            InputProps={{ endAdornment: <InputAdornment position="end">{currency}</InputAdornment> }}
            helperText="z. B. Preis des Displays"
          />
          <TextField
            select
            label="Kaufpreis verteilen"
            value={allocationMode}
            disabled={purchaseTotal === null}
            onChange={(event) => setAllocationMode(event.target.value as AllocationMode)}
            helperText={allocationMode === 'market_value' ? 'Teure Karten bekommen mehr Anteil' : 'Jede Karte gleich viel'}
          >
            <MenuItem value="market_value">Nach Marktwert</MenuItem>
            <MenuItem value="even">Gleichmäßig</MenuItem>
          </TextField>
        </Box>
        <Box sx={{ display: 'grid', gap: 2, mt: 2, gridTemplateColumns: { xs: '1fr', md: '1.2fr 1fr 2fr' } }}>
          <TextField select label="Lagerort" value={storageLocationId} onChange={(event) => setStorageLocationId(event.target.value)}>
            <MenuItem value="">Nicht zugewiesen</MenuItem>
            {storageLocations.map((location) => (
              <MenuItem key={location.id} value={location.id}>
                {location.path_cache}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Zustand" value={condition} onChange={(event) => setCondition(event.target.value)}>
            {CONDITION_OPTIONS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField label="Notiz" placeholder="optional, z. B. Display 04/2026" value={notes} onChange={(event) => setNotes(event.target.value)} />
        </Box>
      </Paper>

      {selectedSet && !selectedSet.is_complete ? (
        <Alert severity="warning">
          {selectedSet.warning || 'Für dieses Set sind evtl. nicht alle Karten bekannt.'} Du kannst die vorhandenen Karten trotzdem erfassen.
        </Alert>
      ) : null}

      {selectedSet ? (
        <Paper sx={{ p: { xs: 2, sm: 3 } }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <BoltRoundedIcon color="primary" />
            <Typography variant="h6">2. Schnellerfassung</Typography>
          </Stack>
          <TextField
            inputRef={quickEntryRef}
            fullWidth
            autoComplete="off"
            label="Kartennummer oder Name"
            placeholder="z. B. 45, DE045 oder Dunkler Magier; mehrere: 45 x3"
            value={quickEntry}
            onChange={(event) => {
              setQuickEntry(event.target.value);
              setQuickEntryCandidates([]);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                submitQuickEntry();
              }
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRoundedIcon />
                </InputAdornment>
              ),
            }}
            helperText="Enter fügt die Karte hinzu. Bei mehreren Treffern (z. B. gleiche Nummer, andere Rarität) unten auswählen."
          />
          {quickEntryCandidates.length ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
              {quickEntryCandidates.map((candidate) => (
                <Chip
                  key={candidate.card_print_id}
                  clickable
                  color="primary"
                  variant="outlined"
                  avatar={<Avatar src={resolveMediaUrl(candidate.image_url)} />}
                  label={`${candidate.card_number || ''} ${candidate.name} · ${candidate.rarity || 'n/a'}`}
                  onClick={() => addCard(candidate, parseQuickEntry(quickEntry).quantity)}
                />
              ))}
            </Stack>
          ) : quickEntry.trim() && !findQuickEntryMatches(setCards, parseQuickEntry(quickEntry).term).length ? (
            <Typography color="warning.main" variant="body2" sx={{ mt: 1 }}>
              Keine Karte in diesem Set gefunden.
            </Typography>
          ) : null}
          {lastAdded ? (
            <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 1.5 }}>
              <Avatar src={resolveMediaUrl(lastAdded.row.image_url)} variant="rounded" sx={{ width: 32, height: 46 }} />
              <Typography variant="body2">
                Hinzugefügt: <strong>{lastAdded.row.name}</strong> ({lastAdded.row.card_number}, {lastAdded.row.rarity}) · jetzt {lastAdded.quantity}×
              </Typography>
              <Button size="small" color="inherit" onClick={() => changeQuantity(lastAdded.row.card_print_id, lastAdded.quantity - 1)}>
                Rückgängig
              </Button>
            </Stack>
          ) : null}
        </Paper>
      ) : null}

      <Paper sx={{ overflow: 'hidden' }}>
        {!selectedSet ? (
          <Box sx={{ p: 5, textAlign: 'center' }}>
            <Typography variant="h6">Noch kein Set ausgewählt</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.75 }}>
              Wähle oben ein Set. Danach erscheinen alle Karten des Sets.
            </Typography>
          </Box>
        ) : loadingCards ? (
          <Box sx={{ p: 5, display: 'grid', placeItems: 'center' }}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }} sx={{ px: { xs: 2, sm: 3 }, py: 2 }}>
              <Typography variant="h6" sx={{ flex: 1 }}>
                3. Kartenliste ({setCards.length})
              </Typography>
              <TextField size="small" label="Filtern" value={filterText} onChange={(event) => setFilterText(event.target.value)} />
              <FormControlLabel
                control={<Switch checked={onlySelected} onChange={(event) => setOnlySelected(event.target.checked)} />}
                label="Nur erfasste"
              />
            </Stack>
            <Box sx={{ maxHeight: '65vh', overflow: 'auto' }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    {sortHeader('name', 'Karte')}
                    {sortHeader('card_number', 'Nr.')}
                    <TableCell>Seltenheit</TableCell>
                    <TableCell align="right">Im Bestand</TableCell>
                    {sortHeader('current_market_price', 'Marktpreis', 'right')}
                    {sortHeader('quantity', 'Menge', 'right')}
                    {purchaseTotal !== null ? <TableCell align="right">Kaufpreis-Anteil</TableCell> : null}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visibleRows.map((card) => {
                    const quantity = quantities[card.card_print_id] || 0;
                    const line = allocation[card.card_print_id];
                    return (
                      <TableRow key={card.card_print_id} hover sx={{ backgroundColor: quantity > 0 ? 'rgba(216, 169, 76, 0.08)' : undefined }}>
                        <TableCell>
                          <Stack direction="row" spacing={1.5} alignItems="center">
                            <Avatar src={resolveMediaUrl(card.image_url)} variant="rounded" sx={{ width: 40, height: 58 }} />
                            <Box sx={{ minWidth: 0 }}>
                              <Typography fontWeight={700}>{card.name}</Typography>
                              <Typography variant="body2" color="text.secondary">
                                {card.card_type || ''}
                              </Typography>
                            </Box>
                          </Stack>
                        </TableCell>
                        <TableCell sx={{ whiteSpace: 'nowrap' }}>{card.card_number || 'n/a'}</TableCell>
                        <TableCell>{card.rarity || 'n/a'}</TableCell>
                        <TableCell align="right">{card.existing_quantity || '–'}</TableCell>
                        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                          {card.current_market_price != null ? formatCurrency(card.current_market_price, card.current_price_currency || currency) : '–'}
                        </TableCell>
                        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                          <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="flex-end">
                            <IconButton size="small" disabled={!quantity} onClick={() => changeQuantity(card.card_print_id, quantity - 1)} aria-label="Weniger">
                              <RemoveRoundedIcon fontSize="small" />
                            </IconButton>
                            <TextField
                              size="small"
                              value={quantity}
                              onFocus={(event) => event.target.select()}
                              onChange={(event) => changeQuantity(card.card_print_id, Math.max(0, Number.parseInt(event.target.value, 10) || 0))}
                              inputProps={{ inputMode: 'numeric', style: { textAlign: 'center', width: 32 } }}
                            />
                            <IconButton size="small" color="primary" onClick={() => changeQuantity(card.card_print_id, quantity + 1)} aria-label="Mehr">
                              <AddRoundedIcon fontSize="small" />
                            </IconButton>
                          </Stack>
                        </TableCell>
                        {purchaseTotal !== null ? (
                          <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                            {line ? (
                              <>
                                {formatCurrency(line.lineTotal, currency)}
                                {line.quantity > 1 ? (
                                  <Typography variant="body2" color="text.secondary">
                                    {formatCurrency(line.unitPrice, currency)} / Stk.
                                  </Typography>
                                ) : null}
                              </>
                            ) : (
                              '–'
                            )}
                          </TableCell>
                        ) : null}
                      </TableRow>
                    );
                  })}
                  {!visibleRows.length ? (
                    <TableRow>
                      <TableCell colSpan={7}>
                        <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                          {onlySelected ? 'Noch keine Karten erfasst.' : 'Keine Karten gefunden.'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </Box>
          </>
        )}
      </Paper>

      {selectedSet ? (
        <Paper
          elevation={8}
          sx={{
            position: 'sticky',
            bottom: { xs: 8, md: 16 },
            zIndex: 5,
            p: 2,
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            flexWrap: 'wrap',
            border: '1px solid rgba(216,169,76,0.35)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap sx={{ flex: 1 }}>
            <Box>
              <Typography variant="body2" color="text.secondary">
                Karten
              </Typography>
              <Typography fontWeight={800}>{totalQuantity}</Typography>
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary">
                Marktwert{unpricedCount ? ` (${unpricedCount} ohne Preis)` : ''}
              </Typography>
              <Typography fontWeight={800}>{formatCurrency(marketTotal, currency)}</Typography>
            </Box>
            {purchaseTotal !== null ? (
              <>
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Kaufpreis
                  </Typography>
                  <Typography fontWeight={800}>{formatCurrency(purchaseTotal, currency)}</Typography>
                </Box>
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Bilanz
                  </Typography>
                  <Typography fontWeight={800} color={(balance || 0) >= 0 ? 'success.main' : 'error.main'}>
                    {(balance || 0) >= 0 ? '+' : ''}
                    {formatCurrency(balance, currency)}
                  </Typography>
                </Box>
              </>
            ) : null}
          </Stack>
          <Button color="inherit" disabled={!totalQuantity || saving} onClick={() => setQuantities({})}>
            Leeren
          </Button>
          <Button
            variant="contained"
            size="large"
            startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <AddTaskRoundedIcon />}
            disabled={saving || !totalQuantity}
            onClick={() => void handleSave()}
          >
            {saving ? 'Speichere…' : `${totalQuantity} Karten speichern`}
          </Button>
        </Paper>
      ) : null}
    </Stack>
  );
}
