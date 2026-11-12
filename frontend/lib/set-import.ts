import { AllocationMode, SetCardRow } from './types';

export type AllocationLine = {
  card_print_id: number;
  quantity: number;
  lineTotal: number;
  unitPrice: number;
};

/**
 * Mirrors the backend split (services/inventory.py): exact to the cent, either
 * evenly per card or proportional to the market value of each card. Cards
 * without a market price are weighted like the cheapest priced card.
 */
export function allocatePurchaseTotal(
  total: number | null,
  rows: Array<{ card_print_id: number; quantity: number; market_price?: number | null }>,
  mode: AllocationMode,
): Record<number, AllocationLine> {
  const lines = rows.filter((row) => row.quantity > 0);
  if (total === null || total <= 0 || !lines.length) {
    return {};
  }

  const knownPrices = lines.map((row) => row.market_price).filter((price): price is number => typeof price === 'number' && price > 0);
  const floorPrice = knownPrices.length ? Math.min(...knownPrices) : null;
  const unitWeight = (row: (typeof lines)[number]) => {
    if (mode !== 'market_value' || floorPrice === null) {
      return 1;
    }
    return row.market_price && row.market_price > 0 ? row.market_price : floorPrice;
  };

  const totalCents = Math.round(total * 100);
  const weights = lines.map((row) => unitWeight(row) * row.quantity);
  const weightSum = weights.reduce((sum, weight) => sum + weight, 0);
  const shares = weights.map((weight) => (totalCents * weight) / weightSum);
  const cents = shares.map((share) => Math.floor(share));
  let remainder = totalCents - cents.reduce((sum, value) => sum + value, 0);
  const byFraction = shares
    .map((share, index) => ({ index, fraction: share - cents[index] }))
    .sort((left, right) => right.fraction - left.fraction || left.index - right.index);
  for (const { index } of byFraction) {
    if (remainder <= 0) {
      break;
    }
    cents[index] += 1;
    remainder -= 1;
  }

  return Object.fromEntries(
    lines.map((row, index) => {
      const lineTotal = cents[index] / 100;
      return [row.card_print_id, { card_print_id: row.card_print_id, quantity: row.quantity, lineTotal, unitPrice: lineTotal / row.quantity }];
    }),
  );
}

function numberPart(value: string | null | undefined): string {
  const match = (value || '').match(/(\d+)\s*$/);
  return match ? String(Number(match[1])) : '';
}

/**
 * Parses quick-entry input such as "45", "DE045", "RA05-DE045", "Dark Magician" or "45 x3".
 */
export function parseQuickEntry(input: string): { term: string; quantity: number } {
  const match = input.trim().match(/^(.*?)(?:\s*[x*×]\s*(\d+))?$/i);
  const term = (match?.[1] || '').trim();
  const quantity = match?.[2] ? Math.max(1, Number(match[2])) : 1;
  return { term, quantity };
}

export function findQuickEntryMatches(rows: SetCardRow[], term: string): SetCardRow[] {
  const normalized = term.trim().toLowerCase();
  if (!normalized) {
    return [];
  }

  if (/\d/.test(normalized) && /^[a-z0-9-]+$/.test(normalized)) {
    const fullCodeMatches = rows.filter(
      (row) => (row.set_code || '').toLowerCase() === normalized || (row.card_number || '').toLowerCase() === normalized,
    );
    if (fullCodeMatches.length) {
      return fullCodeMatches;
    }
    const wantedNumber = numberPart(normalized);
    const numberMatches = rows.filter((row) => numberPart(row.card_number || row.set_code) === wantedNumber);
    if (numberMatches.length) {
      return numberMatches;
    }
  }

  const exactName = rows.filter((row) => row.name.toLowerCase() === normalized);
  if (exactName.length) {
    return exactName;
  }
  return rows.filter((row) => row.name.toLowerCase().includes(normalized));
}
