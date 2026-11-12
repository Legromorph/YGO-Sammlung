import Link from 'next/link';
import { useRouter } from 'next/router';
import { type ReactNode, useEffect, useState } from 'react';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import TaskAltRoundedIcon from '@mui/icons-material/TaskAltRounded';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Grid,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import CardFormDialog from '../../components/card-form-dialog';
import CardMetadataList from '../../components/card-metadata-list';
import api, { getApiErrorMessage, resolveMediaUrl } from '../../lib/api';
import { formatCurrency, formatDate, formatPercent } from '../../lib/format';
import {
  cardmarketLinkColor,
  cardmarketLinkLabel,
  cardmarketSearchUrl,
  isCardmarketProductUrl,
  monitorStateColor,
  monitorStateLabel,
  priceMatchLabel,
  pricingColor,
  pricingLabel,
  priceSourceLabel,
} from '../../lib/pricing';
import { CardDetail, CardFilterOptions, CardPayload, PriceRefreshResponse, StorageLocation, SyncJob } from '../../lib/types';

type MessageSeverity = 'info' | 'success' | 'warning' | 'error';

function isActiveSyncJob(job: SyncJob | null | undefined): job is SyncJob {
  return Boolean(job && (job.status === 'pending' || job.status === 'running'));
}

function dedupeSourceMappings(mappings: CardDetail['source_mappings']): CardDetail['source_mappings'] {
  const seen = new Set<string>();
  return mappings.filter((mapping) => {
    const key = `${mapping.provider_key}\u0000${mapping.external_id}\u0000${mapping.external_url || ''}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function storedCardmarketLink(card: CardDetail): string {
  return card.cardmarket_product_url || card.cardmarket_reference || card.pricing.cardmarket_url || '';
}

function StatusRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2 }}>
      <Typography color="text.secondary">{label}</Typography>
      <Box sx={{ minWidth: 0, fontWeight: 700, textAlign: 'right', overflowWrap: 'anywhere' }}>{children}</Box>
    </Box>
  );
}

function ValueTile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Paper sx={{ p: 2, height: '100%' }}>
      <Typography color="text.secondary" variant="body2">
        {label}
      </Typography>
      <Box sx={{ mt: 0.75 }}>{children}</Box>
    </Paper>
  );
}

export default function CardDetailPage() {
  const router = useRouter();
  const [card, setCard] = useState<CardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshingPrice, setIsRefreshingPrice] = useState(false);
  const [isSavingLink, setIsSavingLink] = useState(false);
  const [message, setMessage] = useState<{ text: string; severity: MessageSeverity } | null>(null);
  const [priceJob, setPriceJob] = useState<SyncJob | null>(null);
  const [cardmarketLinkDraft, setCardmarketLinkDraft] = useState('');
  const [editOpen, setEditOpen] = useState(false);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [storageLocations, setStorageLocations] = useState<StorageLocation[]>([]);
  const [reloadToken, setReloadToken] = useState(0);

  const applyCard = (nextCard: CardDetail) => {
    setCard(nextCard);
    setCardmarketLinkDraft(storedCardmarketLink(nextCard));
  };

  useEffect(() => {
    if (!router.query.id) {
      return;
    }

    let active = true;
    const load = async () => {
      try {
        const response = await api.get<CardDetail>(`/cards/${router.query.id}`);
        if (active) {
          applyCard(response.data);
          setPriceJob(isActiveSyncJob(response.data.pricing.pending_job) ? response.data.pricing.pending_job : null);
          setError(null);
        }
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, [router.query.id, reloadToken]);

  useEffect(() => {
    let active = true;
    api
      .get<CardFilterOptions>('/cards/filters')
      .then((response) => {
        if (active) {
          setStorageLocations(response.data.storage_locations);
        }
      })
      .catch(() => {
        if (active) {
          setStorageLocations([]);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  // Only used when the instant refresh had to fall back to the background queue.
  const activeJobId = isActiveSyncJob(priceJob) ? priceJob.id : null;
  useEffect(() => {
    if (!activeJobId) {
      return;
    }

    let active = true;
    const poll = async () => {
      try {
        const response = await api.get<SyncJob>(`/sync/jobs/${activeJobId}`);
        if (!active) {
          return;
        }
        setPriceJob(response.data);
        if (response.data.status === 'completed') {
          const updated = (response.data.successful_items || 0) > 0;
          setMessage({
            text: updated ? 'Preis im Hintergrund aktualisiert.' : 'Kein neuer Preis gefunden.',
            severity: updated ? 'success' : 'warning',
          });
          setReloadToken((value) => value + 1);
        } else if (response.data.status === 'failed') {
          setMessage({ text: response.data.error_message || 'Preisupdate fehlgeschlagen.', severity: 'error' });
          setReloadToken((value) => value + 1);
        }
      } catch (requestError) {
        if (active) {
          setMessage({ text: getApiErrorMessage(requestError), severity: 'error' });
        }
      }
    };

    const interval = window.setInterval(() => void poll(), 2000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [activeJobId]);

  const refreshPrice = async () => {
    if (!card) {
      return;
    }
    setIsRefreshingPrice(true);
    setMessage(null);
    try {
      const response = await api.post<PriceRefreshResponse>(`/cards/${card.id}/price-update`);
      applyCard(response.data.card);
      setPriceJob(response.data.job || null);
      setMessage({
        text: response.data.message,
        severity: response.data.status === 'updated' ? 'success' : response.data.status === 'queued' ? 'info' : 'warning',
      });
    } catch (requestError) {
      setMessage({ text: getApiErrorMessage(requestError), severity: 'error' });
    } finally {
      setIsRefreshingPrice(false);
    }
  };

  const saveCardmarketLink = async () => {
    if (!card) {
      return;
    }
    setIsSavingLink(true);
    setMessage(null);
    try {
      const url = cardmarketLinkDraft.trim();
      const response = await api.put<CardDetail>(`/cards/${card.id}/cardmarket-link`, { url: url || null, confirmed: Boolean(url) });
      applyCard(response.data);
      setMessage({ text: url ? 'Cardmarket-Link gespeichert und bestätigt.' : 'Cardmarket-Link entfernt.', severity: 'success' });
    } catch (requestError) {
      setMessage({ text: getApiErrorMessage(requestError), severity: 'error' });
    } finally {
      setIsSavingLink(false);
    }
  };

  const saveCardEdit = async (payload: CardPayload) => {
    if (!card) {
      return;
    }
    setIsSavingEdit(true);
    setMessage(null);
    try {
      await api.put(`/cards/${card.id}`, payload);
      setEditOpen(false);
      setMessage({ text: 'Karte gespeichert.', severity: 'success' });
      setReloadToken((value) => value + 1);
    } catch (requestError) {
      setMessage({ text: getApiErrorMessage(requestError), severity: 'error' });
    } finally {
      setIsSavingEdit(false);
    }
  };

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  if (!card) {
    return <CircularProgress />;
  }

  const sourceMappings = dedupeSourceMappings(card.source_mappings);
  const latestSnapshot = card.price_history[0] ?? null;
  const storedLink = storedCardmarketLink(card);
  const linkQuality = storedLink ? card.pricing.cardmarket_link_mode || null : null;
  const draft = cardmarketLinkDraft.trim();
  const draftIsValid = isCardmarketProductUrl(draft);
  const draftChanged = draft !== storedLink;
  const linkConfirmed = linkQuality === 'manual_verified' && !draftChanged;
  const purchaseTotal = card.purchase_price != null ? card.purchase_price * card.quantity : null;
  const profit = purchaseTotal != null && card.current_market_price != null ? card.total_value - purchaseTotal : null;
  const priceBusy = isRefreshingPrice || isActiveSyncJob(priceJob);

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2} flexWrap="wrap" useFlexGap>
        <Button component={Link} href="/cards" startIcon={<ArrowBackRoundedIcon />}>
          Zurück zur Kartenliste
        </Button>
        <Button variant="outlined" startIcon={<EditRoundedIcon />} onClick={() => setEditOpen(true)}>
          Karte bearbeiten
        </Button>
      </Stack>

      {message ? (
        <Alert severity={message.severity} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      ) : null}

      <Paper sx={{ p: 3 }}>
        <Grid container spacing={3}>
          <Grid item xs={12} md={4}>
            <Avatar
              src={resolveMediaUrl(card.image_url)}
              variant="rounded"
              sx={{ width: '100%', height: { xs: 360, md: 420 }, bgcolor: 'rgba(255,255,255,0.05)' }}
            />
          </Grid>
          <Grid item xs={12} md={8}>
            <Typography variant="h3">{card.name}</Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap' }} useFlexGap>
              <Chip label={card.set_code || 'Kein Setcode'} color="primary" variant="outlined" />
              {card.rarity ? <Chip label={card.rarity} variant="outlined" /> : null}
              <Chip label={card.language.toUpperCase()} variant="outlined" />
              <Chip label={card.condition} color="secondary" variant="outlined" />
              {card.set_name ? <Chip label={card.set_name} variant="outlined" /> : null}
            </Stack>

            <Grid container spacing={2} sx={{ mt: 1 }}>
              <Grid item xs={12} sm={6} lg={3}>
                <ValueTile label="Marktpreis (Stück)">
                  <Typography variant="h5">{formatCurrency(card.current_market_price, card.current_price_currency)}</Typography>
                  <Chip size="small" sx={{ mt: 1 }} label={pricingLabel(card.pricing)} color={pricingColor(card.pricing)} variant="outlined" />
                </ValueTile>
              </Grid>
              <Grid item xs={12} sm={6} lg={3}>
                <ValueTile label={`Bestand (${card.quantity}×)`}>
                  <Typography variant="h5">{formatCurrency(card.total_value, card.current_price_currency)}</Typography>
                  {profit != null ? (
                    <Typography variant="body2" sx={{ mt: 1, color: profit >= 0 ? 'success.main' : 'error.main' }}>
                      {profit >= 0 ? '+' : ''}
                      {formatCurrency(profit, card.current_price_currency)} ggü. Einkauf
                    </Typography>
                  ) : null}
                </ValueTile>
              </Grid>
              <Grid item xs={12} sm={6} lg={3}>
                <ValueTile label="Veränderung 7 Tage">
                  <Typography variant="h5" sx={{ color: (card.price_change_7d || 0) >= 0 ? 'success.main' : 'error.main' }}>
                    {formatPercent(card.price_change_7d)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    30 Tage: {formatPercent(card.price_change_30d)}
                  </Typography>
                </ValueTile>
              </Grid>
              <Grid item xs={12} sm={6} lg={3}>
                <ValueTile label="Lagerort">
                  <Typography variant="h6">{card.storage_path || 'Nicht zugewiesen'}</Typography>
                </ValueTile>
              </Grid>
            </Grid>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }} sx={{ mt: 2.5 }}>
              <Button
                variant="contained"
                startIcon={priceBusy ? <CircularProgress size={18} color="inherit" /> : <RefreshRoundedIcon />}
                onClick={() => void refreshPrice()}
                disabled={priceBusy}
              >
                {isRefreshingPrice ? 'Preis wird abgefragt…' : 'Preis jetzt abfragen'}
              </Button>
              <Typography variant="body2" color="text.secondary">
                Stand: {formatDate(card.pricing.last_updated_at || latestSnapshot?.captured_at)} · Quelle:{' '}
                {priceSourceLabel(card.pricing.source || latestSnapshot?.provider_key)}
              </Typography>
            </Stack>
            {isActiveSyncJob(priceJob) ? <LinearProgress sx={{ mt: 1.5 }} /> : null}
            {card.pricing.note ? (
              <Alert severity={card.pricing.status === 'fallback' || card.pricing.status === 'unpriced' ? 'warning' : 'info'} sx={{ mt: 2 }}>
                {card.pricing.note}
              </Alert>
            ) : null}
          </Grid>
        </Grid>
      </Paper>

      <Grid container spacing={2.5} alignItems="flex-start">
        <Grid item xs={12} lg={7}>
          <Stack spacing={2.5}>
            <Paper sx={{ p: 2.5 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Preisverlauf
              </Typography>
              <Box sx={{ height: 300 }}>
                {card.price_history.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={[...card.price_history].reverse()}>
                      <XAxis dataKey="captured_at" tickFormatter={(value) => formatDate(value).slice(0, 10)} stroke="#8ea092" />
                      <YAxis stroke="#8ea092" width={80} tickFormatter={(value) => formatCurrency(Number(value), card.current_price_currency)} />
                      <Tooltip
                        formatter={(value) => formatCurrency(Number(value), card.current_price_currency)}
                        labelFormatter={(value) => formatDate(String(value))}
                      />
                      <Line type="monotone" dataKey="price" stroke="#d8a94c" strokeWidth={3} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <Box sx={{ height: '100%', display: 'grid', placeItems: 'center' }}>
                    <Typography color="text.secondary">Noch kein Preisverlauf vorhanden.</Typography>
                  </Box>
                )}
              </Box>
            </Paper>

            <Paper sx={{ p: 2.5 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Kartendetails
              </Typography>
              {card.effect_text ? (
                <Typography color="text.secondary" sx={{ mb: 2 }}>
                  {card.effect_text}
                </Typography>
              ) : null}
              <CardMetadataList card={card} />
            </Paper>
          </Stack>
        </Grid>

        <Grid item xs={12} lg={5}>
          <Stack spacing={2.5}>
            <Paper sx={{ p: 2.5 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                <Typography variant="h6">Cardmarket</Typography>
                <Chip label={cardmarketLinkLabel(linkQuality)} color={cardmarketLinkColor(linkQuality)} variant="outlined" size="small" />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Hinterlege den Produktlink deines genauen Prints. Er wird nur gespeichert, nicht automatisch abgerufen.
              </Typography>
              <TextField
                label="Cardmarket-Produktlink"
                type="url"
                size="small"
                fullWidth
                value={cardmarketLinkDraft}
                error={Boolean(draft) && !draftIsValid}
                helperText={draft && !draftIsValid ? 'Bitte einen Link auf eine Cardmarket-Produktseite einfügen.' : undefined}
                onChange={(event) => setCardmarketLinkDraft(event.target.value)}
              />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
                {linkConfirmed ? (
                  <Chip icon={<TaskAltRoundedIcon />} label="Bestätigt" color="success" variant="outlined" />
                ) : (
                  <Button
                    variant="contained"
                    color={draftChanged ? 'primary' : 'success'}
                    startIcon={
                      isSavingLink ? <CircularProgress size={18} color="inherit" /> : draftChanged ? <SaveRoundedIcon /> : <TaskAltRoundedIcon />
                    }
                    disabled={isSavingLink || (Boolean(draft) && !draftIsValid) || (!draft && !draftChanged)}
                    onClick={() => void saveCardmarketLink()}
                  >
                    {!draft && draftChanged ? 'Link entfernen' : draftChanged ? 'Speichern' : 'Als korrekt bestätigen'}
                  </Button>
                )}
                {draftIsValid ? (
                  <Button component="a" href={draft} target="_blank" rel="noopener noreferrer" variant="outlined" startIcon={<OpenInNewRoundedIcon />}>
                    Öffnen
                  </Button>
                ) : (
                  <Button
                    component="a"
                    href={cardmarketSearchUrl(card.name)}
                    target="_blank"
                    rel="noopener noreferrer"
                    variant="outlined"
                    startIcon={<SearchRoundedIcon />}
                  >
                    Auf Cardmarket suchen
                  </Button>
                )}
              </Stack>
              {card.cardmarket_verified_at ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  Bestätigt am {formatDate(card.cardmarket_verified_at)}
                </Typography>
              ) : null}
            </Paper>

            <Accordion disableGutters sx={{ bgcolor: 'background.paper', borderRadius: 2, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                <Typography variant="h6">Preisprüfung & Quellen</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={1.25}>
                  <StatusRow label="Prüfstatus">
                    <Chip label={monitorStateLabel(card.pricing)} color={monitorStateColor(card.pricing)} variant="outlined" size="small" />
                  </StatusRow>
                  <StatusRow label="Letzte Prüfung">{formatDate(card.pricing.last_price_check_at)}</StatusRow>
                  <StatusRow label="Nächste automatische Prüfung">{formatDate(card.pricing.next_price_check_at)}</StatusRow>
                  {card.pricing.price_check_interval_hours ? (
                    <StatusRow label="Prüfintervall">{card.pricing.price_check_interval_hours} h</StatusRow>
                  ) : null}
                  {(card.pricing.failure_count ?? 0) > 0 ? (
                    <StatusRow label="Fehlversuche">
                      <Typography component="span" color="error.main" fontWeight={700}>
                        {card.pricing.failure_count}
                      </Typography>
                    </StatusRow>
                  ) : null}
                </Stack>

                <Typography color="text.secondary" sx={{ mt: 2.5, mb: 0.5 }}>
                  Letzte Preisstände
                </Typography>
                <List disablePadding dense>
                  {card.price_history.slice(0, 6).map((entry) => (
                    <ListItem key={`${entry.provider_key}-${entry.captured_at}`} disableGutters>
                      <ListItemText
                        primary={`${formatCurrency(entry.price, entry.currency)} · ${priceSourceLabel(entry.provider_key)}`}
                        secondary={[formatDate(entry.captured_at), entry.match_quality ? priceMatchLabel(entry.match_quality) : null]
                          .filter(Boolean)
                          .join(' · ')}
                      />
                    </ListItem>
                  ))}
                  {card.price_history.length === 0 ? (
                    <ListItem disableGutters>
                      <ListItemText secondary="Noch kein gültiger Preisstand vorhanden." />
                    </ListItem>
                  ) : null}
                </List>

                <Typography color="text.secondary" sx={{ mt: 2, mb: 0.5 }}>
                  Externe Zuordnungen
                </Typography>
                <List disablePadding dense>
                  {sourceMappings.map((mapping) => (
                    <ListItem key={`${mapping.provider_key}-${mapping.external_id}-${mapping.external_url || ''}`} disableGutters>
                      <ListItemText
                        primary={`${priceSourceLabel(mapping.provider_key)} · ID ${mapping.external_id}`}
                        secondary={mapping.external_url || undefined}
                        secondaryTypographyProps={{ sx: { overflowWrap: 'anywhere' } }}
                      />
                    </ListItem>
                  ))}
                  {sourceMappings.length === 0 ? (
                    <ListItem disableGutters>
                      <ListItemText secondary="Keine externe Zuordnung vorhanden." />
                    </ListItem>
                  ) : null}
                </List>
              </AccordionDetails>
            </Accordion>
          </Stack>
        </Grid>
      </Grid>

      <CardFormDialog
        open={editOpen}
        title={`Karte bearbeiten: ${card.name}`}
        initialValue={card}
        storageLocations={storageLocations}
        loading={isSavingEdit}
        onClose={() => setEditOpen(false)}
        onSubmit={saveCardEdit}
      />
    </Stack>
  );
}
