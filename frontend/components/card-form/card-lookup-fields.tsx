import {
  Autocomplete,
  Avatar,
  Box,
  Chip,
  CircularProgress,
  Grid,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

import { resolveMediaUrl } from '../../lib/api';
import { priceSourceLabel } from '../../lib/pricing';
import {
  CardLookupPrintOption,
  CardLookupResponse,
  CardLookupSuggestion,
} from '../../lib/types';
import {
  SetGroupOption,
  buildVariantKey,
  buildVariantLabel,
  normalizeAutocompleteText,
} from './card-form-utils';

interface CardLookupFieldsProps {
  lookupData: CardLookupResponse | null;
  suggestions: CardLookupSuggestion[];
  selectedSuggestion: CardLookupSuggestion | null;
  cardName: string;
  searchLoading: boolean;
  lookupLoading: boolean;
  searchLanguageLabel: string;
  setGroupOptions: SetGroupOption[];
  selectedSetGroup: SetGroupOption | null;
  resolvedPrint: CardLookupPrintOption | null;
  variantOptions: CardLookupPrintOption[];
  selectedVariantKey: string;
  needsSetSelection: boolean;
  needsVariantSelection: boolean;
  showManualPrintFields: boolean;
  setName?: string | null;
  setCode?: string | null;
  rarity?: string | null;
  setCodeLanguageError: string | null;
  onNameInputChange: (value: string, reason: string) => void;
  onSuggestionChange: (option: CardLookupSuggestion | string | null) => void;
  onSetGroupChange: (groupKey: string) => void;
  onVariantChange: (variantKey: string) => void;
  onManualPrintChange: (patch: {
    set_name?: string;
    set_code?: string;
    rarity?: string;
  }) => void;
}

export default function CardLookupFields({
  lookupData,
  suggestions,
  selectedSuggestion,
  cardName,
  searchLoading,
  lookupLoading,
  searchLanguageLabel,
  setGroupOptions,
  selectedSetGroup,
  resolvedPrint,
  variantOptions,
  selectedVariantKey,
  needsSetSelection,
  needsVariantSelection,
  showManualPrintFields,
  setName,
  setCode,
  rarity,
  setCodeLanguageError,
  onNameInputChange,
  onSuggestionChange,
  onSetGroupChange,
  onVariantChange,
  onManualPrintChange,
}: CardLookupFieldsProps) {
  return (
    <>
      {lookupData ? (
        <Grid item xs={12}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip color="primary" variant="outlined" label={`Karte: ${lookupData.name}`} />
            {selectedSetGroup ? <Chip variant="outlined" label={`Set: ${selectedSetGroup.label}`} /> : null}
            {resolvedPrint ? (
              <Chip color="success" variant="outlined" label={`Variante: ${buildVariantLabel(resolvedPrint)}`} />
            ) : null}
            {lookupData.image_url ? (
              <Chip
                variant="outlined"
                label="Kartendaten geladen"
                avatar={<Avatar alt={lookupData.name} src={resolveMediaUrl(lookupData.image_url)} />}
              />
            ) : null}
          </Stack>
        </Grid>
      ) : null}

      <Grid item xs={12}>
        <Autocomplete<CardLookupSuggestion, false, false, true>
          freeSolo
          options={suggestions}
          loading={searchLoading}
          filterOptions={(options) => options}
          value={selectedSuggestion}
          inputValue={cardName}
          noOptionsText="Keine passenden Karten gefunden"
          loadingText="Suche Karten..."
          isOptionEqualToValue={(option, value) =>
            typeof value !== 'string' && option.external_id === value.external_id
          }
          getOptionLabel={(option) => (typeof option === 'string' ? option : option.name)}
          onInputChange={(_, value, reason) => onNameInputChange(value, reason)}
          onChange={(_, option) => onSuggestionChange(option)}
          renderOption={(props, option) => (
            <Box component="li" {...props} sx={{ alignItems: 'flex-start', gap: 1.5 }}>
              <Avatar
                src={resolveMediaUrl(option.image_url)}
                variant="rounded"
                sx={{ width: 42, height: 58 }}
              />
              <Box>
                <Typography fontWeight={700}>{option.name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {[option.card_type, option.attribute, option.monster_type].filter(Boolean).join(' | ') ||
                    'Keine Typdaten'}
                </Typography>
                <Stack direction="row" spacing={0.75} sx={{ mt: 0.85 }} flexWrap="wrap" useFlexGap>
                  <Chip label={`${option.set_count} Drucke`} size="small" variant="outlined" />
                  {option.default_market_price ? (
                    <Tooltip title={priceSourceLabel(option.price_source)}>
                      <Chip
                        label={`${option.default_market_price.toFixed(2)} ${
                          option.default_price_currency || ''
                        }`.trim()}
                        size="small"
                        color="secondary"
                        variant="outlined"
                      />
                    </Tooltip>
                  ) : null}
                </Stack>
              </Box>
            </Box>
          )}
          renderInput={(params) => (
            <TextField
              {...params}
              label="Kartenname"
              helperText={
                lookupData
                  ? 'Karte erkannt. Jetzt Set und bei Bedarf die genaue Variante wählen.'
                  : `Suche gleichzeitig in ${
                      searchLanguageLabel || 'DE, EN'
                    }. Weitere Felder erscheinen nach der Kartenauswahl.`
              }
              InputProps={{
                ...params.InputProps,
                endAdornment: (
                  <>
                    {searchLoading || lookupLoading ? (
                      <CircularProgress color="inherit" size={18} sx={{ mr: 1 }} />
                    ) : null}
                    {params.InputProps.endAdornment}
                  </>
                ),
              }}
            />
          )}
        />
      </Grid>

      {lookupData ? (
        <>
          <Grid item xs={12}>
            <Autocomplete<SetGroupOption, false, false, false>
              options={setGroupOptions}
              value={selectedSetGroup}
              onChange={(_, option) => onSetGroupChange(option?.key || '')}
              isOptionEqualToValue={(option, value) => option.key === value.key}
              getOptionLabel={(option) => option.label}
              filterOptions={(options, state) => {
                const normalizedInput = normalizeAutocompleteText(state.inputValue);
                if (!normalizedInput) {
                  return options;
                }
                return options.filter((option) =>
                  normalizeAutocompleteText(option.label).includes(normalizedInput),
                );
              }}
              autoHighlight
              clearOnBlur={false}
              noOptionsText="Kein passendes Set gefunden"
              ListboxProps={{ style: { maxHeight: 360 } }}
              renderOption={(props, option) => (
                <Box component="li" {...props}>
                  <Stack direction="row" justifyContent="space-between" width="100%" spacing={2}>
                    <Typography>{option.label}</Typography>
                    {option.options.length > 1 ? (
                      <Typography variant="body2" color="text.secondary">
                        {option.options.length} Varianten
                      </Typography>
                    ) : null}
                  </Stack>
                </Box>
              )}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Set"
                  fullWidth
                  color={needsSetSelection ? 'warning' : 'primary'}
                  helperText={
                    needsSetSelection
                      ? 'Bitte das richtige Set auswählen.'
                      : selectedSetGroup && variantOptions.length > 1
                        ? `${variantOptions.length} Varianten in diesem Set verfügbar.`
                        : 'Set wurde erkannt.'
                  }
                />
              )}
            />
          </Grid>

          {selectedSetGroup && variantOptions.length > 1 ? (
            <Grid item xs={12}>
              <TextField
                select
                label="Rarität / Variante"
                fullWidth
                color={needsVariantSelection ? 'warning' : 'primary'}
                value={selectedVariantKey}
                onChange={(event) => onVariantChange(event.target.value)}
                helperText="Bitte die genaue Rarität bzw. Variante wählen."
              >
                <MenuItem value="">Bitte Rarität / Variante auswählen</MenuItem>
                {variantOptions.map((option) => (
                  <MenuItem key={buildVariantKey(option)} value={buildVariantKey(option)}>
                    {buildVariantLabel(option)}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
          ) : null}
        </>
      ) : showManualPrintFields ? (
        <>
          <Grid item xs={12} md={6}>
            <TextField
              label="Setname"
              fullWidth
              value={setName || ''}
              onChange={(event) => onManualPrintChange({ set_name: event.target.value })}
            />
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField
              label="Setcode"
              fullWidth
              error={Boolean(setCodeLanguageError)}
              helperText={setCodeLanguageError || undefined}
              value={setCode || ''}
              onChange={(event) => onManualPrintChange({ set_code: event.target.value })}
            />
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField
              label="Seltenheit"
              fullWidth
              value={rarity || ''}
              onChange={(event) => onManualPrintChange({ rarity: event.target.value })}
            />
          </Grid>
        </>
      ) : null}
    </>
  );
}
