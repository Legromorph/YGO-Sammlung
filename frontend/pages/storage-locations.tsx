import { useEffect, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import { Alert, Box, Button, CircularProgress, Grid, IconButton, Paper, Stack, Typography } from '@mui/material';

import StorageLocationDialog from '../components/storage-location-dialog';
import api, { getApiErrorMessage } from '../lib/api';
import { formatCurrency } from '../lib/format';
import { StorageLocation } from '../lib/types';

export default function StorageLocationsPage() {
  const [locations, setLocations] = useState<StorageLocation[]>([]);
  const [editingLocation, setEditingLocation] = useState<StorageLocation | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const response = await api.get<StorageLocation[]>('/storage-locations/');
      setLocations(response.data);
      setError(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleSave = async (payload: {
    name: string;
    code?: string;
    location_type: string;
    description?: string;
    position_label?: string;
    parent_id?: number | null;
  }) => {
    setSaving(true);
    try {
      if (editingLocation) {
        await api.put(`/storage-locations/${editingLocation.id}`, payload);
      } else {
        await api.post('/storage-locations/', payload);
      }
      setDialogOpen(false);
      setEditingLocation(null);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (locationId: number) => {
    if (!window.confirm('Diesen Lagerort wirklich loeschen?')) {
      return;
    }
    try {
      await api.delete(`/storage-locations/${locationId}`);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 3, display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Box>
          <Typography variant="h4">Physische Lagerorte</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>
            Hierarchische Lagerorte wie Binder, Seiten, Boxen und Regalflaechen.
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddRoundedIcon />}
          onClick={() => {
            setEditingLocation(null);
            setDialogOpen(true);
          }}
        >
          Lagerort anlegen
        </Button>
      </Paper>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {loading ? (
        <CircularProgress />
      ) : (
        <Grid container spacing={2.5}>
          {locations.map((location) => (
            <Grid key={location.id} item xs={12} md={6} xl={4}>
              <Paper sx={{ p: 2.5, height: '100%' }}>
                <Typography variant="overline" color="primary.light">
                  {location.location_type}
                </Typography>
                <Typography variant="h6">{location.name}</Typography>
                <Typography color="text.secondary" sx={{ mt: 0.75 }}>
                  {location.path_cache}
                </Typography>
                <Typography color="text.secondary" sx={{ mt: 1.5, minHeight: 48 }}>
                  {location.description || 'Keine Beschreibung hinterlegt.'}
                </Typography>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2.5 }}>
                  <Box>
                    <Typography color="text.secondary">Karten</Typography>
                    <Typography variant="h5">{location.card_count}</Typography>
                  </Box>
                  <Box sx={{ textAlign: 'right' }}>
                    <Typography color="text.secondary">Wert</Typography>
                    <Typography variant="h5">{formatCurrency(location.total_value, location.display_currency)}</Typography>
                  </Box>
                </Box>
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
                  <IconButton
                    onClick={() => {
                      setEditingLocation(location);
                      setDialogOpen(true);
                    }}
                  >
                    <EditRoundedIcon />
                  </IconButton>
                  <IconButton color="error" onClick={() => void handleDelete(location.id)}>
                    <DeleteOutlineRoundedIcon />
                  </IconButton>
                </Box>
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}

      <StorageLocationDialog
        open={dialogOpen}
        title={editingLocation ? `Lagerort bearbeiten: ${editingLocation.name}` : 'Neuer Lagerort'}
        initialValue={editingLocation}
        locations={locations}
        loading={saving}
        onClose={() => {
          setDialogOpen(false);
          setEditingLocation(null);
        }}
        onSubmit={handleSave}
      />
    </Stack>
  );
}
