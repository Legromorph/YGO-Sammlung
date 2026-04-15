import { useEffect, useMemo, useState } from 'react';
import AddTaskRoundedIcon from '@mui/icons-material/AddTaskRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import {
  Alert,
  Autocomplete,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import api, { getApiErrorMessage, resolveMediaUrl } from '../lib/api';
import { formatCurrency, formatDate } from '../lib/format';
import { useAppSettings } from '../components/app-settings-provider';
import {
  BulkSetImportPayload,
  BulkSetImportResponse,
  CardSetSummary,
  SetCardRow,
  SetCardsResponse,
  StorageLocation,
  SyncJob,
} from '../lib/types';

type QuantityMap = Record<number, number>;

type AllocationPreviewLine = {
  card_print_id: number;
  quantity: number;
  allocatedPurchaseTotal: number;
  allocatedUnitPrice: number;
};

type AllocationPreview = {
  lines: Record<number, AllocationPreviewLine>;
  averageUnitPrice: number | null;
  totalAllocatedPrice: number | null;
  remainderCents: number;
};

function normalizeQuantity(value: string): number {
  const nextValue = Number.parseInt(value, 10);
  if (Number.isNaN(nextValue) || nextValue < 0) {
    return 0;
  }
  return nextValue;
}

function parseMoney(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  if (Number.isNaN(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

function allocateDisplayTotal(displayTotalPrice: number | null, rows: Array<{ card_print_id: number; quantity: number }>): AllocationPreview {
  if (displayTotalPrice === null || !rows.length) {
    return {
      lines: {},
      averageUnitPrice: null,
      totalAllocatedPrice: null,
      remainderCents: 0,
    };
  }

  const totalQuantity = rows.reduce((sum, row) => sum + row.quantity, 0);
  if (totalQuantity <= 0) {
    return {
      lines: {},
      averageUnitPrice: null,
      totalAllocatedPrice: null,
      remainderCents: 0,
    };
  }

  const totalCents = Math.round(displayTotalPrice * 100);
  const baseCents = Math.floor(totalCents / totalQuantity);
  let remainderCents = totalCents % totalQuantity;
  const averageUnitPrice = Number((displayTotalPrice / totalQuantity).toFixed(4));

  const reversedAllocations = [...rows].reverse().map((row) => {
    const extraCents = Math.min(row.quantity, remainderCents);
    remainderCents -= extraCents;
    const lineTotalCents = row.quantity * baseCents + extraCents;
    const allocatedPurchaseTotal = lineTotalCents / 100;
    const allocatedUnitPrice = Number((allocatedPurchaseTotal / row.quantity).toFixed(4));
    return {
      card_print_id: row.card_print_id,
      quantity: row.quantity,
      allocatedPurchaseTotal,
      allocatedUnitPrice,
    };
  });

  const lines = Object.fromEntries(
    reversedAllocations.reverse().map((line) => [
      line.card_print_id,
      {
        card_print_id: line.card_print_id,
        quantity: line.quantity,
        allocatedPurchaseTotal: line.allocatedPurchaseTotal,
        allocatedUnitPrice: line.allocatedUnitPrice,
      },
    ]),
  );

  return {
    lines,
    averageUnitPrice,
    totalAllocatedPrice: totalCents / 100,
    remainderCents: totalCents % totalQuantity,
  };
}

export default function SetImportPage() {
  const { settings } = useAppSettings();
  const [setOptions, setSetOptions] = useState<CardSetSummary[]>([]);
  const [setSearch, setSetSearch] = useState('');
  const [selectedSet, setSelectedSet] = useState<CardSetSummary | null>(null);
  const [setCards, setSetCards] = useState<SetCardRow[]>([]);
  const [quantities, setQuantities] = useState<QuantityMap>({});
  const [storageLocations, setStorageLocations] = useState<StorageLocation[]>([]);
  const [displayTotalPrice, setDisplayTotalPrice] = useState('');
  const [storageLocationId, setStorageLocationId] = useState('');
  const [condition, setCondition] = useState('near_mint');
  const [language, setLanguage] = useState(settings.preferred_card_language || 'de');
  const [displayCurrency, setDisplayCurrency] = useState(settings.preferred_currency || 'EUR');
  const [notes, setNotes] = useState('');
  const [loadingSets, setLoadingSets] = useState(false);
  const [loadingCards, setLoadingCards] = useState(false);
  const [saving, setSaving] = useState(false);
  const [priceSyncJob, setPriceSyncJob] = useState<SyncJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const loadStorageLocations = async () => {
      try {
        const response = await api.get<StorageLocation[]>('/storage-locations/');
        if (active) {
          setStorageLocations(response.data);
        }
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      }
    };

    void loadStorageLocations();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setDisplayCurrency(settings.preferred_currency || 'EUR');
    if (!selectedSet && setCards.length === 0) {
      setLanguage(settings.preferred_card_language || 'de');
    }
  }, [selectedSet, setCards.length, settings.preferred_card_language, settings.preferred_currency]);

  useEffect(() => {
    let active = true;
    const handle = window.setTimeout(async () => {
      setLoadingSets(true);
      try {
        const response = await api.get<CardSetSummary[]>('/sets/', {
          params: {
            q: setSearch.trim() || undefined,
            limit: 24,
          },
        });
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

  const loadSetCards = async (setId: number, languageOverride = language) => {
    setLoadingCards(true);
    setSuccess(null);
    try {
      const response = await api.get<SetCardsResponse>(`/sets/${setId}/cards`, {
        params: { language: languageOverride },
      });
      setSelectedSet(response.data.set);
      setSetCards(response.data.items);
      setQuantities({});
      setError(null);
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
          await loadSetCards(selectedSet.id);
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
  }, [priceSyncJob, selectedSet]);

  const selectedRows = useMemo(
    () =>
      setCards
        .map((card) => ({ ...card, selectedQuantity: quantities[card.card_print_id] || 0 }))
        .filter((card) => card.selectedQuantity > 0),
    [quantities, setCards],
  );

  const selectedLineCount = selectedRows.length;
  const selectedQuantityTotal = selectedRows.reduce((sum, card) => sum + card.selectedQuantity, 0);
  const parsedDisplayTotalPrice = parseMoney(displayTotalPrice);
  const allocationPreview = useMemo(
    () =>
      allocateDisplayTotal(
        parsedDisplayTotalPrice,
        selectedRows.map((card) => ({
          card_print_id: card.card_print_id,
          quantity: card.selectedQuantity,
        })),
      ),
    [parsedDisplayTotalPrice, selectedRows],
  );

  const marketCurrencies = Array.from(
    new Set(selectedRows.map((card) => card.current_price_currency).filter((currency): currency is string => Boolean(currency))),
  );
  const estimatedMarketTotal = selectedRows.reduce((sum, card) => sum + (card.current_market_price || 0) * card.selectedQuantity, 0);

  const handleQuantityChange = (cardPrintId: number, nextQuantity: number) => {
    setSuccess(null);
    setQuantities((current) => {
      if (nextQuantity <= 0) {
        const nextState = { ...current };
        delete nextState[cardPrintId];
        return nextState;
      }
      return { ...current, [cardPrintId]: nextQuantity };
    });
  };

  const handleSave = async () => {
    if (!selectedSet || !selectedRows.length || parsedDisplayTotalPrice === null) {
      return;
    }

    setSaving(true);
    setSuccess(null);
    try {
      const payload: BulkSetImportPayload = {
        set_id: selectedSet.id,
        display_total_price: parsedDisplayTotalPrice,
        currency: displayCurrency,
        storage_location_id: storageLocationId ? Number(storageLocationId) : null,
        condition,
        language,
        notes: notes.trim() || null,
        items: selectedRows.map((card) => ({
          card_print_id: card.card_print_id,
          quantity: card.selectedQuantity,
        })),
      };
      const response = await api.post<BulkSetImportResponse>('/inventory/bulk-add-from-set', payload);
      setPriceSyncJob(response.data.price_sync_job || null);
      setSuccess(
        `Batch #${response.data.purchase_batch_id} gespeichert: ${response.data.total_quantity} Karten, ${formatCurrency(
          response.data.total_allocated_price,
          response.data.currency,
        )} verteilt, durchschnittlich ${formatCurrency(response.data.allocated_unit_price, response.data.currency)} pro Karte.${
          response.data.price_sync_job ? ` Preisjob #${response.data.price_sync_job.id} wurde direkt gestartet.` : ''
        }`,
      );
      if (response.data.price_sync_job_error) {
        setError(response.data.price_sync_job_error);
      }
      await loadSetCards(selectedSet.id);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack spacing={3}>
      <Paper
        sx={{
          p: 3,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 2,
          flexWrap: 'wrap',
          background: 'linear-gradient(135deg, rgba(216,169,76,0.12), rgba(78,162,138,0.08))',
        }}
      >
        <Box>
          <Typography variant="h4">Set-Erfassung</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75, maxWidth: 900 }}>
            Die Setliste laedt komplette Sets ueber den kanonischen Provider-Import und verteilt den Display-Gesamtpreis automatisch auf alle
            aktuell eingetragenen Karten.
          </Typography>
        </Box>
        <Chip icon={<AutoAwesomeRoundedIcon />} label="Kompletter Set-Import mit Batch-Kostenbasis" color="secondary" variant="outlined" />
      </Paper>

      {error ? <Alert severity="error" onClose={() => setError(null)}>{error}</Alert> : null}
      {success ? <Alert severity="success" onClose={() => setSuccess(null)}>{success}</Alert> : null}
      {priceSyncJob ? (
        <Alert
          severity={priceSyncJob.status === 'failed' ? 'error' : priceSyncJob.status === 'completed' ? 'success' : 'info'}
          onClose={() => setPriceSyncJob(null)}
        >
          {priceSyncJob.status === 'completed'
            ? `Preisupdate abgeschlossen. Letztes Preisupdate: ${formatDate(priceSyncJob.completed_at || priceSyncJob.created_at)}.`
            : priceSyncJob.status === 'failed'
              ? `Preisupdate fehlgeschlagen: ${priceSyncJob.error_message || 'Unbekannter Fehler'}.`
              : `Preisupdate laeuft fuer die importierten Karten. Job #${priceSyncJob.id} wurde am ${formatDate(
                  priceSyncJob.created_at,
                )} gestartet.`}
        </Alert>
      ) : null}

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="h6">1. Set auswaehlen</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Suche nach Setname oder Setcode. Die Treffer zeigen direkt, wie viele Karten laut Katalog erwartet und aktuell lokal geladen sind.
            </Typography>
          </Box>

          <Autocomplete<CardSetSummary, false, false, false>
            options={setOptions}
            value={selectedSet}
            inputValue={setSearch}
            loading={loadingSets}
            filterOptions={(options) => options}
            noOptionsText="Keine Sets gefunden"
            loadingText="Lade Sets..."
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
              <Box component="li" {...props} sx={{ alignItems: 'flex-start', gap: 1.25 }}>
                <SearchRoundedIcon sx={{ color: 'primary.light', mt: 0.35 }} />
                <Box>
                  <Typography fontWeight={700}>{option.name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {[option.set_code, `${option.loaded_card_count}/${option.expected_card_count || option.card_count} Karten`, option.release_date || null]
                      .filter(Boolean)
                      .join(' | ')}
                  </Typography>
                </Box>
              </Box>
            )}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Set suchen"
                placeholder="z. B. Burst Protocol oder BPRO"
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

          {selectedSet ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip label={selectedSet.name} color="primary" variant="outlined" />
              {selectedSet.set_code ? <Chip label={selectedSet.set_code} variant="outlined" /> : null}
              <Chip
                label={`${selectedSet.loaded_card_count}/${selectedSet.expected_card_count || selectedSet.card_count} Karten`}
                color={selectedSet.is_complete ? 'success' : 'warning'}
                variant="outlined"
              />
              <Chip label={`${selectedSet.loaded_print_count} Prints`} variant="outlined" />
            </Stack>
          ) : null}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="h6">2. Einkaufsvorgang festlegen</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Der eingegebene Betrag ist der Gesamtpreis des Displays oder Einkaufs und wird dynamisch auf die aktuell eingetragene Gesamtanzahl
              verteilt.
            </Typography>
          </Box>

          <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: '1.15fr 1fr 1fr 1fr' } }}>
            <TextField
              label="Display-Gesamtpreis"
              type="number"
              value={displayTotalPrice}
              onChange={(event) => {
                setSuccess(null);
                setDisplayTotalPrice(event.target.value);
              }}
              inputProps={{ min: 0, step: '0.01' }}
              helperText="Dieser Betrag wird automatisch auf die aktuell eingetragene Gesamtanzahl verteilt."
            />
            <TextField
              select
              label="Lagerort"
              value={storageLocationId}
              onChange={(event) => {
                setSuccess(null);
                setStorageLocationId(event.target.value);
              }}
            >
              <MenuItem value="">Nicht zugewiesen</MenuItem>
              {storageLocations.map((location) => (
                <MenuItem key={location.id} value={location.id}>
                  {location.path_cache}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Zustand"
              value={condition}
              onChange={(event) => {
                setSuccess(null);
                setCondition(event.target.value);
              }}
            >
              <MenuItem value="near_mint">Near Mint</MenuItem>
              <MenuItem value="excellent">Excellent</MenuItem>
              <MenuItem value="good">Good</MenuItem>
              <MenuItem value="played">Played</MenuItem>
              <MenuItem value="poor">Poor</MenuItem>
            </TextField>
              <TextField
                select
                label="Sprache des Einkaufs"
                value={language}
                onChange={(event) => {
                  setSuccess(null);
                  const nextLanguage = event.target.value;
                  setLanguage(nextLanguage);
                  if (selectedSet) {
                    void loadSetCards(selectedSet.id, nextLanguage);
                  }
                }}
              >
              <MenuItem value="de">Deutsch</MenuItem>
              <MenuItem value="en">Englisch</MenuItem>
              <MenuItem value="jp">Japanisch</MenuItem>
            </TextField>
          </Box>

          <TextField
            label="Notiz fuer den Einkaufsvorgang"
            value={notes}
            onChange={(event) => {
              setSuccess(null);
              setNotes(event.target.value);
            }}
            multiline
            minRows={2}
            placeholder="Optional, z. B. Displaykauf 04/2026 oder Messeankauf."
          />
        </Stack>
      </Paper>

      {selectedSet?.warning ? (
        <Alert severity={selectedSet.is_complete ? 'warning' : 'error'} icon={<WarningAmberRoundedIcon />}>
          {selectedSet.warning}
        </Alert>
      ) : null}

      <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', xl: '2.25fr 1fr' }, alignItems: 'start' }}>
        <Paper sx={{ overflow: 'hidden' }}>
          <Box sx={{ p: 3, pb: 2 }}>
            <Typography variant="h6">3. Kartenliste des Sets</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Sortiert nach Kartennummer. Pro Zeile siehst du live die verteilte Kostenbasis fuer genau diese Kartenmenge.
            </Typography>
          </Box>
          <Divider sx={{ borderColor: 'rgba(255,255,255,0.06)' }} />

          {!selectedSet ? (
            <Box sx={{ p: 4.5, textAlign: 'center' }}>
              <Typography variant="h6">Noch kein Set ausgewaehlt</Typography>
              <Typography color="text.secondary" sx={{ mt: 0.75 }}>
                Waehle oben ein Set aus, dann werden alle zugehoerigen Karten geladen.
              </Typography>
            </Box>
          ) : loadingCards ? (
            <Box sx={{ p: 5, display: 'grid', placeItems: 'center' }}>
              <CircularProgress />
            </Box>
          ) : (
            <Box sx={{ maxHeight: '68vh', overflow: 'auto' }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Karte</TableCell>
                    <TableCell>Nr.</TableCell>
                    <TableCell>Seltenheit</TableCell>
                    <TableCell align="right">Bestand</TableCell>
                    <TableCell align="right">Marktpreis</TableCell>
                    <TableCell align="right">Menge</TableCell>
                    <TableCell align="right">Ankauf Zeile</TableCell>
                    <TableCell align="right">Stk. kalk.</TableCell>
                    <TableCell align="right">Schnell</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {setCards.map((card) => {
                    const quantity = quantities[card.card_print_id] || 0;
                    const allocationLine = allocationPreview.lines[card.card_print_id];
                    return (
                      <TableRow
                        key={card.card_print_id}
                        hover
                        sx={{
                          backgroundColor: quantity > 0 ? 'rgba(216, 169, 76, 0.08)' : undefined,
                          transition: 'background-color 160ms ease',
                        }}
                      >
                        <TableCell>
                          <Stack direction="row" spacing={1.5} alignItems="center">
                            <Avatar src={resolveMediaUrl(card.image_url)} variant="rounded" sx={{ width: 42, height: 58 }} />
                            <Box>
                              <Typography fontWeight={700}>{card.name}</Typography>
                              <Typography variant="body2" color="text.secondary">
                                {card.card_type || 'Keine Typinfo'}
                              </Typography>
                              <Typography variant="body2" color="text.secondary">
                                {[card.set_code || selectedSet.set_code || 'Kein Setcode', card.language.toUpperCase()].join(' | ')}
                              </Typography>
                            </Box>
                          </Stack>
                        </TableCell>
                        <TableCell>{card.card_number || 'n/a'}</TableCell>
                        <TableCell>{card.rarity || 'n/a'}</TableCell>
                        <TableCell align="right">{card.existing_quantity}</TableCell>
                        <TableCell align="right">
                          {card.current_market_price !== null && card.current_market_price !== undefined
                            ? formatCurrency(card.current_market_price, card.current_price_currency || displayCurrency)
                            : 'n/a'}
                        </TableCell>
                        <TableCell align="right" sx={{ width: 110 }}>
                          <TextField
                            type="number"
                            size="small"
                            value={quantity}
                            onChange={(event) => handleQuantityChange(card.card_print_id, normalizeQuantity(event.target.value))}
                            onFocus={(event) => event.target.select()}
                            inputProps={{ min: 0, step: 1, inputMode: 'numeric' }}
                          />
                        </TableCell>
                        <TableCell align="right">
                          {allocationLine ? formatCurrency(allocationLine.allocatedPurchaseTotal, displayCurrency) : 'n/a'}
                        </TableCell>
                        <TableCell align="right">
                          {allocationLine ? formatCurrency(allocationLine.allocatedUnitPrice, displayCurrency) : 'n/a'}
                        </TableCell>
                        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                          <Button size="small" onClick={() => handleQuantityChange(card.card_print_id, quantity + 1)}>
                            +1
                          </Button>
                          <Button size="small" color="inherit" onClick={() => handleQuantityChange(card.card_print_id, 0)}>
                            0
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          )}
        </Paper>

        <Stack spacing={3}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6">4. Live-Zusammenfassung</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Die Verteilung aktualisiert sich bei jeder Mengen- oder Preis-Aenderung.
            </Typography>
            <Box sx={{ display: 'grid', gap: 1.25, mt: 2.5 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Display-Gesamtpreis</Typography>
                <Typography fontWeight={700}>
                  {parsedDisplayTotalPrice === null ? 'n/a' : formatCurrency(parsedDisplayTotalPrice, displayCurrency)}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Ausgewaehlte Kartenzeilen</Typography>
                <Typography fontWeight={700}>{selectedLineCount}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Gesamtanzahl</Typography>
                <Typography fontWeight={700}>{selectedQuantityTotal}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Ankauf pro Karte</Typography>
                <Typography fontWeight={700}>
                  {allocationPreview.averageUnitPrice === null ? 'n/a' : formatCurrency(allocationPreview.averageUnitPrice, displayCurrency)}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Verteilter Ankauf gesamt</Typography>
                <Typography fontWeight={700}>
                  {allocationPreview.totalAllocatedPrice === null ? 'n/a' : formatCurrency(allocationPreview.totalAllocatedPrice, displayCurrency)}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Marktreferenz</Typography>
                <Typography fontWeight={700}>
                  {marketCurrencies.length <= 1
                    ? formatCurrency(estimatedMarketTotal, marketCurrencies[0] || displayCurrency)
                    : 'gemischte Waehrungen'}
                </Typography>
              </Box>
            </Box>

            {allocationPreview.remainderCents > 0 ? (
              <Alert severity="info" sx={{ mt: 2.25 }}>
                {allocationPreview.remainderCents} Cent Rundungsrest werden deterministisch auf die letzten ausgewaehlten Zeilen verteilt.
              </Alert>
            ) : null}

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2.5 }}>
              <Chip label={`Waehrung: ${displayCurrency}`} variant="outlined" />
              <Chip label={`Sprache: ${language.toUpperCase()}`} variant="outlined" />
              <Chip label={`Zustand: ${condition}`} variant="outlined" />
              {storageLocationId ? (
                <Chip
                  label={`Lagerort: ${storageLocations.find((location) => String(location.id) === storageLocationId)?.path_cache || storageLocationId}`}
                  variant="outlined"
                />
              ) : null}
            </Stack>
          </Paper>

          <Paper
            sx={{
              p: 3,
              position: { xl: 'sticky' },
              top: { xl: 24 },
            }}
          >
            <Typography variant="h6">5. Speichern</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5, mb: 2.5 }}>
              Beim Speichern wird ein eigener Einkaufsvorgang erzeugt. Jede Zeile behaelt ihre exakt verteilte Kostenbasis und referenziert
              denselben Batch.
            </Typography>
            <Button
              variant="contained"
              size="large"
              startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <AddTaskRoundedIcon />}
              disabled={saving || !selectedSet || !selectedRows.length || parsedDisplayTotalPrice === null}
              fullWidth
              onClick={() => void handleSave()}
            >
              {saving ? 'Speichere Einkaufsvorgang...' : 'Einkaufsvorgang speichern'}
            </Button>
          </Paper>
        </Stack>
      </Box>
    </Stack>
  );
}
