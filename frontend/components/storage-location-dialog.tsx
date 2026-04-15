import { useEffect, useState } from 'react';
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Grid, MenuItem, TextField } from '@mui/material';

import { StorageLocation } from '../lib/types';

interface StorageLocationDialogProps {
  open: boolean;
  title: string;
  initialValue?: StorageLocation | null;
  locations: StorageLocation[];
  loading?: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    name: string;
    code?: string;
    location_type: string;
    description?: string;
    position_label?: string;
    parent_id?: number | null;
  }) => Promise<void>;
}

export default function StorageLocationDialog({
  open,
  title,
  initialValue,
  locations,
  loading = false,
  onClose,
  onSubmit,
}: StorageLocationDialogProps) {
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [locationType, setLocationType] = useState('other');
  const [description, setDescription] = useState('');
  const [positionLabel, setPositionLabel] = useState('');
  const [parentId, setParentId] = useState<number | ''>('');

  useEffect(() => {
    if (!open) {
      return;
    }

    setName(initialValue?.name || '');
    setCode(initialValue?.code || '');
    setLocationType(initialValue?.location_type || 'other');
    setDescription(initialValue?.description || '');
    setPositionLabel(initialValue?.position_label || '');
    setParentId(initialValue?.parent_id || '');
  }, [initialValue, open]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers>
        <Grid container spacing={2} sx={{ mt: 0.25 }}>
          <Grid item xs={12}>
            <TextField label="Name" fullWidth value={name} onChange={(event) => setName(event.target.value)} />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField label="Code" fullWidth value={code} onChange={(event) => setCode(event.target.value)} />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField select label="Typ" fullWidth value={locationType} onChange={(event) => setLocationType(event.target.value)}>
              <MenuItem value="binder">Binder</MenuItem>
              <MenuItem value="page">Seite</MenuItem>
              <MenuItem value="box">Box</MenuItem>
              <MenuItem value="deckbox">Deckbox</MenuItem>
              <MenuItem value="trade_binder">Trade Binder</MenuItem>
              <MenuItem value="shelf">Regal</MenuItem>
              <MenuItem value="other">Sonstiges</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12}>
            <TextField select label="Eltern-Lagerort" fullWidth value={parentId} onChange={(event) => setParentId(event.target.value ? Number(event.target.value) : '')}>
              <MenuItem value="">Keiner</MenuItem>
              {locations
                .filter((location) => location.id !== initialValue?.id)
                .map((location) => (
                  <MenuItem key={location.id} value={location.id}>
                    {location.path_cache}
                  </MenuItem>
                ))}
            </TextField>
          </Grid>
          <Grid item xs={12}>
            <TextField label="Unterposition / Slot" fullWidth value={positionLabel} onChange={(event) => setPositionLabel(event.target.value)} />
          </Grid>
          <Grid item xs={12}>
            <TextField label="Beschreibung" fullWidth multiline minRows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={onClose} disabled={loading}>
          Abbrechen
        </Button>
        <Button
          variant="contained"
          disabled={loading || !name.trim()}
          onClick={() =>
            void onSubmit({
              name,
              code: code || undefined,
              location_type: locationType,
              description: description || undefined,
              position_label: positionLabel || undefined,
              parent_id: parentId === '' ? undefined : parentId,
            })
          }
        >
          Speichern
        </Button>
      </DialogActions>
    </Dialog>
  );
}
