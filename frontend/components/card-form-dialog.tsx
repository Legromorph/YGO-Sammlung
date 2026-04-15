import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';

import api, { getApiErrorMessage, resolveMediaUrl } from '../lib/api';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import { useAppSettings } from './app-settings-provider';
import {
  CardDetail,
  CardLookupPrintOption,
  CardLookupResponse,
  CardLookupSuggestion,
  CardPayload,
  StorageLocation,
} from '../lib/types';

interface CardFormDialogProps {
  open: boolean;
  title: string;
  initialValue?: CardDetail | null;
  storageLocations: StorageLocation[];
  loading?: boolean;
  onClose: () => void;
  onSubmit: (payload: CardPayload) => Promise<void>;
}

type LookupSelection = {
  set_name?: string | null;
  set_code?: string | null;
  rarity?: string | null;
};

const defaultPayload: CardPayload = {
  name: '',
  language: 'de',
  condition: 'near_mint',
  quantity: 1,
  current_price_currency: 'EUR',
  tags: [],
  external_ids: {},
  link_arrows: [],
};

function buildDefaultPayload(preferredCardLanguage: string, preferredCurrency: string): CardPayload {
  return {
    ...defaultPayload,
    language: preferredCardLanguage || defaultPayload.language,
    current_price_currency: preferredCurrency || defaultPayload.current_price_currency,
  };
}

function isCardmarketUrl(value: string): boolean {
  return /^https?:\/\/www\.cardmarket\.com\/[a-z]{2}\/YuGiOh\//i.test(value.trim());
}

function trimValue(value?: string | null): string | undefined {
  const nextValue = value?.trim();
  return nextValue ? nextValue : undefined;
}

function uniqueValues(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.map((value) => trimValue(value)).filter((value): value is string => Boolean(value))));
}

function filterPrintOptions(
  printOptions: CardLookupPrintOption[],
  selection: LookupSelection,
  ignoreField?: keyof LookupSelection,
): CardLookupPrintOption[] {
  return printOptions.filter((option) => {
    if (ignoreField !== 'set_name' && selection.set_name && option.set_name !== selection.set_name) {
      return false;
    }
    if (ignoreField !== 'set_code' && selection.set_code && option.set_code !== selection.set_code) {
      return false;
    }
    if (ignoreField !== 'rarity' && selection.rarity && option.rarity !== selection.rarity) {
      return false;
    }
    return true;
  });
}

function resolveSelectedPrint(printOptions: CardLookupPrintOption[], selection: LookupSelection): CardLookupPrintOption | null {
  const matches = filterPrintOptions(printOptions, selection);
  return matches.length === 1 ? matches[0] : null;
}

function sanitizeSelection(printOptions: CardLookupPrintOption[], selection: LookupSelection): LookupSelection {
  const nextSelection: LookupSelection = {
    set_name: trimValue(selection.set_name),
    set_code: trimValue(selection.set_code),
    rarity: trimValue(selection.rarity),
  };

  if (!printOptions.length) {
    return nextSelection;
  }

  const availableSetNames = uniqueValues(filterPrintOptions(printOptions, nextSelection, 'set_name').map((option) => option.set_name));
  if (nextSelection.set_name && !availableSetNames.includes(nextSelection.set_name)) {
    nextSelection.set_name = undefined;
  }

  const availableSetCodes = uniqueValues(filterPrintOptions(printOptions, nextSelection, 'set_code').map((option) => option.set_code));
  if (nextSelection.set_code && !availableSetCodes.includes(nextSelection.set_code)) {
    nextSelection.set_code = undefined;
  }

  const availableRarities = uniqueValues(filterPrintOptions(printOptions, nextSelection, 'rarity').map((option) => option.rarity));
  if (nextSelection.rarity && !availableRarities.includes(nextSelection.rarity)) {
    nextSelection.rarity = undefined;
  }

  const resolvedPrint = resolveSelectedPrint(printOptions, nextSelection);
  if (resolvedPrint) {
    return {
      set_name: resolvedPrint.set_name ?? undefined,
      set_code: resolvedPrint.set_code ?? undefined,
      rarity: resolvedPrint.rarity ?? undefined,
    };
  }

  return nextSelection;
}

