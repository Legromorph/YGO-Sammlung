import { PricingStatus } from './types';

function normalizedMatchQuality(pricing: PricingStatus): string {
  return pricing.match_quality || pricing.status;
}

function normalizedMonitorState(pricing: PricingStatus): string {
  return pricing.price_stability_state || pricing.status;
}

export function pricingLabel(pricing: PricingStatus): string {
  switch (normalizedMatchQuality(pricing)) {
    case 'manual':
      return 'Manuell';
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
      return 'Hohe Volatilitaet';
    case 'retry':
      return 'Retry';
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
      return 'Hohe Volatilitaet';
    case 'retry':
      return 'Retry';
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
  switch (quality) {
    case 'exact_verified':
      return 'Link verifiziert';
    case 'exact_verified_variant':
      return 'Verifizierte Variante';
    case 'set_name_verified_name_only':
      return 'Name-only-Link';
    case 'ambiguous':
      return 'Link unsicher';
    case 'failed':
      return 'Link fehlgeschlagen';
    default:
      return 'Fallback-Link';
  }
}

export function cardmarketLinkColor(quality?: string | null): 'default' | 'success' | 'warning' | 'info' {
  switch (quality) {
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
