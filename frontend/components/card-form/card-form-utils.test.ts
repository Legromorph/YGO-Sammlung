import { describe, expect, it } from 'vitest';

import {
  buildSearchLanguageQuery,
  buildSetCodeForLanguage,
  buildVariantKey,
  getLanguageAwarePrintOptions,
  normalizeOptionalPositiveNumber,
  sanitizeSelection,
  validateSetCodeLanguage,
} from './card-form-utils';
import { isCardmarketProductUrl } from '../../lib/pricing';

const printOption = {
  set_name: 'Rarity Collection 5',
  set_code: 'RA05-EN080',
  card_number: 'EN080',
  rarity: 'Platinum Secret Rare',
  cardmarket_variant_name: 'V4',
  cardmarket_product_url:
    'https://www.cardmarket.com/en/YuGiOh/Products/Singles/Rarity-Collection-5/Dominus-Impulse-V4-Platinum-Secret-Rare',
  display_label: 'Dominus Impulse V4',
};

describe('card form helpers', () => {
  it('übersetzt den Sprachanteil eines Setcodes', () => {
    expect(buildSetCodeForLanguage('RA05-EN080', 'de')).toBe('RA05-DE080');
    expect(validateSetCodeLanguage('de', 'RA05-EN080')).toContain('Erwartet');
  });

  it('übersetzt bei fehlendem Sprachdruck auch die Kartennummer', () => {
    const [translated] = getLanguageAwarePrintOptions([printOption], 'de');
    expect(translated.set_code).toBe('RA05-DE080');
    expect(translated.card_number).toBe('DE080');
  });

  it('löst eine eindeutige Druckvariante auf', () => {
    const selection = sanitizeSelection([printOption], {
      set_name: printOption.set_name,
      rarity: printOption.rarity,
    });

    expect(selection.variant_key).toBe(buildVariantKey(printOption));
  });

  it('validiert Cardmarket-Produktlinks ohne täuschende Hosts', () => {
    expect(isCardmarketProductUrl(printOption.cardmarket_product_url)).toBe(true);
    expect(
      isCardmarketProductUrl('https://www.cardmarket.com.evil.example/en/YuGiOh/Products/Singles/A/B'),
    ).toBe(false);
  });

  it('führt Suchsprachen ohne Dopplungen zusammen', () => {
    expect(buildSearchLanguageQuery('de,en,fr', 'de')).toBe('de,en,fr');
  });

  it('normalisiert leere oder nullige Marktpreise für die API', () => {
    expect(normalizeOptionalPositiveNumber(undefined)).toBeUndefined();
    expect(normalizeOptionalPositiveNumber(null)).toBeUndefined();
    expect(normalizeOptionalPositiveNumber(0)).toBeUndefined();
    expect(normalizeOptionalPositiveNumber('')).toBeUndefined();
    expect(normalizeOptionalPositiveNumber('1.25')).toBe(1.25);
  });
});
