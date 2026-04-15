import dayjs from 'dayjs';

export function formatCurrency(value?: number | null, currency = 'EUR'): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return 'n/a';
  }

  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return '0.0%';
  }

  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

export function formatDate(value?: string | null): string {
  if (!value) {
    return 'n/a';
  }

  return dayjs(value).format('DD.MM.YYYY HH:mm');
}
