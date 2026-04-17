import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from 'react';

import api, { getApiErrorMessage } from '../lib/api';
import { AppSettings } from '../lib/types';

const defaultSettings: AppSettings = {
  preferred_currency: 'EUR',
  preferred_card_language: 'de',
  preferred_search_language: 'de,en',
  preferred_price_language: 'de',
};

type SettingsContextValue = {
  settings: AppSettings;
  loading: boolean;
  error: string | null;
  refreshSettings: () => Promise<void>;
};

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function AppSettingsProvider({ children }: PropsWithChildren) {
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshSettings = async () => {
    setLoading(true);
    try {
      const response = await api.get<AppSettings>('/settings/');
      setSettings({
        preferred_currency: response.data.preferred_currency || defaultSettings.preferred_currency,
        preferred_card_language: response.data.preferred_card_language || defaultSettings.preferred_card_language,
        preferred_search_language: response.data.preferred_search_language || defaultSettings.preferred_search_language,
        preferred_price_language: response.data.preferred_price_language || defaultSettings.preferred_price_language,
        created_at: response.data.created_at,
        updated_at: response.data.updated_at,
      });
      setError(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
      setSettings(defaultSettings);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refreshSettings();
  }, []);

  const value = useMemo(
    () => ({
      settings,
      loading,
      error,
      refreshSettings,
    }),
    [error, loading, settings],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useAppSettings() {
  const context = useContext(SettingsContext);
  if (!context) {
    return {
      settings: defaultSettings,
      loading: true,
      error: null,
      refreshSettings: async () => undefined,
    } satisfies SettingsContextValue;
  }
  return context;
}
