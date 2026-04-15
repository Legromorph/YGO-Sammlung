import axios from 'axios';

function resolveApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  const browserDefault =
    typeof window !== 'undefined'
      ? `${window.location.protocol}//${window.location.hostname}:8000`
      : 'http://localhost:8000';

  if (!configured) {
    return browserDefault.replace(/\/$/, '');
  }

  try {
    const parsed = new URL(configured);
    if (typeof window !== 'undefined') {
      const browserHost = window.location.hostname;
      if (['localhost', '127.0.0.1'].includes(parsed.hostname) && !['localhost', '127.0.0.1'].includes(browserHost)) {
        parsed.hostname = browserHost;
      }
    }
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return configured.replace(/\/$/, '');
  }
}

const apiBaseUrl = resolveApiBaseUrl();

const api = axios.create({
  baseURL: `${apiBaseUrl}/api`,
});

export function resolveMediaUrl(path?: string | null): string {
  if (!path) {
    return '';
  }

  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }

  if (path.startsWith('/')) {
    return `${apiBaseUrl}${path}`;
  }

  return `${apiBaseUrl}/${path}`;
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return;
    }

    query.set(key, String(value));
  });

  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;

    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }

    if (detail && typeof detail === 'object') {
      const maybeMessage = (detail as { message?: unknown }).message;
      if (typeof maybeMessage === 'string' && maybeMessage.trim()) {
        return maybeMessage;
      }
    }

    if (error.code === 'ERR_NETWORK' || error.message === 'Network Error') {
      return `Backend nicht erreichbar unter ${apiBaseUrl}. Pruefe, ob die API auf Port 8000 laeuft.`;
    }

    if (error.response?.status) {
      return `API-Fehler (${error.response.status}).`;
    }
  }

  return 'Daten konnten nicht geladen werden.';
}

export default api;
