import { describe, expect, it } from 'vitest';

import { allocatePurchaseTotal, findQuickEntryMatches, parseQuickEntry } from './set-import';
import { SetCardRow } from './types';

function row(id: number, name: string, cardNumber: string, rarity = 'Common'): SetCardRow {
  return {
    card_print_id: id,
    card_id: id,
    name,
    language: 'de',
    card_number: cardNumber,
    set_code: `RA05-${cardNumber}`,
    rarity,
    card_kind: 'monster',
    image_url: '',
    existing_quantity: 0,
  };
}

describe('allocatePurchaseTotal', () => {
  it('teilt gleichmäßig und centgenau auf', () => {
    const lines = allocatePurchaseTotal(100, [
      { card_print_id: 1, quantity: 1 },
      { card_print_id: 2, quantity: 1 },
      { card_print_id: 3, quantity: 1 },
    ], 'even');
    const totals = Object.values(lines).map((line) => line.lineTotal);
    expect(totals.reduce((sum, value) => sum + value, 0)).toBeCloseTo(100, 10);
    expect(totals.sort()).toEqual([33.33, 33.33, 33.34]);
  });

  it('verteilt nach Marktwert', () => {
    const lines = allocatePurchaseTotal(90, [
      { card_print_id: 1, quantity: 1, market_price: 40 },
      { card_print_id: 2, quantity: 2, market_price: 5 },
    ], 'market_value');
    expect(lines[1].lineTotal).toBe(72);
    expect(lines[2].lineTotal).toBe(18);
    expect(lines[2].unitPrice).toBe(9);
  });

  it('ohne Kaufpreis wird nichts verteilt', () => {
    expect(allocatePurchaseTotal(null, [{ card_print_id: 1, quantity: 2 }], 'even')).toEqual({});
  });
});

describe('Schnellerfassung', () => {
  const rows = [row(1, 'Dunkler Magier', 'DE001'), row(2, 'Blauäugiger weißer Drache', 'DE045'), row(3, 'Blauäugiger weißer Drache', 'DE045', 'Secret Rare')];

  it('erkennt Mengenangaben', () => {
    expect(parseQuickEntry('45 x3')).toEqual({ term: '45', quantity: 3 });
    expect(parseQuickEntry('DE001')).toEqual({ term: 'DE001', quantity: 1 });
  });

  it('findet Karten über die Nummer', () => {
    expect(findQuickEntryMatches(rows, '1').map((item) => item.card_print_id)).toEqual([1]);
    expect(findQuickEntryMatches(rows, 'de001').map((item) => item.card_print_id)).toEqual([1]);
    expect(findQuickEntryMatches(rows, 'RA05-DE045').map((item) => item.card_print_id)).toEqual([2, 3]);
  });

  it('findet Karten über den Namen', () => {
    expect(findQuickEntryMatches(rows, 'magier').map((item) => item.card_print_id)).toEqual([1]);
  });
});
