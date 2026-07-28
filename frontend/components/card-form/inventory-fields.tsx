import { Grid, MenuItem, TextField } from '@mui/material';

import { CardPayload, StorageLocation } from '../../lib/types';

interface InventoryFieldsProps {
  visible: boolean;
  form: CardPayload;
  hasLookup: boolean;
  storageLocations: StorageLocation[];
  setCodeLanguageError: string | null;
  marketPriceHelperText: string;
  tagText: string;
  onLanguageChange: (language: string) => void;
  onUpdate: (patch: Partial<CardPayload>) => void;
  onTagTextChange: (value: string) => void;
}

export default function InventoryFields({
  visible,
  form,
  hasLookup,
  storageLocations,
  setCodeLanguageError,
  marketPriceHelperText,
  tagText,
  onLanguageChange,
  onUpdate,
  onTagTextChange,
}: InventoryFieldsProps) {
  if (!visible) {
    return null;
  }

  return (
    <>
      <Grid item xs={12} md={4}>
        <TextField
          select
          label="Sprache"
          fullWidth
          value={form.language}
          onChange={(event) => onLanguageChange(event.target.value)}
        >
          <MenuItem value="de">Deutsch</MenuItem>
          <MenuItem value="en">Englisch</MenuItem>
          <MenuItem value="jp">Japanisch</MenuItem>
        </TextField>
      </Grid>

      <Grid item xs={12} md={4}>
        <TextField
          select
          label="Zustand"
          fullWidth
          value={form.condition}
          onChange={(event) => onUpdate({ condition: event.target.value })}
        >
          <MenuItem value="near_mint">Near Mint</MenuItem>
          <MenuItem value="excellent">Excellent</MenuItem>
          <MenuItem value="good">Good</MenuItem>
          <MenuItem value="played">Played</MenuItem>
          <MenuItem value="poor">Poor</MenuItem>
        </TextField>
      </Grid>

      <Grid item xs={12} md={4}>
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

      <Grid item xs={12} md={4}>
        <TextField
          label={hasLookup ? 'Gespeicherter Setcode' : 'Setcode'}
          fullWidth
          error={Boolean(setCodeLanguageError)}
          helperText={
            setCodeLanguageError ||
            (hasLookup ? 'Wird passend zur gewählten Sprache automatisch umgeschrieben.' : undefined)
          }
          value={form.set_code || ''}
          onChange={(event) => onUpdate({ set_code: event.target.value })}
          InputProps={hasLookup ? { readOnly: true } : undefined}
        />
      </Grid>

      <Grid item xs={12} md={4}>
        <TextField
          label="Menge"
          type="number"
          fullWidth
          value={form.quantity}
          inputProps={{ min: 1 }}
          onChange={(event) => onUpdate({ quantity: Number(event.target.value) })}
        />
      </Grid>

      <Grid item xs={12} md={4}>
        <TextField
          label="Einkaufspreis"
          type="number"
          fullWidth
          value={form.purchase_price ?? ''}
          inputProps={{ min: 0, step: '0.01' }}
          onChange={(event) =>
            onUpdate({
              purchase_price: event.target.value ? Number(event.target.value) : undefined,
            })
          }
        />
      </Grid>

      <Grid item xs={12} md={4}>
        <TextField
          label="Marktpreis"
          type="number"
          fullWidth
          value={form.current_market_price ?? ''}
          inputProps={{ min: 0.01, step: '0.01' }}
          onChange={(event) =>
            onUpdate({
              current_market_price: event.target.value ? Number(event.target.value) : undefined,
              current_price_source: event.target.value ? 'manual' : undefined,
              current_price_match_quality: event.target.value ? 'manual' : undefined,
              current_price_note: event.target.value ? 'Manuell gepflegter Marktpreis.' : undefined,
            })
          }
          helperText={marketPriceHelperText || undefined}
        />
      </Grid>

      <Grid item xs={12} md={4}>
        <TextField
          label="Währung"
          fullWidth
          value={form.current_price_currency}
          onChange={(event) =>
            onUpdate({
              current_price_currency: event.target.value,
              current_price_source: 'manual',
              current_price_match_quality: 'manual',
              current_price_note: 'Manuell gepflegter Marktpreis.',
            })
          }
        />
      </Grid>

      <Grid item xs={12}>
        <TextField
          label="Tags (kommagetrennt)"
          fullWidth
          value={tagText}
          onChange={(event) => onTagTextChange(event.target.value)}
        />
      </Grid>

      <Grid item xs={12}>
        <TextField
          label="Notizen"
          fullWidth
          multiline
          minRows={2}
          value={form.notes || ''}
          onChange={(event) => onUpdate({ notes: event.target.value })}
        />
      </Grid>
    </>
  );
}
