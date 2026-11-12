import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Grid,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';

import { priceSourceLabel } from '../../lib/pricing';
import { CardPayload, StorageLocation } from '../../lib/types';

export const CONDITION_OPTIONS = [
  { value: 'near_mint', label: 'Near Mint' },
  { value: 'excellent', label: 'Excellent' },
  { value: 'good', label: 'Good' },
  { value: 'played', label: 'Played' },
  { value: 'poor', label: 'Poor' },
];

interface InventoryFieldsProps {
  visible: boolean;
  form: CardPayload;
  storageLocations: StorageLocation[];
  marketPriceHelperText: string;
  tagText: string;
  cardmarketUrl?: string;
  cardmarketUrlError?: boolean;
  onUpdate: (patch: Partial<CardPayload>) => void;
  onTagTextChange: (value: string) => void;
  onCardmarketUrlChange?: (value: string) => void;
}

export default function InventoryFields({
  visible,
  form,
  storageLocations,
  marketPriceHelperText,
  tagText,
  cardmarketUrl = '',
  cardmarketUrlError = false,
  onUpdate,
  onTagTextChange,
  onCardmarketUrlChange,
}: InventoryFieldsProps) {
  if (!visible) {
    return null;
  }

  const isManualPrice = form.current_price_source === 'manual';
  const hasPrice = form.current_market_price !== null && form.current_market_price !== undefined;

  return (
    <>
      <Grid item xs={12}>
        <Paper variant="outlined" sx={{ p: 2, bgcolor: 'rgba(216,169,76,0.05)', borderColor: 'rgba(216,169,76,0.25)' }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'flex-start' }}>
            <TextField
              label="Marktpreis"
              type="number"
              sx={{ minWidth: { sm: 200 } }}
              value={form.current_market_price ?? ''}
              inputProps={{ min: 0.01, step: '0.01' }}
              InputProps={{ endAdornment: <InputAdornment position="end">{form.current_price_currency}</InputAdornment> }}
              onChange={(event) =>
                onUpdate({
                  current_market_price: event.target.value ? Number(event.target.value) : undefined,
                  current_price_source: event.target.value ? 'manual' : undefined,
                  current_price_match_quality: event.target.value ? 'manual' : undefined,
                  current_price_note: event.target.value ? 'Manuell gepflegter Marktpreis.' : undefined,
                })
              }
            />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Typography fontWeight={700}>
                  {hasPrice ? (isManualPrice ? 'Eigener Preis' : 'Automatisch ermittelt') : 'Noch kein Preis'}
                </Typography>
                {hasPrice && !isManualPrice && form.current_price_source ? (
                  <Chip size="small" variant="outlined" color="secondary" label={priceSourceLabel(form.current_price_source)} />
                ) : null}
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {marketPriceHelperText ||
                  (hasPrice
                    ? 'Du kannst den Wert überschreiben. Nach dem Speichern wird der Preis automatisch aktuell gehalten.'
                    : 'Leer lassen: Der Preis wird nach dem Speichern automatisch abgefragt.')}
              </Typography>
            </Box>
          </Stack>
        </Paper>
      </Grid>

      <Grid item xs={6} md={3}>
        <TextField
          label="Menge"
          type="number"
          fullWidth
          value={form.quantity}
          inputProps={{ min: 1 }}
          onChange={(event) => onUpdate({ quantity: Number(event.target.value) })}
        />
      </Grid>

      <Grid item xs={6} md={3}>
        <TextField select label="Zustand" fullWidth value={form.condition} onChange={(event) => onUpdate({ condition: event.target.value })}>
          {CONDITION_OPTIONS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {option.label}
            </MenuItem>
          ))}
        </TextField>
      </Grid>

      <Grid item xs={12} md={3}>
        <TextField
          label="Lagerort"
          select
          fullWidth
          value={form.storage_location_id || ''}
          onChange={(event) =>
            onUpdate({
              storage_location_id: event.target.value ? Number(event.target.value) : undefined,
            })
          }
        >
          <MenuItem value="">Nicht zugewiesen</MenuItem>
          {storageLocations.map((location) => (
            <MenuItem key={location.id} value={location.id}>
              {location.path_cache}
            </MenuItem>
          ))}
        </TextField>
      </Grid>

      <Grid item xs={12} md={3}>
        <TextField
          label="Einkaufspreis (Stück)"
          type="number"
          fullWidth
          value={form.purchase_price ?? ''}
          inputProps={{ min: 0, step: '0.01' }}
          InputProps={{ endAdornment: <InputAdornment position="end">{form.current_price_currency}</InputAdornment> }}
          onChange={(event) =>
            onUpdate({
              purchase_price: event.target.value ? Number(event.target.value) : undefined,
            })
          }
        />
      </Grid>

      <Grid item xs={12}>
        <Accordion disableGutters variant="outlined" sx={{ bgcolor: 'transparent', borderRadius: 2, '&:before': { display: 'none' } }}>
          <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
            <Typography>Weitere Angaben (optional)</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={2}>
              {onCardmarketUrlChange ? (
                <TextField
                  label="Cardmarket-Produktlink"
                  fullWidth
                  value={cardmarketUrl}
                  error={cardmarketUrlError}
                  onChange={(event) => onCardmarketUrlChange(event.target.value)}
                  helperText={
                    cardmarketUrlError
                      ? 'Bitte einen Link auf eine Cardmarket-Produktseite einfügen.'
                      : 'Optional. Wird nur gespeichert, nicht abgerufen.'
                  }
                />
              ) : null}
              <TextField label="Tags (kommagetrennt)" fullWidth value={tagText} onChange={(event) => onTagTextChange(event.target.value)} />
              <TextField
                label="Notizen"
                fullWidth
                multiline
                minRows={2}
                value={form.notes || ''}
                onChange={(event) => onUpdate({ notes: event.target.value })}
              />
            </Stack>
          </AccordionDetails>
        </Accordion>
      </Grid>
    </>
  );
}
