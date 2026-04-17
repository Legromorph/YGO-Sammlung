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

type SetGroupOption = {
  key: string;
  label: string;
  options: CardLookupPrintOption[];
};

const languageSetCodePrefixes: Record<string, string[]> = {
  de: ['DE'],
  en: ['EN'],
  fr: ['FR'],
  it: ['IT'],
  es: ['ES', 'SP'],
  pt: ['PT'],
  jp: ['JP'],
  ja: ['JP'],
  ko: ['KR'],
};

function extractSetCodeLanguagePrefix(setCode?: string | null): string | null {
  const normalizedSetCode = (setCode || '').trim().toUpperCase();
  if (!normalizedSetCode.includes('-')) {
    return null;
  }
  const suffix = normalizedSetCode.split('-', 2)[1] || '';
  const match = suffix.match(/^([A-Z]{2,3})/);
  return match ? match[1] : null;
}

function validateSetCodeLanguage(language: string, setCode?: string | null): string | null {
  const normalizedLanguage = (language || '').trim().toLowerCase();
  const expectedPrefixes = languageSetCodePrefixes[normalizedLanguage];
  if (!expectedPrefixes || !setCode?.trim()) {
    return null;
  }

  const detectedPrefix = extractSetCodeLanguagePrefix(setCode);
  if (!detectedPrefix || expectedPrefixes.includes(detectedPrefix)) {
    return null;
  }

  return `Setcode passt nicht zur Sprache ${normalizedLanguage.toUpperCase()}. Erwartet: ${expectedPrefixes.join(', ')} nach dem Bindestrich (z. B. POTD-${expectedPrefixes[0]}011).`;
}

function buildSetCodeForLanguage(setCode: string | null | undefined, language: string): string | null {
  const normalizedSetCode = (setCode || '').trim().toUpperCase();
  const expectedPrefixes = languageSetCodePrefixes[(language || '').trim().toLowerCase()];
  if (!normalizedSetCode || !expectedPrefixes?.length) {
    return null;
  }
  if (!normalizedSetCode.includes('-')) {
    return normalizedSetCode;
  }

  const [setPrefix, suffix = ''] = normalizedSetCode.split('-', 2);
  const match = suffix.match(/^([A-Z]{2,3})(.*)$/);
  if (!match) {
    return normalizedSetCode;
  }
  return `${setPrefix}-${expectedPrefixes[0]}${match[2] || ''}`;
}

function normalizeSetGroupKey(option: Pick<CardLookupPrintOption, 'set_name' | 'set_code'>): string {
  const normalizedSetCode = (option.set_code || '').trim().toUpperCase();
  if (normalizedSetCode.includes('-')) {
    const [series, suffix = ''] = normalizedSetCode.split('-', 2);
    const match = suffix.match(/^([A-Z]{2,3})(.*)$/);
    if (match) {
      return `${series}-${match[2] || ''}`.toUpperCase();
    }
    return normalizedSetCode;
  }
  return (option.set_name || '').trim().toLowerCase();
}

function buildSetGroupOptions(printOptions: CardLookupPrintOption[]): SetGroupOption[] {
  const groups = new Map<string, SetGroupOption>();
  for (const option of printOptions) {
    const key = normalizeSetGroupKey(option);
    const existing = groups.get(key);
    if (existing) {
      existing.options.push(option);
      continue;
    }
    const labelParts = [trimValue(option.set_name), trimValue(option.set_code)].filter(Boolean);
    groups.set(key, {
      key,
      label: labelParts.join(' | ') || 'Unbekanntes Set',
      options: [option],
    });
  }
  return Array.from(groups.values()).sort((left, right) => left.label.localeCompare(right.label));
}

function buildVariantKey(option: CardLookupPrintOption): string {
  return [trimValue(option.set_name), trimValue(option.set_code), trimValue(option.rarity), trimValue(option.card_number)].join('||');
}

function buildVariantLabel(option: CardLookupPrintOption): string {
  return [trimValue(option.rarity), trimValue(option.card_number), trimValue(option.set_code)].filter(Boolean).join(' | ') || option.display_label;
}

