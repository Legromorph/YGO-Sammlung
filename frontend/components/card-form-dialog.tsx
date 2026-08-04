import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  Stack,
  TextField,
  useMediaQuery,
  useTheme,
} from '@mui/material';

import api, { getApiErrorMessage } from '../lib/api';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import { useAppSettings } from './app-settings-provider';
import CardLookupFields from './card-form/card-lookup-fields';
import InventoryFields from './card-form/inventory-fields';
import {
  LookupSelection,
  SetGroupOption,
  buildDefaultPayload,
  buildLookupSelectionFromPrint,
  buildSearchLanguageQuery,
  buildSetCodeForLanguage,
  buildSetGroupOptions,
  buildStoredVariantKey,
  buildVariantKey,
  defaultPayload,
  getLanguageAwarePrintOptions,
  isCardmarketUrl,
  normalizeOptionalPositiveNumber,
  normalizeSetGroupKey,
  parseLanguageList,
  priceMatchQualityForSource,
  resolveSelectedPrint,
  sanitizeSelection,
  trimValue,
  validateSetCodeLanguage,
} from './card-form/card-form-utils';
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
      current_market_price: initialValue.stored_market_price ?? initialValue.current_market_price,
      current_price_currency: initialValue.stored_price_currency || initialValue.current_price_currency,
      current_price_source: initialValue.last_price_source,
      current_price_match_quality: initialValue.last_price_match_quality,
      current_price_note: initialValue.last_price_note,
      storage_location_id: initialValue.storage_location_id,
      cardmarket_reference: initialValue.cardmarket_reference,
      cardmarket_product_url: initialValue.cardmarket_product_url,
      cardmarket_product_slug: initialValue.cardmarket_product_slug,
      cardmarket_set_slug: initialValue.cardmarket_set_slug,
      cardmarket_set_name: initialValue.cardmarket_set_name,
      cardmarket_product_name: initialValue.cardmarket_product_name,
      cardmarket_variant_name: initialValue.cardmarket_variant_name,
      cardmarket_category: initialValue.cardmarket_category,
      cardmarket_expected_rarity: initialValue.cardmarket_expected_rarity,
      cardmarket_expected_language: initialValue.cardmarket_expected_language,
      cardmarket_expected_set_name: initialValue.cardmarket_expected_set_name,
      notes: initialValue.notes,
      tags: initialValue.tags || [],
      external_ids: externalIds,
      effect_text: initialValue.effect_text,
      card_type: initialValue.card_type,
      card_kind: initialValue.card_kind,
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
  }, [initialValue, open, settings.preferred_card_language, settings.preferred_currency]);

  const updateForm = (patch: Partial<CardPayload>) => setForm((current) => ({ ...current, ...patch }));

  const clearLookupResult = (nextName?: string) => {
    setLookupData(null);
    setLookupError(null);
    setYgoprodeckId('');
    setForm((current) => {
      const nextExternalIds = { ...(current.external_ids || {}) };
      delete nextExternalIds.ygoprodeck;
      delete nextExternalIds.cardmarket;
      return {
        ...current,
        name: nextName ?? current.name,
        set_name: undefined,
        set_code: undefined,
        card_number: undefined,
        rarity: undefined,
        rarity_code: undefined,
        current_market_price: undefined,
        current_price_source: undefined,
        current_price_match_quality: undefined,
        current_price_note: undefined,
        cardmarket_reference: undefined,
        cardmarket_product_url: undefined,
        cardmarket_product_slug: undefined,
        cardmarket_set_slug: undefined,
        cardmarket_set_name: undefined,
        cardmarket_product_name: undefined,
        cardmarket_variant_name: undefined,
        cardmarket_category: undefined,
        cardmarket_expected_rarity: undefined,
        cardmarket_expected_set_name: undefined,
        effect_text: undefined,
        card_type: undefined,
        card_kind: undefined,
        subtype: undefined,
        attribute: undefined,
        monster_type: undefined,
        archetype: undefined,
        atk: undefined,
        defense: undefined,
        level: undefined,
        rank: undefined,
        link_rating: undefined,
        link_arrows: [],
        pendulum_scale: undefined,
        pendulum_effect: undefined,
        spell_trap_type: undefined,
        external_ids: nextExternalIds,
      };
    });
  };

  const searchLanguageQuery = useMemo(
    () => buildSearchLanguageQuery(settings.preferred_search_language, form.language || settings.preferred_card_language || defaultPayload.language),
    [form.language, settings.preferred_card_language, settings.preferred_search_language],
  );
  const searchLanguageLabel = useMemo(
    () => parseLanguageList(searchLanguageQuery, []).map((value) => value.toUpperCase()).join(', '),
    [searchLanguageQuery],
  );

  const printOptions = useMemo(
    () => getLanguageAwarePrintOptions(lookupData?.print_options ?? [], form.language),
    [form.language, lookupData?.print_options],
  );
  const selection = useMemo<LookupSelection>(
    () => ({
      set_name: form.set_name,
      set_code: form.set_code,
      rarity: form.rarity,
      variant_key: buildStoredVariantKey(form),
    }),
    [form],
  );
  const setGroupOptions = useMemo(() => buildSetGroupOptions(printOptions), [printOptions]);
  const selectedSetGroupKey = useMemo(
    () => (selection.set_name || selection.set_code ? normalizeSetGroupKey({ set_name: selection.set_name, set_code: selection.set_code }) : ''),
    [selection.set_code, selection.set_name],
  );
  const selectedSetGroup = useMemo(
    () => setGroupOptions.find((option) => option.key === selectedSetGroupKey) ?? null,
    [selectedSetGroupKey, setGroupOptions],
  );
  const variantOptions = useMemo(() => selectedSetGroup?.options ?? [], [selectedSetGroup]);
  const resolvedPrint = useMemo(
    () => resolveSelectedPrint(printOptions, selection),
    [printOptions, selection],
  );
  const selectedVariantKey = useMemo(() => (resolvedPrint ? buildVariantKey(resolvedPrint) : ''), [resolvedPrint]);

  const needsDisambiguation = Boolean(lookupData && printOptions.length > 1 && !resolvedPrint);
  const needsSetSelection = Boolean(lookupData && setGroupOptions.length > 1 && !selectedSetGroup);
  const needsVariantSelection = Boolean(lookupData && selectedSetGroup && variantOptions.length > 1 && !resolvedPrint);
  const trimmedCardmarketUrl = cardmarketUrl.trim();
  const cardmarketUrlError = Boolean(trimmedCardmarketUrl && !isCardmarketUrl(trimmedCardmarketUrl));
  const showManualPrintFields = !lookupData && Boolean(form.name.trim());
  const showInventoryFields = showManualPrintFields || Boolean(resolvedPrint) || Boolean(lookupData && !printOptions.length);
  const setCodeLanguageError = useMemo(
    () => validateSetCodeLanguage(form.language, form.set_code),
    [form.language, form.set_code],
  );

  const marketPriceHelperText = useMemo(() => {
    const messages: string[] = [];
    if (resolvedPrint?.price_note) {
      messages.push(resolvedPrint.price_note);
    } else if (lookupData?.price_note) {
      messages.push(lookupData.price_note);
    }
    if (lookupData && !lookupData.condition_price_supported && form.condition !== 'near_mint') {
      messages.push('Der gewählte Zustand wird aktuell nicht automatisch in den Provider-Preis eingerechnet. Bitte Marktpreis prüfen.');
    }
    return messages.join(' ');
  }, [form.condition, lookupData, resolvedPrint]);

  const applyLookupPayload = (lookup: CardLookupResponse, selectionPatch: LookupSelection = {}, languageOverride?: string) => {
    setLookupData(lookup);
    setLookupError(null);
    setYgoprodeckId(lookup.ygoprodeck_id || '');
    setForm((current) => {
      const targetLanguage = (languageOverride || current.language || form.language || settings.preferred_card_language || defaultPayload.language).trim().toLowerCase();
      const languageAwarePrintOptions = getLanguageAwarePrintOptions(lookup.print_options, targetLanguage);
      const requestedSetCode =
        selectionPatch.set_code !== undefined
          ? trimValue(selectionPatch.set_code)
          : validateSetCodeLanguage(targetLanguage, current.set_code)
            ? buildSetCodeForLanguage(current.set_code, targetLanguage)
            : trimValue(current.set_code);

      let nextSelection = sanitizeSelection(languageAwarePrintOptions, {
        set_name: selectionPatch.set_name !== undefined ? selectionPatch.set_name : current.set_name,
        set_code: requestedSetCode,
        rarity: selectionPatch.rarity !== undefined ? selectionPatch.rarity : current.rarity,
        variant_key: selectionPatch.variant_key !== undefined ? selectionPatch.variant_key : buildStoredVariantKey(current),
      });
      let nextPrint = resolveSelectedPrint(languageAwarePrintOptions, nextSelection);

      if (!nextPrint && languageAwarePrintOptions.length === 1) {
        nextPrint = languageAwarePrintOptions[0];
        nextSelection = {
          set_name: nextPrint.set_name ?? undefined,
          set_code: nextPrint.set_code ?? undefined,
          rarity: nextPrint.rarity ?? undefined,
        };
      }

      const exactCardmarketReference =
        nextPrint?.cardmarket_product_url ??
        nextPrint?.cardmarket_reference ??
        (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_product_url ?? lookup.cardmarket_reference ?? undefined : undefined);
      const selectedMarketPrice = nextPrint?.market_price ?? lookup.default_market_price ?? undefined;
      const selectedPriceSource = nextPrint?.price_source ?? lookup.price_source ?? undefined;
      const selectedPriceNote = nextPrint?.price_note ?? lookup.price_note ?? undefined;

      return {
        ...current,
        language: targetLanguage,
        name: lookup.name,
        set_name: nextPrint?.set_name ?? nextSelection.set_name ?? undefined,
        set_code: nextPrint?.set_code ?? nextSelection.set_code ?? requestedSetCode ?? undefined,
        card_number: nextPrint?.card_number ?? undefined,
        rarity: nextPrint?.rarity ?? nextSelection.rarity ?? undefined,
        rarity_code: nextPrint?.rarity_code ?? undefined,
        current_market_price: selectedMarketPrice,
        current_price_currency: nextPrint?.price_currency ?? lookup.default_price_currency ?? current.current_price_currency ?? 'EUR',
        current_price_source: selectedMarketPrice !== undefined ? selectedPriceSource : undefined,
        current_price_match_quality:
          selectedMarketPrice !== undefined
            ? priceMatchQualityForSource(selectedPriceSource, nextPrint?.cardmarket_match_quality)
            : undefined,
        current_price_note: selectedMarketPrice !== undefined ? selectedPriceNote : undefined,
        cardmarket_reference: exactCardmarketReference,
        cardmarket_product_url: nextPrint?.cardmarket_product_url ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_product_url ?? undefined : undefined),
        cardmarket_product_slug: nextPrint?.cardmarket_product_slug ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_product_slug ?? undefined : undefined),
        cardmarket_set_slug: nextPrint?.cardmarket_set_slug ?? undefined,
        cardmarket_set_name: nextPrint?.cardmarket_set_name ?? nextSelection.set_name ?? lookup.cardmarket_set_name ?? undefined,
        cardmarket_product_name: nextPrint?.cardmarket_product_name ?? lookup.cardmarket_product_name ?? lookup.name,
        cardmarket_variant_name: nextPrint?.cardmarket_variant_name ?? undefined,
        cardmarket_category: nextPrint?.cardmarket_category ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_category ?? undefined : undefined),
        cardmarket_expected_rarity: nextPrint?.rarity ?? nextSelection.rarity ?? undefined,
        cardmarket_expected_language: targetLanguage,
        cardmarket_expected_set_name: nextPrint?.set_name ?? nextSelection.set_name ?? lookup.cardmarket_set_name ?? undefined,
        effect_text: lookup.effect_text,
        card_type: lookup.card_type,
        card_kind: lookup.card_kind,
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
          ...(exactCardmarketReference ? { cardmarket: exactCardmarketReference } : {}),
        },
      };
    });
  };

  const loadLookup = async (params: { external_id?: string; name?: string }, languageOverride?: string) => {
    setLookupLoading(true);
    try {
      const lookupLanguageQuery = buildSearchLanguageQuery(
        settings.preferred_search_language,
        languageOverride || form.language || settings.preferred_card_language || defaultPayload.language,
      );
      const response = await api.get<CardLookupResponse>('/cards/lookup/autofill', {
        params: {
          ...params,
          language: lookupLanguageQuery,
        },
      });
      applyLookupPayload(response.data, {}, languageOverride);
    } catch (requestError) {
      setLookupError(getApiErrorMessage(requestError));
    } finally {
      setLookupLoading(false);
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
            language: searchLanguageQuery,
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
  }, [debouncedSearchTerm, open, searchLanguageQuery, selectedSuggestion]);

  useEffect(() => {
    if (!open || !lookupData || !resolvedPrint) {
      return;
    }

    const resolvedUrl = (resolvedPrint.cardmarket_product_url || resolvedPrint.cardmarket_reference || '').trim();
    if (!isCardmarketUrl(resolvedUrl)) {
      return;
    }
    if (resolvedUrl === cardmarketUrl.trim()) {
      return;
    }

    setCardmarketUrl(resolvedUrl);
  }, [cardmarketUrl, lookupData, open, resolvedPrint]);

  useEffect(() => {
    if (!open || !lookupData || resolvedPrint || selectedSetGroup || setGroupOptions.length !== 1) {
      return;
    }

    const onlySet = setGroupOptions[0];
    const primaryOption = onlySet.options[0];
    if (!primaryOption) {
      return;
    }

    applyLookupPayload(lookupData, {
      set_name: primaryOption.set_name || '',
      set_code: primaryOption.set_code || '',
      rarity: onlySet.options.length === 1 ? primaryOption.rarity || '' : '',
      variant_key: '',
    });
  }, [lookupData, open, resolvedPrint, selectedSetGroup, setGroupOptions]);

  const handleSubmit = async () => {
    if (setCodeLanguageError) {
      return;
    }
    const manualCardmarketUrl = isCardmarketUrl(trimmedCardmarketUrl) ? trimmedCardmarketUrl : undefined;
    await onSubmit({
      ...form,
      quantity: Number(form.quantity) || 1,
      purchase_price:
        form.purchase_price === null || form.purchase_price === undefined || form.purchase_price === 0
          ? form.purchase_price
          : Number(form.purchase_price),
      current_market_price: normalizeOptionalPositiveNumber(form.current_market_price),
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
      cardmarket_reference: manualCardmarketUrl ?? form.cardmarket_reference,
      cardmarket_product_url: manualCardmarketUrl ?? form.cardmarket_product_url,
      external_ids: {
        ...form.external_ids,
        ...(ygoprodeckId ? { ygoprodeck: ygoprodeckId.trim() } : {}),
        ...(manualCardmarketUrl || form.cardmarket_reference ? { cardmarket: (manualCardmarketUrl || form.cardmarket_reference || '').trim() } : {}),
      },
      link_arrows: form.link_arrows || [],
    });
  };

  const handleSetGroupChange = (groupKey: string) => {
    if (!lookupData) {
      return;
    }

    if (!groupKey) {
      updateForm({
        set_name: undefined,
        set_code: undefined,
        card_number: undefined,
        rarity: undefined,
        rarity_code: undefined,
        current_market_price: lookupData.default_market_price ?? undefined,
        current_price_source: lookupData.default_market_price != null ? lookupData.price_source : undefined,
        current_price_match_quality:
          lookupData.default_market_price != null
            ? priceMatchQualityForSource(lookupData.price_source, lookupData.cardmarket_match_quality)
            : undefined,
        current_price_note: lookupData.default_market_price != null ? lookupData.price_note : undefined,
        cardmarket_reference: undefined,
        cardmarket_product_url: undefined,
        cardmarket_product_slug: undefined,
        cardmarket_set_slug: undefined,
        cardmarket_variant_name: undefined,
      });
      return;
    }

    const nextGroup = setGroupOptions.find((option) => option.key === groupKey);
    const primaryOption = nextGroup?.options[0];
    if (!nextGroup || !primaryOption) {
      return;
    }

    applyLookupPayload(lookupData, {
      set_name: primaryOption.set_name || '',
      set_code: primaryOption.set_code || '',
      rarity: nextGroup.options.length === 1 ? primaryOption.rarity || '' : '',
      variant_key: '',
    });
  };

  const handleVariantChange = (variantKey: string) => {
    if (!lookupData || !selectedSetGroup) {
      return;
    }

    const nextVariant = variantOptions.find((option) => buildVariantKey(option) === variantKey);
    if (!nextVariant) {
      return;
    }

    applyLookupPayload(lookupData, buildLookupSelectionFromPrint(nextVariant));
  };

  const submitDisabled = loading || !form.name.trim() || cardmarketUrlError || Boolean(setCodeLanguageError) || Boolean(lookupData && printOptions.length > 1 && !resolvedPrint);

  return (
    <Dialog open={open} onClose={onClose} fullWidth fullScreen={fullScreen} maxWidth="md">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2.25} sx={{ mt: 0.25 }}>
          {lookupError ? <Alert severity="error">{lookupError}</Alert> : null}

          {needsDisambiguation ? (
            <Alert severity="warning">
              {needsSetSelection
                ? 'Karte erkannt. Bitte jetzt zuerst das richtige Set wählen.'
                : 'Das Set ist erkannt. Bitte jetzt noch die passende Rarität bzw. Variante wählen, bevor die restlichen Felder freigeschaltet werden.'}
            </Alert>
          ) : null}


          <Grid container spacing={2} sx={{ mt: 0.1 }}>
            <Grid item xs={12}>
              <TextField
                label="Cardmarket-Link"
                fullWidth
                value={cardmarketUrl}
                error={cardmarketUrlError}
                onChange={(event) => {
                  const nextUrl = event.target.value;
                  setCardmarketUrl(nextUrl);
                  setForm((current) => {
                    const nextExternalIds = { ...current.external_ids };
                    delete nextExternalIds.cardmarket;
                    return {
                      ...current,
                      cardmarket_reference: nextUrl.trim() || undefined,
                      cardmarket_product_url: isCardmarketUrl(nextUrl.trim()) ? nextUrl.trim() : undefined,
                      cardmarket_product_slug: undefined,
                      cardmarket_set_slug: undefined,
                      cardmarket_variant_name: undefined,
                      external_ids: nextExternalIds,
                    };
                  });
                }}
                helperText={
                  cardmarketUrlError
                    ? 'Bitte einen gültigen Cardmarket-Produktlink eintragen.'
                    : 'Der Link wird ohne Seitenabruf gespeichert und kann anschließend in den Kartendetails bestätigt werden.'
                }
              />
            </Grid>

            <CardLookupFields
              lookupData={lookupData}
              suggestions={suggestions}
              selectedSuggestion={selectedSuggestion}
              cardName={form.name}
              searchLoading={searchLoading}
              lookupLoading={lookupLoading}
              searchLanguageLabel={searchLanguageLabel}
              setGroupOptions={setGroupOptions}
              selectedSetGroup={selectedSetGroup}
              resolvedPrint={resolvedPrint}
              variantOptions={variantOptions}
              selectedVariantKey={selectedVariantKey}
              needsSetSelection={needsSetSelection}
              needsVariantSelection={needsVariantSelection}
              showManualPrintFields={showManualPrintFields}
              setName={form.set_name}
              setCode={form.set_code}
              rarity={form.rarity}
              setCodeLanguageError={setCodeLanguageError}
              onNameInputChange={(value, reason) => {
                if (
                  (reason === 'input' || reason === 'clear') &&
                  selectedSuggestion &&
                  value.trim() !== selectedSuggestion.name.trim()
                ) {
                  setSelectedSuggestion(null);
                  clearLookupResult(value);
                  return;
                }
                updateForm({ name: value });
              }}
              onSuggestionChange={(option) => {
                if (typeof option === 'string') {
                  setSelectedSuggestion(null);
                  clearLookupResult(option);
                  return;
                }
                setSelectedSuggestion(option);
                if (!option) {
                  clearLookupResult(form.name);
                  return;
                }
                void loadLookup({ external_id: option.external_id });
              }}
              onSetGroupChange={handleSetGroupChange}
              onVariantChange={handleVariantChange}
              onManualPrintChange={updateForm}
            />

            <InventoryFields
              visible={showInventoryFields}
              form={form}
              hasLookup={Boolean(lookupData)}
              storageLocations={storageLocations}
              setCodeLanguageError={setCodeLanguageError}
              marketPriceHelperText={marketPriceHelperText}
              tagText={tagText}
              onLanguageChange={(nextLanguage) => {
                if (lookupData) {
                  applyLookupPayload(lookupData, {}, nextLanguage);
                  return;
                }
                updateForm({
                  language: nextLanguage,
                  set_code: buildSetCodeForLanguage(form.set_code, nextLanguage) || form.set_code,
                  cardmarket_expected_language: nextLanguage,
                });
              }}
              onUpdate={updateForm}
              onTagTextChange={setTagText}
            />
          </Grid>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: { xs: 2, sm: 3 }, py: 2, position: fullScreen ? 'sticky' : 'static', bottom: 0, bgcolor: 'background.paper' }}>
        <Button onClick={onClose} disabled={loading}>
          Abbrechen
        </Button>
        <Button onClick={handleSubmit} variant="contained" disabled={submitDisabled}>
          Speichern
        </Button>
      </DialogActions>
    </Dialog>
  );
}
