import { PricingStatus } from './types';

function normalizedMatchQuality(pricing: PricingStatus): string {
  return pricing.match_quality || pricing.status;
}

function normalizedMonitorState(pricing: PricingStatus): string {
  return pricing.price_stability_state || pricing.status;
}

export function pricingLabel(pricing: PricingStatus): string {
  return priceMatchLabel(normalizedMatchQuality(pricing));
}

export function priceMatchLabel(matchQuality?: string | null): string {
  switch (matchQuality) {
    case 'manual':
      return 'Manuell';
    case 'manual_verified':
      return 'Manuell bestätigter Print';
    case 'exact_verified':
    case 'exact_verified_variant':
    case 'exact':
      return 'Exakter Print-Match';
    case 'set_name_verified_name_only':
    case 'high_confidence':
      return 'Teilweise verifiziert';
    case 'ambiguous':
    case 'failed':
    case 'fallback':
    case 'fallback_name_only':
      return 'Fallback';
    case 'new':
      return 'Neu';
    case 'stable':
      return 'Stabil';
    case 'low_value_stable':
      return 'Stabil, Low-Value';
    case 'watch':
      return 'Beobachten';
    case 'volatile':
      return 'Volatil';
    case 'high_volatility':
      return 'Hohe Volatilität';
    case 'retry':
      return 'Wiederholung geplant';
    case 'updating':
      return 'Preis wird aktualisiert';
    default:
      return 'Preis offen';
  }
}

export function pricingColor(pricing: PricingStatus): 'default' | 'success' | 'warning' | 'info' {
  switch (normalizedMatchQuality(pricing)) {
    case 'manual':
      return 'info';
    case 'manual_verified':
      return 'success';
    case 'exact_verified':
    case 'exact_verified_variant':
    case 'exact':
      return 'success';
    case 'set_name_verified_name_only':
    case 'high_confidence':
      return 'info';
    case 'ambiguous':
    case 'failed':
    case 'fallback':
    case 'fallback_name_only':
      return 'warning';
    case 'new':
    case 'watch':
      return 'info';
    case 'stable':
    case 'low_value_stable':
      return 'success';
    case 'volatile':
    case 'high_volatility':
    case 'retry':
      return 'warning';
    case 'updating':
      return 'info';
    default:
      return 'default';
  }
}

export function monitorStateLabel(pricing: PricingStatus): string {
  switch (normalizedMonitorState(pricing)) {
    case 'new':
      return 'Neu';
    case 'stable':
      return 'Stabil';
    case 'low_value_stable':
      return 'Stabil, Low-Value';
    case 'watch':
      return 'Beobachten';
    case 'volatile':
      return 'Volatil';
    case 'high_volatility':
      return 'Hohe Volatilität';
    case 'retry':
      return 'Wiederholung geplant';
    case 'updating':
      return 'Preis wird aktualisiert';
    default:
      return 'Unbekannt';
  }
}

export function monitorStateColor(pricing: PricingStatus): 'default' | 'success' | 'warning' | 'info' {
  switch (normalizedMonitorState(pricing)) {
    case 'new':
    case 'watch':
      return 'info';
    case 'stable':
    case 'low_value_stable':
      return 'success';
    case 'volatile':
    case 'high_volatility':
    case 'retry':
      return 'warning';
    case 'updating':
      return 'info';
    default:
      return 'default';
  }
}

export function cardmarketLinkLabel(quality?: string | null): string {
  if (!quality) {
    return 'Kein Link';
  }
  switch (quality) {
    case 'manual_verified':
      return 'Manuell bestätigt';
    case 'exact_verified':
      return 'Link verifiziert';
    case 'exact_verified_variant':
      return 'Verifizierte Variante';
    case 'set_name_verified_name_only':
      return 'Name-only-Link';
    case 'ambiguous':
      return 'Automatisch erstellt, nicht verifiziert';
    case 'failed':
      return 'Link fehlgeschlagen';
    default:
      return 'Fallback-Link';
  }
}

export function cardmarketLinkColor(quality?: string | null): 'default' | 'success' | 'warning' | 'info' {
  switch (quality) {
    case 'manual_verified':
    case 'exact_verified':
    case 'exact_verified_variant':
      return 'success';
    case 'set_name_verified_name_only':
      return 'info';
    case 'ambiguous':
    case 'failed':
      return 'warning';
    default:
      return 'default';
  }
}

export function pricingUpdateLabel(pricing: PricingStatus): string | null {
  if (!pricing.is_updating) {
    return null;
  }
  return 'Preis wird aktualisiert';
}

export function priceSourceLabel(source?: string | null): string {
  switch (source) {
    case 'ygoprodeck':
      return 'YGOPRODeck';
    case 'ygoprodeck:tcgplayer_set_price':
      return 'TCGPlayer-Printpreis via YGOPRODeck';
    case 'ygoprodeck:cardmarket_card_price':
      return 'Cardmarket-Kartenpreis via YGOPRODeck';
    case 'ygoprodeck:cardmarket':
      return 'Cardmarket-Kartenpreis via YGOPRODeck';
    case 'ygoprodeck:tcgplayer':
      return 'TCGPlayer-Kartenpreis via YGOPRODeck';
    case 'ygoprodeck:set_price':
      return 'YGOPRODeck-Printpreis';
    case 'cardmarket:median_top5':
      return 'Cardmarket Median Top 5';
    case 'cardmarket':
      return 'Cardmarket';
    case 'manual':
      return 'Manuell';
    default:
      return source || 'n/a';
  }
}
