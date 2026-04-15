import { useEffect, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import { Alert, Box, Button, Chip, CircularProgress, IconButton, Paper, Stack, Typography } from '@mui/material';

import CollectionFormDialog from '../components/collection-form-dialog';
import api, { getApiErrorMessage } from '../lib/api';
import { formatCurrency } from '../lib/format';
import { CollectionDetail, CollectionPayload, CollectionSummary } from '../lib/types';

export default function CollectionsPage() {
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [editingCollection, setEditingCollection] = useState<CollectionDetail | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const collectionsResponse = await api.get<CollectionSummary[]>('/collections/');
      setCollections(collectionsResponse.data);
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

  const loadCollectionDetail = async (collectionId: number) => {
    try {
      const response = await api.get<CollectionDetail>(`/collections/${collectionId}`);
      setEditingCollection(response.data);
      setDialogOpen(true);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  const handleSave = async (payload: CollectionPayload) => {
    setSaving(true);
    try {
      if (editingCollection) {
        await api.put(`/collections/${editingCollection.id}`, payload);
      } else {
        await api.post('/collections/', payload);
      }
      setDialogOpen(false);
      setEditingCollection(null);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (collectionId: number) => {
    if (!window.confirm('Diese Sammlung wirklich loeschen?')) {
      return;
    }
    try {
      await api.delete(`/collections/${collectionId}`);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 3, display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Box>
          <Typography variant="h4">Sammlungen</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>
            Freie Ordner und Kategorien fuer Staples, Verkauf, Favorites oder Projekte.
          </Typography>
        </Box>
        <Button
          startIcon={<AddRoundedIcon />}
          variant="contained"
          onClick={() => {
            setEditingCollection(null);
            setDialogOpen(true);
          }}
        >
          Sammlung anlegen
        </Button>
      </Paper>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {loading ? (
        <CircularProgress />
      ) : (
        <Stack spacing={2.5}>
          {collections.map((collection) => (
            <Paper key={collection.id} sx={{ p: 2.5 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <Box>
                  <Typography variant="h6">{collection.name}</Typography>
                  <Typography color="text.secondary" sx={{ mt: 0.75 }}>
                    {collection.description || 'Keine Beschreibung'}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1}>
                  {collection.color ? <Chip label={collection.color} variant="outlined" /> : null}
                  <Chip label={`${collection.card_count} Karten`} variant="outlined" />
                  <Chip label={formatCurrency(collection.total_value, collection.display_currency)} color="primary" variant="outlined" />
                  <IconButton onClick={() => void loadCollectionDetail(collection.id)}>
                    <EditRoundedIcon />
                  </IconButton>
                  <IconButton color="error" onClick={() => void handleDelete(collection.id)}>
                    <DeleteOutlineRoundedIcon />
                  </IconButton>
                </Stack>
              </Box>
            </Paper>
          ))}
        </Stack>
      )}

      <CollectionFormDialog
        open={dialogOpen}
        title={editingCollection ? `Sammlung bearbeiten: ${editingCollection.name}` : 'Neue Sammlung'}
        initialValue={editingCollection}
        loading={saving}
        onClose={() => {
          setDialogOpen(false);
          setEditingCollection(null);
        }}
        onSubmit={handleSave}
      />
    </Stack>
  );
}