export default function CardFormDialog({
  open,
  title,
  initialValue,
  storageLocations,
  loading = false,
  onClose,
  onSubmit,
}: CardFormDialogProps) {
  const { settings } = useAppSettings();
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'));
  const [form, setForm] = useState<CardPayload>(() => buildDefaultPayload(settings.preferred_card_language, settings.preferred_currency));
  const [tagText, setTagText] = useState('');
  const [ygoprodeckId, setYgoprodeckId] = useState('');
  const [cardmarketUrl, setCardmarketUrl] = useState('');
  const [lookupData, setLookupData] = useState<CardLookupResponse | null>(null);
  const [suggestions, setSuggestions] = useState<CardLookupSuggestion[]>([]);
  const [selectedSuggestion, setSelectedSuggestion] = useState<CardLookupSuggestion | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [cardmarketLoading, setCardmarketLoading] = useState(false);
  const [lastImportedCardmarketUrl, setLastImportedCardmarketUrl] = useState('');
  const debouncedSearchTerm = useDebouncedValue(form.name.trim(), 250);

  useEffect(() => {
    if (!open) {
      return;
    }

    setSuggestions([]);
    setSelectedSuggestion(null);
    setLookupData(null);
    setLookupError(null);
    setSearchLoading(false);
    setLookupLoading(false);
    setCardmarketLoading(false);
    setLastImportedCardmarketUrl('');

    if (!initialValue) {
      setForm(buildDefaultPayload(settings.preferred_card_language, settings.preferred_currency));
      setTagText('');
      setYgoprodeckId('');
      setCardmarketUrl('');
      return;
    }

    const mapping = initialValue.source_mappings.find((item) => item.provider_key === 'ygoprodeck');
    const externalIds = initialValue.source_mappings.reduce<Record<string, string>>((accumulator, item) => {
      accumulator[item.provider_key] = item.external_id;
      return accumulator;
    }, {});
    setForm({
      card_id: initialValue.card_id,
      card_print_id: initialValue.card_print_id,
      name: initialValue.name,
      language: initialValue.language,
      set_name: initialValue.set_name,
      set_code: initialValue.set_code,
      card_number: initialValue.card_number,
      rarity: initialValue.rarity,
      rarity_code: initialValue.rarity_code,
      edition: initialValue.edition,
      release_date: initialValue.release_date,
      condition: initialValue.condition,
      quantity: initialValue.quantity,
      purchase_price: initialValue.purchase_price,
      current_market_price: initialValue.current_market_price,
      current_price_currency: initialValue.current_price_currency,
      storage_location_id: initialValue.storage_location_id,
      cardmarket_reference: initialValue.cardmarket_reference,
      cardmarket_product_url: initialValue.cardmarket_product_url,
      cardmarket_product_slug: initialValue.cardmarket_product_slug,
      cardmarket_set_slug: initialValue.cardmarket_set_slug,
      cardmarket_set_name: initialValue.cardmarket_set_name,
      cardmarket_product_name: initialValue.cardmarket_product_name,
      cardmarket_variant_name: initialValue.cardmarket_variant_name,
      cardmarket_category: initialValue.cardmarket_category,
      cardmarket_match_quality: initialValue.cardmarket_match_quality,
      cardmarket_verified_at: initialValue.cardmarket_verified_at,
      cardmarket_expected_rarity: initialValue.cardmarket_expected_rarity,
      cardmarket_expected_language: initialValue.cardmarket_expected_language,
      cardmarket_expected_set_name: initialValue.cardmarket_expected_set_name,
      notes: initialValue.notes,
      tags: initialValue.tags || [],
      external_ids: externalIds,
      effect_text: initialValue.effect_text,
      card_type: initialValue.card_type,
      subtype: initialValue.subtype,
      attribute: initialValue.attribute,
      monster_type: initialValue.monster_type,
      archetype: initialValue.archetype,
      atk: initialValue.atk,
      defense: initialValue.defense,
      level: initialValue.level,
      rank: initialValue.rank,
      link_rating: initialValue.link_rating,
      link_arrows: initialValue.link_arrows || [],
      pendulum_scale: initialValue.pendulum_scale,
      pendulum_effect: initialValue.pendulum_effect,
      spell_trap_type: initialValue.spell_trap_type,
    });
    setTagText((initialValue.tags || []).join(', '));
    setYgoprodeckId(mapping?.external_id || '');
    setCardmarketUrl(initialValue.cardmarket_product_url || initialValue.cardmarket_reference || externalIds.cardmarket || '');
    setLastImportedCardmarketUrl(initialValue.cardmarket_product_url || initialValue.cardmarket_reference || externalIds.cardmarket || '');
  }, [initialValue, open, settings.preferred_card_language, settings.preferred_currency]);

  const updateForm = (patch: Partial<CardPayload>) => setForm((current) => ({ ...current, ...patch }));

  const printOptions = lookupData?.print_options ?? [];
  const selection = useMemo<LookupSelection>(
    () => ({
      set_name: form.set_name,
      set_code: form.set_code,
      rarity: form.rarity,
    }),
    [form.rarity, form.set_code, form.set_name],
  );

  const setNameOptions = useMemo(
    () => uniqueValues(filterPrintOptions(printOptions, selection, 'set_name').map((option) => option.set_name)),
    [printOptions, selection],
  );
  const setCodeOptions = useMemo(
    () => uniqueValues(filterPrintOptions(printOptions, selection, 'set_code').map((option) => option.set_code)),
    [printOptions, selection],
  );
  const rarityOptions = useMemo(
    () => uniqueValues(filterPrintOptions(printOptions, selection, 'rarity').map((option) => option.rarity)),
    [printOptions, selection],
  );
  const resolvedPrint = useMemo(
    () => resolveSelectedPrint(printOptions, selection),
    [printOptions, selection],
  );

  const needsDisambiguation = Boolean(lookupData && printOptions.length > 1 && !resolvedPrint);
  const highlightSetName = needsDisambiguation && !form.set_name && setNameOptions.length > 1;
  const highlightSetCode = needsDisambiguation && !form.set_code && setCodeOptions.length > 1;
  const highlightRarity = needsDisambiguation && !form.rarity && rarityOptions.length > 1;

  const marketPriceHelperText = useMemo(() => {
    const messages: string[] = [];
    if (resolvedPrint?.price_note) {
      messages.push(resolvedPrint.price_note);
    } else if (lookupData?.price_note) {
      messages.push(lookupData.price_note);
    }
    if (lookupData && !lookupData.condition_price_supported && form.condition !== 'near_mint') {
      messages.push('Der gewaehlte Zustand wird aktuell nicht automatisch in den Provider-Preis eingerechnet. Bitte Marktpreis pruefen.');
    }
    return messages.join(' ');
  }, [form.condition, lookupData, resolvedPrint]);

  const applyLookupPayload = (lookup: CardLookupResponse, selectionPatch: LookupSelection = {}) => {
    setLookupData(lookup);
    setLookupError(null);
    setYgoprodeckId(lookup.ygoprodeck_id || '');
    setForm((current) => {
      const nextSelection = sanitizeSelection(lookup.print_options, {
        set_name: selectionPatch.set_name !== undefined ? selectionPatch.set_name : current.set_name,
        set_code: selectionPatch.set_code !== undefined ? selectionPatch.set_code : current.set_code,
        rarity: selectionPatch.rarity !== undefined ? selectionPatch.rarity : current.rarity,
      });
      const nextPrint = resolveSelectedPrint(lookup.print_options, nextSelection);

      return {
        ...current,
        name: lookup.name,
        set_name: nextSelection.set_name ?? undefined,
        set_code: nextSelection.set_code ?? undefined,
        card_number: nextPrint?.card_number ?? undefined,
        rarity: nextSelection.rarity ?? undefined,
        rarity_code: nextPrint?.rarity_code ?? undefined,
        current_market_price: nextPrint?.market_price ?? lookup.default_market_price ?? undefined,
        current_price_currency: nextPrint?.price_currency ?? lookup.default_price_currency ?? current.current_price_currency ?? 'EUR',
        cardmarket_reference: nextPrint?.cardmarket_product_url ?? nextPrint?.cardmarket_reference ?? lookup.cardmarket_product_url ?? lookup.cardmarket_reference ?? undefined,
        cardmarket_product_url: nextPrint?.cardmarket_product_url ?? lookup.cardmarket_product_url ?? undefined,
        cardmarket_product_slug: nextPrint?.cardmarket_product_slug ?? lookup.cardmarket_product_slug ?? undefined,
        cardmarket_set_slug: nextPrint?.cardmarket_set_slug ?? lookup.cardmarket_set_slug ?? undefined,
        cardmarket_set_name: nextPrint?.cardmarket_set_name ?? lookup.cardmarket_set_name ?? undefined,
        cardmarket_product_name: nextPrint?.cardmarket_product_name ?? lookup.cardmarket_product_name ?? undefined,
        cardmarket_variant_name: nextPrint?.cardmarket_variant_name ?? lookup.cardmarket_variant_name ?? undefined,
        cardmarket_category: nextPrint?.cardmarket_category ?? lookup.cardmarket_category ?? undefined,
        cardmarket_match_quality: nextPrint?.cardmarket_match_quality ?? lookup.cardmarket_match_quality ?? undefined,
        cardmarket_verified_at: nextPrint?.cardmarket_verified_at ?? lookup.cardmarket_verified_at ?? undefined,
        cardmarket_expected_rarity: nextPrint?.rarity ?? current.cardmarket_expected_rarity ?? undefined,
        cardmarket_expected_language: current.cardmarket_expected_language ?? current.language ?? undefined,
        cardmarket_expected_set_name: nextPrint?.set_name ?? lookup.cardmarket_set_name ?? current.cardmarket_expected_set_name ?? undefined,
        effect_text: lookup.effect_text,
        card_type: lookup.card_type,
        subtype: lookup.subtype,
        attribute: lookup.attribute,
        monster_type: lookup.monster_type,
        archetype: lookup.archetype,
        atk: lookup.atk ?? undefined,
        defense: lookup.defense ?? undefined,
        level: lookup.level ?? undefined,
        rank: lookup.rank ?? undefined,
        link_rating: lookup.link_rating ?? undefined,
        link_arrows: lookup.link_arrows || [],
        pendulum_scale: lookup.pendulum_scale ?? undefined,
        pendulum_effect: lookup.pendulum_effect,
        spell_trap_type: lookup.spell_trap_type,
        external_ids: {
          ...current.external_ids,
          ...(lookup.ygoprodeck_id ? { ygoprodeck: lookup.ygoprodeck_id } : {}),
          ...(lookup.cardmarket_product_url || lookup.cardmarket_reference ? { cardmarket: lookup.cardmarket_product_url || lookup.cardmarket_reference } : {}),
        },
      };
    });
  };

  const loadLookup = async (params: { external_id?: string; name?: string }, languageOverride?: string) => {
    setLookupLoading(true);
    try {
      const response = await api.get<CardLookupResponse>('/cards/lookup/autofill', {
        params: {
          ...params,
          language: languageOverride || form.language || settings.preferred_price_language,
        },
      });
      applyLookupPayload(response.data);
    } catch (requestError) {
      setLookupError(getApiErrorMessage(requestError));
    } finally {
      setLookupLoading(false);
    }
  };

  const loadCardmarketLink = async (url: string, languageOverride?: string) => {
    setCardmarketLoading(true);
    try {
      const response = await api.get<CardLookupResponse>('/cards/lookup/cardmarket-link', {
        params: {
          url,
          language: languageOverride || form.language || settings.preferred_price_language,
        },
      });
      applyLookupPayload(response.data);
      setCardmarketUrl(response.data.cardmarket_product_url || response.data.cardmarket_reference || url.trim());
      setLastImportedCardmarketUrl(response.data.cardmarket_product_url || response.data.cardmarket_reference || url.trim());
      if (response.data.ygoprodeck_id) {
        const importedSuggestion: CardLookupSuggestion = {
          external_id: response.data.ygoprodeck_id,
          name: response.data.name,
          card_type: response.data.card_type,
          attribute: response.data.attribute,
          monster_type: response.data.monster_type,
          image_url: response.data.image_url,
          set_count: response.data.print_options.length,
          default_market_price: response.data.default_market_price,
          default_price_currency: response.data.default_price_currency,
          price_source: response.data.price_source,
        };
        setSelectedSuggestion(importedSuggestion);
        setSuggestions((current) => {
          const remaining = current.filter((item) => item.external_id !== importedSuggestion.external_id);
          return [importedSuggestion, ...remaining];
        });
      }
    } catch (requestError) {
      setLookupError(getApiErrorMessage(requestError));
    } finally {
      setCardmarketLoading(false);
    }
  };

  useEffect(() => {
    if (!open) {
      return;
    }

    const query = debouncedSearchTerm;
    if (query.length < 2) {
      setSuggestions(selectedSuggestion ? [selectedSuggestion] : []);
      setSearchLoading(false);
      return;
    }

    let active = true;
    const loadSuggestions = async () => {
      setSearchLoading(true);
      try {
        const response = await api.get<CardLookupSuggestion[]>('/cards/lookup/search', {
          params: {
            q: query,
            language: settings.preferred_search_language || form.language,
            limit: 8,
          },
        });
        if (!active) {
          return;
        }

        const nextSuggestions = [...response.data];
        if (selectedSuggestion && !nextSuggestions.some((option) => option.external_id === selectedSuggestion.external_id)) {
          nextSuggestions.unshift(selectedSuggestion);
        }
        setSuggestions(nextSuggestions);
      } catch {
        if (active) {
          setSuggestions(selectedSuggestion ? [selectedSuggestion] : []);
        }
      } finally {
        if (active) {
          setSearchLoading(false);
        }
      }
    };

    void loadSuggestions();

    return () => {
      active = false;
    };
  }, [debouncedSearchTerm, form.language, open, selectedSuggestion, settings.preferred_search_language]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const trimmedUrl = cardmarketUrl.trim();
    if (!isCardmarketUrl(trimmedUrl) || trimmedUrl === lastImportedCardmarketUrl) {
      return;
    }

    const handle = window.setTimeout(() => {
      void loadCardmarketLink(trimmedUrl);
    }, 300);

    return () => {
      window.clearTimeout(handle);
    };
  }, [cardmarketUrl, lastImportedCardmarketUrl, open]);

  useEffect(() => {
    if (!open || !lookupData || !resolvedPrint) {
      return;
    }

    const resolvedUrl = (resolvedPrint.cardmarket_product_url || resolvedPrint.cardmarket_reference || '').trim();
    if (!isCardmarketUrl(resolvedUrl) || resolvedUrl === lastImportedCardmarketUrl) {
      return;
    }
    if (resolvedUrl === cardmarketUrl.trim()) {
      return;
    }

    setCardmarketUrl(resolvedUrl);
  }, [cardmarketUrl, lastImportedCardmarketUrl, lookupData, open, resolvedPrint]);

  const handleSubmit = async () => {
    await onSubmit({
      ...form,
      quantity: Number(form.quantity) || 1,
      purchase_price:
        form.purchase_price === null || form.purchase_price === undefined || form.purchase_price === 0
          ? form.purchase_price
          : Number(form.purchase_price),
      current_market_price:
        form.current_market_price === null || form.current_market_price === undefined || form.current_market_price === 0
          ? form.current_market_price
          : Number(form.current_market_price),
      atk: form.atk === null || form.atk === undefined ? undefined : Number(form.atk),
      defense: form.defense === null || form.defense === undefined ? undefined : Number(form.defense),
      level: form.level === null || form.level === undefined ? undefined : Number(form.level),
      rank: form.rank === null || form.rank === undefined ? undefined : Number(form.rank),
      link_rating: form.link_rating === null || form.link_rating === undefined ? undefined : Number(form.link_rating),
      pendulum_scale: form.pendulum_scale === null || form.pendulum_scale === undefined ? undefined : Number(form.pendulum_scale),
      tags: tagText
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      external_ids: {
        ...form.external_ids,
        ...(ygoprodeckId ? { ygoprodeck: ygoprodeckId.trim() } : {}),
        ...(form.cardmarket_reference ? { cardmarket: form.cardmarket_reference.trim() } : {}),
      },
      link_arrows: form.link_arrows || [],
    });
  };

  const handleLookupSelectionChange = (field: keyof LookupSelection, value: string) => {
    if (!value) {
      updateForm({
        set_name: undefined,
        set_code: undefined,
        card_number: undefined,
        rarity: undefined,
        rarity_code: undefined,
        current_market_price: undefined,
      });
      return;
    }

    if (!lookupData) {
      updateForm({ [field]: value || undefined } as Partial<CardPayload>);
      return;
    }
    applyLookupPayload(lookupData, { [field]: value || undefined });
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth fullScreen={fullScreen} maxWidth="md">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2.25} sx={{ mt: 0.25 }}>
          {lookupError ? <Alert severity="error">{lookupError}</Alert> : null}

          {needsDisambiguation ? (
            <Alert severity="warning">
              Mehrere Druckvarianten gefunden. Die orange markierten Auswahlfelder brauchen noch eine Auswahl, damit Preis und Referenzen sauber
              zugeordnet werden koennen.
            </Alert>
          ) : null}

          {lookupData && resolvedPrint ? (
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Chip color="success" variant="outlined" label={`Erkannter Druck: ${resolvedPrint.display_label}`} />
              {lookupData.image_url ? (
                <Chip
                  variant="outlined"
                  label="Kartendaten geladen"
                  avatar={<Avatar alt={lookupData.name} src={resolveMediaUrl(lookupData.image_url)} />}
                />
              ) : null}
            </Stack>
          ) : null}

          <Grid container spacing={2} sx={{ mt: 0.1 }}>
            <Grid item xs={12}>
              <TextField
                label="Cardmarket-Link"
                fullWidth
                value={cardmarketUrl}
                onChange={(event) => setCardmarketUrl(event.target.value)}
                helperText={
                  isCardmarketUrl(cardmarketUrl)
                    ? 'Cardmarket-Link erkannt. Set, Raritaet, Nummer und Preis werden automatisch eingelesen.'
                    : 'Fuege optional einen Cardmarket-Link ein, um die Druckvariante direkt vorzubelegen.'
                }
                InputProps={{
                  endAdornment: cardmarketLoading ? <CircularProgress color="inherit" size={18} /> : undefined,
                }}
              />
            </Grid>

            <Grid item xs={12} md={6}>
              <Autocomplete<CardLookupSuggestion, false, false, true>
                freeSolo
                options={suggestions}
                loading={searchLoading}
                filterOptions={(options) => options}
                value={selectedSuggestion}
                inputValue={form.name}
                noOptionsText="Keine passenden Karten gefunden"
                loadingText="Suche Karten..."
                isOptionEqualToValue={(option, value) => typeof value !== 'string' && option.external_id === value.external_id}
                getOptionLabel={(option) => (typeof option === 'string' ? option : option.name)}
                onInputChange={(_, value, reason) => {
                  updateForm({ name: value });
                  if ((reason === 'input' || reason === 'clear') && selectedSuggestion && value.trim() !== selectedSuggestion.name.trim()) {
                    setSelectedSuggestion(null);
                    setLookupData(null);
                    setLookupError(null);
                    setYgoprodeckId('');
                  }
                }}
                onChange={(_, option) => {
                  if (typeof option === 'string') {
                    setSelectedSuggestion(null);
                    setLookupData(null);
                    setLookupError(null);
                    setYgoprodeckId('');
                    updateForm({ name: option });
                    return;
                  }
                  setSelectedSuggestion(option);
                  if (!option) {
                    setLookupData(null);
                    setLookupError(null);
                    setYgoprodeckId('');
                    return;
                  }
                  void loadLookup({ external_id: option.external_id });
                }}
                renderOption={(props, option) => (
                  <Box component="li" {...props} sx={{ alignItems: 'flex-start', gap: 1.5 }}>
                    <Avatar src={resolveMediaUrl(option.image_url)} variant="rounded" sx={{ width: 42, height: 58 }} />
                    <Box>
                      <Typography fontWeight={700}>{option.name}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {[option.card_type, option.attribute, option.monster_type].filter(Boolean).join(' | ') || 'Keine Typdaten'}
                      </Typography>
                      <Stack direction="row" spacing={0.75} sx={{ mt: 0.85 }} flexWrap="wrap" useFlexGap>
                        <Chip label={`${option.set_count} Drucke`} size="small" variant="outlined" />
                        {option.default_market_price ? (
                          <Chip
                            label={`${option.default_market_price.toFixed(2)} ${option.default_price_currency || ''}`.trim()}
                            size="small"
                            color="secondary"
                            variant="outlined"
                          />
                        ) : null}
                      </Stack>
                    </Box>
                  </Box>
                )}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Kartenname"
                    helperText={
                      lookupData
                        ? 'Karte erkannt. Bei mehreren Drucken bitte Set, Setcode oder Seltenheit unten festlegen.'
                        : 'Tippe einen Namen ein und waehle einen Vorschlag aus, damit Kartendaten und IDs uebernommen werden.'
                    }
                    InputProps={{
                      ...params.InputProps,
                      endAdornment: (
                        <>
                          {searchLoading || lookupLoading || cardmarketLoading ? <CircularProgress color="inherit" size={18} sx={{ mr: 1 }} /> : null}
                          {params.InputProps.endAdornment}
                        </>
                      ),
                    }}
                  />
                )}
              />
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField
                select
                label="Sprache"
                fullWidth
                value={form.language}
                onChange={(event) => {
                  const nextLanguage = event.target.value;
                  updateForm({ language: nextLanguage });
                  if (isCardmarketUrl(cardmarketUrl)) {
                    void loadCardmarketLink(cardmarketUrl, nextLanguage);
                  } else if (lookupData?.ygoprodeck_id) {
                    void loadLookup({ external_id: lookupData.ygoprodeck_id }, nextLanguage);
                  }
                }}
              >
                <MenuItem value="de">Deutsch</MenuItem>
                <MenuItem value="en">Englisch</MenuItem>
                <MenuItem value="jp">Japanisch</MenuItem>
              </TextField>
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField select label="Zustand" fullWidth value={form.condition} onChange={(event) => updateForm({ condition: event.target.value })}>
                <MenuItem value="near_mint">Near Mint</MenuItem>
                <MenuItem value="excellent">Excellent</MenuItem>
                <MenuItem value="good">Good</MenuItem>
                <MenuItem value="played">Played</MenuItem>
                <MenuItem value="poor">Poor</MenuItem>
              </TextField>
            </Grid>

            <Grid item xs={12} md={6}>
              {lookupData && setNameOptions.length ? (
                <TextField
                  select
                  label="Setname"
                  fullWidth
                  color={highlightSetName ? 'warning' : 'primary'}
                  value={form.set_name || ''}
                  onChange={(event) => handleLookupSelectionChange('set_name', event.target.value)}
                  helperText={highlightSetName ? 'Mehrere Setnamen verfuegbar' : undefined}
                >
                  <MenuItem value="">Noch offen</MenuItem>
                  {setNameOptions.map((option) => (
                    <MenuItem key={option} value={option}>
                      {option}
                    </MenuItem>
                  ))}
                </TextField>
              ) : (
                <TextField label="Setname" fullWidth value={form.set_name || ''} onChange={(event) => updateForm({ set_name: event.target.value })} />
              )}
            </Grid>

            <Grid item xs={12} md={3}>
              {lookupData && setCodeOptions.length ? (
                <TextField
                  select
                  label="Setcode"
                  fullWidth
                  color={highlightSetCode ? 'warning' : 'primary'}
                  value={form.set_code || ''}
                  onChange={(event) => handleLookupSelectionChange('set_code', event.target.value)}
                  helperText={highlightSetCode ? 'Mehrere Setcodes verfuegbar' : undefined}
                >
                  <MenuItem value="">Noch offen</MenuItem>
                  {setCodeOptions.map((option) => (
                    <MenuItem key={option} value={option}>
                      {option}
                    </MenuItem>
                  ))}
                </TextField>
              ) : (
                <TextField label="Setcode" fullWidth value={form.set_code || ''} onChange={(event) => updateForm({ set_code: event.target.value })} />
              )}
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField label="Kartennummer" fullWidth value={form.card_number || ''} onChange={(event) => updateForm({ card_number: event.target.value })} />
            </Grid>

            <Grid item xs={12} md={4}>
              {lookupData && rarityOptions.length ? (
                <TextField
                  select
                  label="Seltenheit"
                  fullWidth
                  color={highlightRarity ? 'warning' : 'primary'}
                  value={form.rarity || ''}
                  onChange={(event) => handleLookupSelectionChange('rarity', event.target.value)}
                  helperText={highlightRarity ? 'Mehrere Seltenheiten verfuegbar' : undefined}
                >
                  <MenuItem value="">Noch offen</MenuItem>
                  {rarityOptions.map((option) => (
                    <MenuItem key={option} value={option}>
                      {option}
                    </MenuItem>
                  ))}
                </TextField>
              ) : (
                <TextField label="Seltenheit" fullWidth value={form.rarity || ''} onChange={(event) => updateForm({ rarity: event.target.value })} />
              )}
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField
                label="Lagerort"
                select
                fullWidth
                value={form.storage_location_id || ''}
                onChange={(event) => updateForm({ storage_location_id: event.target.value ? Number(event.target.value) : undefined })}
              >
                <MenuItem value="">Nicht zugewiesen</MenuItem>
                {storageLocations.map((location) => (
                  <MenuItem key={location.id} value={location.id}>
                    {location.path_cache}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField label="Menge" type="number" fullWidth value={form.quantity} onChange={(event) => updateForm({ quantity: Number(event.target.value) })} />
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField
                label="Einkaufspreis"
                type="number"
                fullWidth
                value={form.purchase_price ?? ''}
                onChange={(event) => updateForm({ purchase_price: event.target.value ? Number(event.target.value) : undefined })}
              />
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField
                label="Marktpreis"
                type="number"
                fullWidth
                color={needsDisambiguation ? 'warning' : 'primary'}
                value={form.current_market_price ?? ''}
                onChange={(event) => updateForm({ current_market_price: event.target.value ? Number(event.target.value) : undefined })}
                helperText={marketPriceHelperText || undefined}
              />
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField label="Waehrung" fullWidth value={form.current_price_currency} onChange={(event) => updateForm({ current_price_currency: event.target.value })} />
            </Grid>

            <Grid item xs={12} md={6}>
              <TextField
                label="Cardmarket-Referenz"
                fullWidth
                color={lookupData && !form.cardmarket_reference ? 'warning' : 'primary'}
                value={form.cardmarket_reference || ''}
                onChange={(event) => updateForm({ cardmarket_reference: event.target.value })}
                helperText={
                  lookupData
                    ? form.cardmarket_reference
                      ? 'Best-effort aus vorhandenen lokalen Mappings uebernommen.'
                      : 'Ohne offizielles Cardmarket-Mapping konnte keine Referenz automatisch gesetzt werden.'
                    : undefined
                }
              />
            </Grid>

            <Grid item xs={12} md={6}>
              <TextField
                label="YGOPRODeck-ID"
                fullWidth
                value={ygoprodeckId}
                onChange={(event) => setYgoprodeckId(event.target.value)}
                helperText={lookupData ? 'Wird nach erfolgreicher Kartenerkennung automatisch uebernommen.' : undefined}
              />
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField label="Kartentyp" fullWidth value={form.card_type || ''} onChange={(event) => updateForm({ card_type: event.target.value })} />
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField label="Attribut" fullWidth value={form.attribute || ''} onChange={(event) => updateForm({ attribute: event.target.value })} />
            </Grid>

            <Grid item xs={12} md={4}>
              <TextField label="Monster-Typ" fullWidth value={form.monster_type || ''} onChange={(event) => updateForm({ monster_type: event.target.value })} />
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField label="ATK" type="number" fullWidth value={form.atk ?? ''} onChange={(event) => updateForm({ atk: event.target.value ? Number(event.target.value) : undefined })} />
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField label="DEF" type="number" fullWidth value={form.defense ?? ''} onChange={(event) => updateForm({ defense: event.target.value ? Number(event.target.value) : undefined })} />
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField label="Level" type="number" fullWidth value={form.level ?? ''} onChange={(event) => updateForm({ level: event.target.value ? Number(event.target.value) : undefined })} />
            </Grid>

            <Grid item xs={12} md={3}>
              <TextField label="Rank" type="number" fullWidth value={form.rank ?? ''} onChange={(event) => updateForm({ rank: event.target.value ? Number(event.target.value) : undefined })} />
            </Grid>

            <Grid item xs={12}>
              <TextField label="Tags (kommagetrennt)" fullWidth value={tagText} onChange={(event) => setTagText(event.target.value)} />
            </Grid>

            <Grid item xs={12}>
              <TextField label="Notizen" fullWidth multiline minRows={2} value={form.notes || ''} onChange={(event) => updateForm({ notes: event.target.value })} />
            </Grid>

            <Grid item xs={12}>
              <TextField
                label="Effekttext"
                fullWidth
                multiline
                minRows={4}
                value={form.effect_text || ''}
                onChange={(event) => updateForm({ effect_text: event.target.value })}
              />
            </Grid>
          </Grid>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: { xs: 2, sm: 3 }, py: 2, position: fullScreen ? 'sticky' : 'static', bottom: 0, bgcolor: 'background.paper' }}>
        <Button onClick={onClose} disabled={loading}>
          Abbrechen
        </Button>
        <Button onClick={handleSubmit} variant="contained" disabled={loading || !form.name.trim()}>
          Speichern
        </Button>
      </DialogActions>
    </Dialog>
  );
}