function normalizeAutocompleteText(value?: string | null): string {
  return (value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function parseLanguageList(value: string | undefined, fallback: string[] = ['de', 'en']): string[] {
  const values = Array.from(
    new Set(
      (value || '')
        .split(',')
        .map((entry) => entry.trim().toLowerCase())
        .filter(Boolean),
    ),
  );
  return values.length ? values : fallback;
}

function buildSearchLanguageQuery(preferredSearchLanguage: string | undefined, currentLanguage: string): string {
  const preferred = parseLanguageList(preferredSearchLanguage, []);
  const merged = Array.from(new Set([currentLanguage, 'de', 'en', ...preferred].filter(Boolean)));
  return merged.join(',');
}

function matchesPrintOptionLanguage(option: CardLookupPrintOption, language: string): boolean {
  const expectedPrefixes = languageSetCodePrefixes[(language || '').trim().toLowerCase()];
  if (!expectedPrefixes?.length) {
    return true;
  }
  const detectedPrefix = extractSetCodeLanguagePrefix(option.set_code);
  if (!detectedPrefix) {
    return true;
  }
  return expectedPrefixes.includes(detectedPrefix);
}

function translatePrintOptionLanguage(option: CardLookupPrintOption, language: string): CardLookupPrintOption {
  const translatedSetCode = buildSetCodeForLanguage(option.set_code, language) || option.set_code;
  return {
    ...option,
    set_code: translatedSetCode,
    card_number: option.card_number || trimValue(translatedSetCode?.split('-').pop()),
  };
}

function getLanguageAwarePrintOptions(printOptions: CardLookupPrintOption[], language: string): CardLookupPrintOption[] {
  if (!printOptions.length) {
    return [];
  }

  const groupedOptions = new Map<string, CardLookupPrintOption[]>();
  for (const option of printOptions) {
    const key = [normalizeSetGroupKey(option), trimValue(option.rarity), trimValue(option.card_number)].join('||');
    const existing = groupedOptions.get(key);
    if (existing) {
      existing.push(option);
      continue;
    }
    groupedOptions.set(key, [option]);
  }

  const sourceOptions = Array.from(groupedOptions.values()).map((options) => {
    const matchingOption = options.find((option) => matchesPrintOptionLanguage(option, language));
    return matchingOption ?? translatePrintOptionLanguage(options[0], language);
  });
  const seen = new Set<string>();

  return sourceOptions.filter((option) => {
    const key = [trimValue(option.set_name), trimValue(option.set_code), trimValue(option.rarity), trimValue(option.card_number)].join('||');
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

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

  const clearLookupResult = (nextName?: string) => {
    setLookupData(null);
    setLookupError(null);
    setYgoprodeckId('');
    setCardmarketUrl('');
    setLastImportedCardmarketUrl('');
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
        cardmarket_reference: undefined,
        cardmarket_product_url: undefined,
        cardmarket_product_slug: undefined,
        cardmarket_set_slug: undefined,
        cardmarket_set_name: undefined,
        cardmarket_product_name: undefined,
        cardmarket_variant_name: undefined,
        cardmarket_category: undefined,
        cardmarket_match_quality: undefined,
        cardmarket_verified_at: undefined,
        cardmarket_expected_rarity: undefined,
        cardmarket_expected_set_name: undefined,
        effect_text: undefined,
        card_type: undefined,
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
    }),
    [form.rarity, form.set_code, form.set_name],
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
  const showInventoryFields = !lookupData || Boolean(resolvedPrint);
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
      messages.push('Der gewaehlte Zustand wird aktuell nicht automatisch in den Provider-Preis eingerechnet. Bitte Marktpreis pruefen.');
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

      return {
        ...current,
        language: targetLanguage,
        name: lookup.name,
        set_name: nextPrint?.set_name ?? nextSelection.set_name ?? undefined,
        set_code: nextPrint?.set_code ?? nextSelection.set_code ?? requestedSetCode ?? undefined,
        card_number: nextPrint?.card_number ?? undefined,
        rarity: nextPrint?.rarity ?? nextSelection.rarity ?? undefined,
        rarity_code: nextPrint?.rarity_code ?? undefined,
        current_market_price: nextPrint?.market_price ?? lookup.default_market_price ?? undefined,
        current_price_currency: nextPrint?.price_currency ?? lookup.default_price_currency ?? current.current_price_currency ?? 'EUR',
        cardmarket_reference: exactCardmarketReference,
        cardmarket_product_url: nextPrint?.cardmarket_product_url ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_product_url ?? undefined : undefined),
        cardmarket_product_slug: nextPrint?.cardmarket_product_slug ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_product_slug ?? undefined : undefined),
        cardmarket_set_slug: nextPrint?.cardmarket_set_slug ?? undefined,
        cardmarket_set_name: nextPrint?.cardmarket_set_name ?? nextSelection.set_name ?? lookup.cardmarket_set_name ?? undefined,
        cardmarket_product_name: nextPrint?.cardmarket_product_name ?? lookup.cardmarket_product_name ?? lookup.name,
        cardmarket_variant_name: nextPrint?.cardmarket_variant_name ?? undefined,
        cardmarket_category: nextPrint?.cardmarket_category ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_category ?? undefined : undefined),
        cardmarket_match_quality: nextPrint?.cardmarket_match_quality ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_match_quality ?? undefined : undefined),
        cardmarket_verified_at: nextPrint?.cardmarket_verified_at ?? (languageAwarePrintOptions.length === 1 ? lookup.cardmarket_verified_at ?? undefined : undefined),
        cardmarket_expected_rarity: nextPrint?.rarity ?? nextSelection.rarity ?? undefined,
        cardmarket_expected_language: targetLanguage,
        cardmarket_expected_set_name: nextPrint?.set_name ?? nextSelection.set_name ?? lookup.cardmarket_set_name ?? undefined,
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

  const loadCardmarketLink = async (url: string, languageOverride?: string) => {
    setCardmarketLoading(true);
    try {
      const lookupLanguageQuery = buildSearchLanguageQuery(
        settings.preferred_search_language,
        languageOverride || form.language || settings.preferred_card_language || defaultPayload.language,
      );
      const response = await api.get<CardLookupResponse>('/cards/lookup/cardmarket-link', {
        params: {
          url,
          language: lookupLanguageQuery,
        },
      });
      applyLookupPayload(response.data, {}, languageOverride);
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
    });
  }, [lookupData, open, resolvedPrint, selectedSetGroup, setGroupOptions]);

  const handleSubmit = async () => {
    if (setCodeLanguageError) {
      return;
    }
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

    applyLookupPayload(lookupData, {
      set_name: nextVariant.set_name || '',
      set_code: nextVariant.set_code || '',
      rarity: nextVariant.rarity || '',
    });
  };

  const submitDisabled = loading || !form.name.trim() || Boolean(setCodeLanguageError) || Boolean(lookupData && printOptions.length > 1 && !resolvedPrint);

  return (
    <Dialog open={open} onClose={onClose} fullWidth fullScreen={fullScreen} maxWidth="md">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2.25} sx={{ mt: 0.25 }}>
          {lookupError ? <Alert severity="error">{lookupError}</Alert> : null}

          {needsDisambiguation ? (
            <Alert severity="warning">
              {needsSetSelection
                ? 'Karte erkannt. Bitte jetzt zuerst das richtige Set waehlen.'
                : 'Das Set ist erkannt. Bitte jetzt noch die richtige Variante waehlen, bevor Sprache und Bestand gespeichert werden.'}
            </Alert>
          ) : null}

          {lookupData ? (
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Chip color="primary" variant="outlined" label={`Karte: ${lookupData.name}`} />
              {selectedSetGroup ? <Chip variant="outlined" label={`Set: ${selectedSetGroup.label}`} /> : null}
              {resolvedPrint ? <Chip color="success" variant="outlined" label={`Variante: ${buildVariantLabel(resolvedPrint)}`} /> : null}
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

            <Grid item xs={12}>
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
                  if ((reason === 'input' || reason === 'clear') && selectedSuggestion && value.trim() !== selectedSuggestion.name.trim()) {
                    setSelectedSuggestion(null);
                    clearLookupResult(value);
                    return;
                  }
                  updateForm({ name: value });
                }}
                onChange={(_, option) => {
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
                        ? 'Karte erkannt. Jetzt Set und bei Bedarf die genaue Variante waehlen.'
                        : `Suche immer gleichzeitig in ${searchLanguageLabel || 'DE, EN'}. Danach waehlen wir Set und Variante.`
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

            {lookupData ? (
              <>
                <Grid item xs={12}>
                  <Autocomplete<SetGroupOption, false, false, false>
                    options={setGroupOptions}
                    value={selectedSetGroup}
                    onChange={(_, option) => handleSetGroupChange(option?.key || '')}
                    isOptionEqualToValue={(option, value) => option.key === value.key}
                    getOptionLabel={(option) => option.label}
                    filterOptions={(options, state) => {
                      const normalizedInput = normalizeAutocompleteText(state.inputValue);
                      if (!normalizedInput) {
                        return options;
                      }
                      return options.filter((option) => normalizeAutocompleteText(option.label).includes(normalizedInput));
                    }}
                    autoHighlight
                    clearOnBlur={false}
                    noOptionsText="Kein passendes Set gefunden"
                    ListboxProps={{ style: { maxHeight: 360 } }}
                    renderOption={(props, option) => (
                      <Box component="li" {...props}>
                        <Stack direction="row" justifyContent="space-between" width="100%" spacing={2}>
                          <Typography>{option.label}</Typography>
                          {option.options.length > 1 ? (
                            <Typography variant="body2" color="text.secondary">
                              {option.options.length} Varianten
                            </Typography>
                          ) : null}
                        </Stack>
                      </Box>
                    )}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Set"
                        fullWidth
                        color={needsSetSelection ? 'warning' : 'primary'}
                        helperText={
                          needsSetSelection
                            ? 'Bitte das richtige Set auswaehlen. Du kannst auch direkt im Feld tippen.'
                            : selectedSetGroup && variantOptions.length > 1
                              ? `${variantOptions.length} Varianten in diesem Set verfuegbar.`
                              : 'Set wurde erkannt.'
                        }
                      />
                    )}
                  />
                </Grid>

                {selectedSetGroup && variantOptions.length > 1 ? (
                  <Grid item xs={12}>
                    <TextField
                      select
                      label="Variante"
                      fullWidth
                      color={needsVariantSelection ? 'warning' : 'primary'}
                      value={selectedVariantKey}
                      onChange={(event) => handleVariantChange(event.target.value)}
                      helperText="Bitte die genaue Variante innerhalb des Sets waehlen."
                    >
                      <MenuItem value="">Bitte Variante auswaehlen</MenuItem>
                      {variantOptions.map((option) => (
                        <MenuItem key={buildVariantKey(option)} value={buildVariantKey(option)}>
                          {buildVariantLabel(option)}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Grid>
                ) : null}
              </>
            ) : (
              <>
                <Grid item xs={12} md={6}>
                  <TextField label="Setname" fullWidth value={form.set_name || ''} onChange={(event) => updateForm({ set_name: event.target.value })} />
                </Grid>

                <Grid item xs={12} md={3}>
                  <TextField
                    label="Setcode"
                    fullWidth
                    error={Boolean(setCodeLanguageError)}
                    helperText={setCodeLanguageError || undefined}
                    value={form.set_code || ''}
                    onChange={(event) => updateForm({ set_code: event.target.value })}
                  />
                </Grid>

                <Grid item xs={12} md={3}>
                  <TextField label="Seltenheit" fullWidth value={form.rarity || ''} onChange={(event) => updateForm({ rarity: event.target.value })} />
                </Grid>
              </>
            )}

            {showInventoryFields ? (
              <>
                <Grid item xs={12} md={4}>
                  <TextField
                    select
                    label="Sprache"
                    fullWidth
                    value={form.language}
                    onChange={(event) => {
                      const nextLanguage = event.target.value;
                      if (lookupData) {
                        applyLookupPayload(lookupData, {}, nextLanguage);
                      } else {
                        updateForm({
                          language: nextLanguage,
                          set_code: buildSetCodeForLanguage(form.set_code, nextLanguage) || form.set_code,
                          cardmarket_expected_language: nextLanguage,
                        });
                      }
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

                <Grid item xs={12} md={4}>
                  <TextField select label="Zustand" fullWidth value={form.condition} onChange={(event) => updateForm({ condition: event.target.value })}>
                    <MenuItem value="near_mint">Near Mint</MenuItem>
                    <MenuItem value="excellent">Excellent</MenuItem>
                    <MenuItem value="good">Good</MenuItem>
                    <MenuItem value="played">Played</MenuItem>
                    <MenuItem value="poor">Poor</MenuItem>
                  </TextField>
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
                  <TextField
                    label={lookupData ? 'Gespeicherter Setcode' : 'Setcode'}
                    fullWidth
                    error={Boolean(setCodeLanguageError)}
                    helperText={
                      setCodeLanguageError ||
                      (lookupData ? 'Wird passend zur gewaehlten Sprache automatisch umgeschrieben, z. B. DE-001 statt EN-001.' : undefined)
                    }
                    value={form.set_code || ''}
                    onChange={(event) => updateForm({ set_code: event.target.value })}
                    InputProps={lookupData ? { readOnly: true } : undefined}
                  />
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
                    value={form.current_market_price ?? ''}
                    onChange={(event) => updateForm({ current_market_price: event.target.value ? Number(event.target.value) : undefined })}
                    helperText={marketPriceHelperText || undefined}
                  />
                </Grid>

                <Grid item xs={12} md={4}>
                  <TextField label="Waehrung" fullWidth value={form.current_price_currency} onChange={(event) => updateForm({ current_price_currency: event.target.value })} />
                </Grid>

                <Grid item xs={12}>
                  <TextField label="Tags (kommagetrennt)" fullWidth value={tagText} onChange={(event) => setTagText(event.target.value)} />
                </Grid>

                <Grid item xs={12}>
                  <TextField label="Notizen" fullWidth multiline minRows={2} value={form.notes || ''} onChange={(event) => updateForm({ notes: event.target.value })} />
                </Grid>
              </>
            ) : null}
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
