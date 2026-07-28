import { CardLookupPrintOption, CardPayload } from '../../lib/types';

export type LookupSelection = {
  set_name?: string | null;
  set_code?: string | null;
  rarity?: string | null;
  variant_key?: string | null;
};

export type SetGroupOption = {
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

export function validateSetCodeLanguage(language: string, setCode?: string | null): string | null {
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

export function buildSetCodeForLanguage(setCode: string | null | undefined, language: string): string | null {
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

export function normalizeSetGroupKey(option: Pick<CardLookupPrintOption, 'set_name' | 'set_code'>): string {
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

export function trimValue(value?: string | null): string | undefined {
  const nextValue = value?.trim();
  return nextValue ? nextValue : undefined;
}

export function buildSetGroupOptions(printOptions: CardLookupPrintOption[]): SetGroupOption[] {
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

type PrintIdentitySource = Pick<
  CardLookupPrintOption,
  | 'set_name'
  | 'set_code'
  | 'rarity'
  | 'card_number'
  | 'cardmarket_variant_name'
  | 'cardmarket_product_slug'
  | 'cardmarket_product_url'
  | 'cardmarket_reference'
>;

function buildPrintIdentityKey(option: PrintIdentitySource): string {
  return [
    normalizeSetGroupKey(option),
    trimValue(option.rarity),
    trimValue(option.card_number),
    trimValue(option.cardmarket_variant_name),
    trimValue(option.cardmarket_product_slug),
    trimValue(option.cardmarket_product_url || option.cardmarket_reference),
  ].join('||');
}

export function buildVariantKey(option: CardLookupPrintOption): string {
  return buildPrintIdentityKey(option);
}

export function buildVariantLabel(option: CardLookupPrintOption): string {
  return (
    [
      trimValue(option.cardmarket_variant_name),
      trimValue(option.rarity),
      trimValue(option.card_number),
      trimValue(option.set_code),
    ]
      .filter(Boolean)
      .join(' | ') || option.display_label
  );
}

export function buildLookupSelectionFromPrint(option: CardLookupPrintOption): LookupSelection {
  return {
    set_name: option.set_name ?? undefined,
    set_code: option.set_code ?? undefined,
    rarity: option.rarity ?? undefined,
    variant_key: buildVariantKey(option),
  };
}

export function buildStoredVariantKey(form: CardPayload): string | undefined {
  const hasVariantIdentity = trimValue(
    form.cardmarket_product_url ||
      form.cardmarket_reference ||
      form.cardmarket_product_slug ||
      form.cardmarket_variant_name,
  );
  if (!hasVariantIdentity) {
    return undefined;
  }
  return buildPrintIdentityKey({
    set_name: form.set_name,
    set_code: form.set_code,
    rarity: form.rarity,
    card_number: form.card_number,
    cardmarket_variant_name: form.cardmarket_variant_name,
    cardmarket_product_slug: form.cardmarket_product_slug,
    cardmarket_product_url: form.cardmarket_product_url,
    cardmarket_reference: form.cardmarket_reference,
  });
}

export function normalizeAutocompleteText(value?: string | null): string {
  return (value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export function parseLanguageList(value: string | undefined, fallback: string[] = ['de', 'en']): string[] {
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

export function buildSearchLanguageQuery(
  preferredSearchLanguage: string | undefined,
  currentLanguage: string,
): string {
  const preferred = parseLanguageList(preferredSearchLanguage, []);
  return Array.from(new Set([currentLanguage, 'de', 'en', ...preferred].filter(Boolean))).join(',');
}

function matchesPrintOptionLanguage(option: CardLookupPrintOption, language: string): boolean {
  const expectedPrefixes = languageSetCodePrefixes[(language || '').trim().toLowerCase()];
  if (!expectedPrefixes?.length) {
    return true;
  }
  const detectedPrefix = extractSetCodeLanguagePrefix(option.set_code);
  return !detectedPrefix || expectedPrefixes.includes(detectedPrefix);
}

function translatePrintOptionLanguage(
  option: CardLookupPrintOption,
  language: string,
): CardLookupPrintOption {
  const translatedSetCode = buildSetCodeForLanguage(option.set_code, language) || option.set_code;
  return {
    ...option,
    set_code: translatedSetCode,
    card_number: option.card_number || trimValue(translatedSetCode?.split('-').pop()),
  };
}

export function getLanguageAwarePrintOptions(
  printOptions: CardLookupPrintOption[],
  language: string,
): CardLookupPrintOption[] {
  if (!printOptions.length) {
    return [];
  }

  const groupedOptions = new Map<string, CardLookupPrintOption[]>();
  for (const option of printOptions) {
    const key = buildPrintIdentityKey(option);
    const existing = groupedOptions.get(key);
    if (existing) {
      existing.push(option);
    } else {
      groupedOptions.set(key, [option]);
    }
  }

  const sourceOptions = Array.from(groupedOptions.values()).map((options) => {
    const matchingOption = options.find((option) => matchesPrintOptionLanguage(option, language));
    return matchingOption ?? translatePrintOptionLanguage(options[0], language);
  });
  const seen = new Set<string>();
  return sourceOptions.filter((option) => {
    const key = buildVariantKey(option);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

export const defaultPayload: CardPayload = {
  name: '',
  language: 'de',
  condition: 'near_mint',
  quantity: 1,
  current_price_currency: 'EUR',
  tags: [],
  external_ids: {},
  link_arrows: [],
};

export function buildDefaultPayload(preferredCardLanguage: string, preferredCurrency: string): CardPayload {
  return {
    ...defaultPayload,
    language: preferredCardLanguage || defaultPayload.language,
    current_price_currency: preferredCurrency || defaultPayload.current_price_currency,
  };
}

export function isCardmarketUrl(value: string): boolean {
  return /^https?:\/\/www\.cardmarket\.com\/[a-z]{2}\/YuGiOh\//i.test(value.trim());
}

export function priceMatchQualityForSource(
  source?: string | null,
  cardmarketMatchQuality?: string | null,
): string | undefined {
  if (!source) {
    return undefined;
  }
  if (source === 'manual') {
    return 'manual';
  }
  if (source === 'ygoprodeck:tcgplayer_set_price') {
    return 'exact_verified';
  }
  if (source === 'cardmarket:public-product-page') {
    return cardmarketMatchQuality || 'exact_verified';
  }
  return 'fallback_name_only';
}

function uniqueValues(values: Array<string | null | undefined>): string[] {
  return Array.from(
    new Set(values.map((value) => trimValue(value)).filter((value): value is string => Boolean(value))),
  );
}

function filterPrintOptions(
  printOptions: CardLookupPrintOption[],
  selection: LookupSelection,
  ignoreField?: keyof LookupSelection,
): CardLookupPrintOption[] {
  return printOptions.filter((option) => {
    if (ignoreField !== 'variant_key' && selection.variant_key && buildVariantKey(option) !== selection.variant_key) {
      return false;
    }
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

export function resolveSelectedPrint(
  printOptions: CardLookupPrintOption[],
  selection: LookupSelection,
): CardLookupPrintOption | null {
  if (selection.variant_key) {
    const exactVariant = printOptions.find((option) => buildVariantKey(option) === selection.variant_key);
    if (exactVariant) {
      return exactVariant;
    }
  }
  const matches = filterPrintOptions(printOptions, selection);
  return matches.length === 1 ? matches[0] : null;
}

export function sanitizeSelection(
  printOptions: CardLookupPrintOption[],
  selection: LookupSelection,
): LookupSelection {
  const nextSelection: LookupSelection = {
    set_name: trimValue(selection.set_name),
    set_code: trimValue(selection.set_code),
    rarity: trimValue(selection.rarity),
    variant_key: trimValue(selection.variant_key),
  };

  if (!printOptions.length) {
    return nextSelection;
  }

  if (nextSelection.variant_key) {
    const exactVariant = printOptions.find((option) => buildVariantKey(option) === nextSelection.variant_key);
    if (exactVariant) {
      return buildLookupSelectionFromPrint(exactVariant);
    }
  }

  const availableSetNames = uniqueValues(
    filterPrintOptions(printOptions, nextSelection, 'set_name').map((option) => option.set_name),
  );
  if (nextSelection.set_name && !availableSetNames.includes(nextSelection.set_name)) {
    nextSelection.set_name = undefined;
  }

  const availableSetCodes = uniqueValues(
    filterPrintOptions(printOptions, nextSelection, 'set_code').map((option) => option.set_code),
  );
  if (nextSelection.set_code && !availableSetCodes.includes(nextSelection.set_code)) {
    nextSelection.set_code = undefined;
  }

  const availableRarities = uniqueValues(
    filterPrintOptions(printOptions, nextSelection, 'rarity').map((option) => option.rarity),
  );
  if (nextSelection.rarity && !availableRarities.includes(nextSelection.rarity)) {
    nextSelection.rarity = undefined;
  }

  const availableVariantKeys = filterPrintOptions(printOptions, nextSelection, 'variant_key').map(
    (option) => buildVariantKey(option),
  );
  if (nextSelection.variant_key && !availableVariantKeys.includes(nextSelection.variant_key)) {
    nextSelection.variant_key = undefined;
  }

  const resolvedPrint = resolveSelectedPrint(printOptions, nextSelection);
  return resolvedPrint ? buildLookupSelectionFromPrint(resolvedPrint) : nextSelection;
}
