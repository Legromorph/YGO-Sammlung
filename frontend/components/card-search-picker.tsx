import { useEffect, useMemo, useState } from 'react';
import ClearRoundedIcon from '@mui/icons-material/ClearRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import {
  Alert,
  Box,
  CircularProgress,
  IconButton,
  List,
  ListItemButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';

import api, { getApiErrorMessage } from '../lib/api';
import { useDebouncedValue } from '../hooks/use-debounced-value';
import { useAppSettings } from './app-settings-provider';
import { CardSearchOption, cardSearchLabel } from '../lib/card-search';
import CardSearchResultItem from './card-search-result-item';

interface CardSearchPickerProps {
  label: string;
  selectedCard?: CardSearchOption | null;
  onSelect: (card: CardSearchOption | null) => void;
  helperText?: string;
  placeholder?: string;
  minLength?: number;
  disabled?: boolean;
  language?: string;
}

export default function CardSearchPicker({
  label,
  selectedCard,
  onSelect,
  helperText,
  placeholder,
  minLength = 2,
  disabled = false,
  language,
}: CardSearchPickerProps) {
  const { settings } = useAppSettings();
  const resolvedLanguage = language || settings.preferred_card_language || 'de';
  const [query, setQuery] = useState(selectedCard?.name || '');
  const [results, setResults] = useState<CardSearchOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query.trim(), 250);

  useEffect(() => {
    if (disabled) {
      return;
    }

    const searchText = debouncedQuery.trim();
    if (searchText.length < minLength) {
      setResults(selectedCard ? [selectedCard] : []);
      setLoading(false);
      setError(null);
      return;
    }

    let active = true;
    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.get<{ items: CardSearchOption[]; total: number }>('/cards/', {
          params: {
            q: searchText,
            language: resolvedLanguage,
            page: 1,
            page_size: 10,
            sort_by: 'name',
            sort_order: 'asc',
          },
        });

        if (!active) {
          return;
        }

        const nextResults = [...response.data.items];
        if (selectedCard && !nextResults.some((card) => card.id === selectedCard.id)) {
          nextResults.unshift(selectedCard);
        }
        setResults(nextResults);
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
          setResults(selectedCard ? [selectedCard] : []);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void run();
    return () => {
      active = false;
    };
  }, [debouncedQuery, disabled, minLength, resolvedLanguage, selectedCard]);

  const showResults = useMemo(() => {
    if (disabled) {
      return false;
    }
    return query.trim().length >= minLength || Boolean(selectedCard);
  }, [disabled, minLength, query, selectedCard]);

  return (
    <Stack spacing={1.25}>
      {selectedCard ? (
        <Paper
          variant="outlined"
          sx={{
            p: 1.25,
            borderColor: 'rgba(216,169,76,0.35)',
            background: 'rgba(216,169,76,0.06)',
          }}
        >
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="caption" color="text.secondary">
                Aktuell ausgewählt
              </Typography>
              <CardSearchResultItem card={selectedCard} compact />
            </Box>
            <IconButton
              size="small"
              aria-label="Auswahl entfernen"
              onClick={() => {
                setQuery('');
                onSelect(null);
              }}
            >
              <ClearRoundedIcon fontSize="small" />
            </IconButton>
          </Stack>
        </Paper>
      ) : null}

      <TextField
        label={label}
        fullWidth
        value={query}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => {
          const nextValue = event.target.value;
          setQuery(nextValue);
          if (selectedCard && nextValue.trim() !== selectedCard.name.trim()) {
            onSelect(null);
          }
          if (!nextValue.trim()) {
            onSelect(null);
          }
        }}
        helperText={helperText || `Tippe mindestens ${minLength} Zeichen, um Karten nach Name, Set, Setcode, Seltenheit oder Sprache zu durchsuchen.`}
        InputProps={{
          endAdornment: loading ? <CircularProgress color="inherit" size={18} /> : <SearchRoundedIcon sx={{ color: 'text.secondary' }} />,
        }}
      />

      {showResults ? (
        <Paper
          variant="outlined"
          sx={{
            maxHeight: 420,
            overflow: 'auto',
            borderColor: 'rgba(255,255,255,0.08)',
          }}
        >
          {error ? <Alert severity="warning" sx={{ m: 1.25 }}>{error}</Alert> : null}
          {!error && loading && results.length === 0 ? (
            <Box sx={{ p: 2.5, display: 'grid', placeItems: 'center' }}>
              <CircularProgress size={22} />
            </Box>
          ) : null}
          {!error && !loading && query.trim().length < minLength ? (
            <Box sx={{ p: 2.5 }}>
              <Typography color="text.secondary">Beginne zu tippen, um passende Karten zu finden.</Typography>
            </Box>
          ) : null}
          {!error && !loading && query.trim().length >= minLength && results.length === 0 ? (
            <Box sx={{ p: 2.5 }}>
              <Typography color="text.secondary">Keine Karten gefunden.</Typography>
            </Box>
          ) : null}
          {results.length > 0 ? (
            <List disablePadding>
              {results.map((card) => {
                const isSelected = selectedCard?.id === card.id;
                return (
                  <ListItemButton
                    key={card.id}
                    selected={isSelected}
                    onClick={() => {
                      onSelect(card);
                      setQuery(cardSearchLabel(card));
                    }}
                    sx={{
                      alignItems: 'flex-start',
                      py: 1.25,
                      px: 1.5,
                      borderTop: '1px solid rgba(255,255,255,0.06)',
                      '&.Mui-selected': {
                        backgroundColor: 'rgba(216,169,76,0.14)',
                      },
                    }}
                  >
                    <Box sx={{ width: '100%' }}>
                      <CardSearchResultItem card={card} compact />
                    </Box>
                  </ListItemButton>
                );
              })}
            </List>
          ) : null}
        </Paper>
      ) : null}
    </Stack>
  );
}
