import Link from 'next/link';
import { useRouter } from 'next/router';
import { type ReactNode, useEffect, useState } from 'react';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import TaskAltRoundedIcon from '@mui/icons-material/TaskAltRounded';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
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
import { cardmarketLinkColor, cardmarketLinkLabel, monitorStateColor, monitorStateLabel, priceMatchLabel, pricingColor, pricingLabel, pricingUpdateLabel, priceSourceLabel } from '../../lib/pricing';
import { CardDetail, CardFilterOptions, CardPayload, StorageLocation, SyncJob } from '../../lib/types';

function isCardmarketProductUrl(value: string): boolean {
  return /^https?:\/\/(?:www\.)?cardmarket\.com\/[a-z]{2}\/YuGiOh\/Products\/Singles\/[^/?#]+\/[^/?#]+/i.test(value.trim());
}

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

function StatusRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 2 }}>
      <Typography color="text.secondary">{label}</Typography>
      <Box sx={{ minWidth: 0, fontWeight: 700, textAlign: 'right', overflowWrap: 'anywhere' }}>{children}</Box>
    </Box>
  );
}

export default function CardDetailPage() {
  const router = useRouter();
  const [card, setCard] = useState<CardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRequestingPriceUpdate, setIsRequestingPriceUpdate] = useState(false);
  const [cardmarketLinkAction, setCardmarketLinkAction] = useState<'save' | 'confirm' | null>(null);
  const [priceUpdateMessage, setPriceUpdateMessage] = useState<string | null>(null);
  const [priceUpdateSeverity, setPriceUpdateSeverity] = useState<'info' | 'success' | 'warning' | 'error'>('info');
  const [priceJob, setPriceJob] = useState<SyncJob | null>(null);
  const [cardmarketLinkDraft, setCardmarketLinkDraft] = useState('');
  const [editOpen, setEditOpen] = useState(false);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [storageLocations, setStorageLocations] = useState<StorageLocation[]>([]);
  const [reloadToken, setReloadToken] = useState(0);
  const activePriceJob = isActiveSyncJob(priceJob)
    ? priceJob
    : isActiveSyncJob(card?.pricing.pending_job)
      ? card.pricing.pending_job
      : null;
  const priceJobId = priceJob?.id;
  const priceJobStatus = priceJob?.status;
  const latestSnapshot = card?.price_history?.[0] ?? null;
  const cardmarketLink = card?.cardmarket_product_url || card?.cardmarket_reference || card?.pricing.cardmarket_url || null;
  const cardmarketLinkQuality = card?.pricing.cardmarket_link_mode || null;
  const trimmedCardmarketLinkDraft = cardmarketLinkDraft.trim();
  const cardmarketLinkDraftIsValid = isCardmarketProductUrl(trimmedCardmarketLinkDraft);
  const cardmarketLinkDraftMatchesStored = trimmedCardmarketLinkDraft === (cardmarketLink || '');
  const cardmarketLinkIsManuallyConfirmed = cardmarketLinkQuality === 'manual_verified' && cardmarketLinkDraftMatchesStored;
  const medianTop5Price = latestSnapshot?.market_price_median_top5 ?? latestSnapshot?.selected_market_price ?? null;
  const offersConsideredCount = latestSnapshot?.offers_considered_count ?? latestSnapshot?.offer_count_considered ?? null;
  const top5OfferPrices = latestSnapshot?.top5_offer_prices?.length ? latestSnapshot.top5_offer_prices : latestSnapshot?.raw_offer_prices_sample ?? [];
  const hasCardmarketOfferData = Boolean(
    latestSnapshot
    && [
      latestSnapshot.lowest_offer_price,
      medianTop5Price,
      latestSnapshot.avg_1d,
      latestSnapshot.avg_7d,
      latestSnapshot.avg_30d,
      latestSnapshot.price_trend,
      offersConsideredCount,
      ...top5OfferPrices,
    ].some((value) => value !== null && value !== undefined),
  );

  useEffect(() => {
    if (!router.query.id) {
      return;
    }

    let active = true;
    const load = async () => {
      try {
        const response = await api.get<CardDetail>(`/cards/${router.query.id}`);
        if (active) {
          setCard(response.data);
          setCardmarketLinkDraft(response.data.cardmarket_product_url || response.data.cardmarket_reference || response.data.pricing.cardmarket_url || '');
          setPriceJob(response.data.pricing.pending_job || null);
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
    const loadStorageLocations = async () => {
      try {
        const response = await api.get<CardFilterOptions>('/cards/filters');
        if (active) {
          setStorageLocations(response.data.storage_locations);
        }
      } catch {
        if (active) {
          setStorageLocations([]);
        }
      }
    };

    void loadStorageLocations();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!priceJobId || (priceJobStatus !== 'pending' && priceJobStatus !== 'running')) {
      return;
    }

    let active = true;
    const poll = async () => {
      try {
        const response = await api.get<SyncJob>(`/sync/jobs/${priceJobId}`);
        if (!active) {
          return;
        }
        setPriceJob(response.data);
        if (response.data.status === 'completed') {
          const updated = response.data.successful_items || 0;
          const failed = response.data.failed_items || 0;
          setPriceUpdateMessage(
            updated > 0
              ? `Preisupdate abgeschlossen: ${updated} aktualisiert${failed > 0 ? `, ${failed} ohne neuen Preis` : ''}.`
              : 'Preisupdate ohne neuen Preis abgeschlossen.',
          );
          setPriceUpdateSeverity(updated > 0 && failed === 0 ? 'success' : 'warning');
          setReloadToken((value) => value + 1);
        } else if (response.data.status === 'failed') {
          setPriceUpdateMessage(response.data.error_message || 'Preisupdate fehlgeschlagen.');
          setPriceUpdateSeverity('error');
          setReloadToken((value) => value + 1);
        }
      } catch (requestError) {
        if (active) {
          setPriceUpdateMessage(getApiErrorMessage(requestError));
          setPriceUpdateSeverity('error');
        }
      }
    };

    void poll();
    const interval = window.setInterval(() => void poll(), 1500);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [priceJobId, priceJobStatus]);

  const triggerPriceUpdate = async () => {
    if (!card) {
      return;
    }

    setIsRequestingPriceUpdate(true);
    setPriceUpdateMessage(null);
    setPriceUpdateSeverity('info');
    try {
      const response = await api.post<SyncJob>(`/cards/${card.id}/price-update`);
      const jobId = response.data.id;
      setPriceJob(response.data);
      setPriceUpdateMessage(jobId ? `Preisupdate angefordert. Job ${jobId} wurde angelegt.` : 'Preisupdate angefordert.');
    } catch (requestError) {
      setPriceUpdateMessage(getApiErrorMessage(requestError));
      setPriceUpdateSeverity('error');
    } finally {
      setIsRequestingPriceUpdate(false);
    }
  };

  const saveCardmarketLink = async (confirmed: boolean) => {
    if (!card) {
      return;
    }

    setCardmarketLinkAction(confirmed ? 'confirm' : 'save');
    setPriceUpdateMessage(null);
    try {
      const response = await api.put<CardDetail>(`/cards/${card.id}/cardmarket-link`, {
        url: trimmedCardmarketLinkDraft || null,
        confirmed,
      });
      setCard(response.data);
      setCardmarketLinkDraft(response.data.cardmarket_product_url || response.data.cardmarket_reference || response.data.pricing.cardmarket_url || '');
      setPriceUpdateMessage(confirmed ? 'Cardmarket-Link manuell bestätigt.' : 'Cardmarket-Link gespeichert.');
      setPriceUpdateSeverity('success');
    } catch (requestError) {
      setPriceUpdateMessage(getApiErrorMessage(requestError));
      setPriceUpdateSeverity('error');
    } finally {
      setCardmarketLinkAction(null);
    }
  };

  const saveCardEdit = async (payload: CardPayload) => {
    if (!card) {
      return;
    }

    setIsSavingEdit(true);
    setPriceUpdateMessage(null);
    try {
      await api.put(`/cards/${card.id}`, payload);
      setEditOpen(false);
      setPriceUpdateMessage('Karte gespeichert.');
      setPriceUpdateSeverity('success');
      setReloadToken((value) => value + 1);
    } catch (requestError) {
      setPriceUpdateMessage(getApiErrorMessage(requestError));
      setPriceUpdateSeverity('error');
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

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
        <Button component={Link} href="/cards" startIcon={<ArrowBackRoundedIcon />}>
          Zurück zur Kartenliste
        </Button>
        <Button variant="outlined" startIcon={<EditRoundedIcon />} onClick={() => setEditOpen(true)}>
          Karte bearbeiten
        </Button>
      </Stack>

      <Paper sx={{ p: 3 }}>
        <Grid container spacing={3}>
          <Grid item xs={12} md={4}>
            <Avatar src={resolveMediaUrl(card.image_url)} variant="rounded" sx={{ width: '100%', height: 420, bgcolor: 'rgba(255,255,255,0.05)' }} />
          </Grid>
          <Grid item xs={12} md={8}>
            <Typography variant="h3">{card.name}</Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap' }} useFlexGap>
              {card.rarity ? <Chip label={card.rarity} variant="outlined" /> : null}
              <Chip label={card.condition} color="secondary" variant="outlined" />
              <Chip label={card.set_code || 'Kein Setcode'} color="primary" variant="outlined" />
              <Chip label={card.language.toUpperCase()} variant="outlined" />
              <Chip label={pricingLabel(card.pricing)} color={pricingColor(card.pricing)} variant="outlined" />
              {pricingUpdateLabel(card.pricing) ? <Chip label={pricingUpdateLabel(card.pricing)} color="warning" variant="outlined" /> : null}
            </Stack>
            <Typography color="text.secondary" sx={{ mt: 1.5 }}>
              {card.effect_text || 'Kein Effekttext hinterlegt.'}
            </Typography>

            <Grid container spacing={2} sx={{ mt: 1 }}>
              <Grid item xs={12} sm={4}>
                <Paper sx={{ p: 2 }}>
                  <Typography color="text.secondary">Marktpreis</Typography>
                  <Typography variant="h5" sx={{ mt: 1 }}>
                    {formatCurrency(card.current_market_price, card.current_price_currency)}
                  </Typography>
                </Paper>
              </Grid>
              <Grid item xs={12} sm={4}>
                <Paper sx={{ p: 2 }}>
                  <Typography color="text.secondary">7 Tage</Typography>
                  <Typography variant="h5" sx={{ mt: 1, color: (card.price_change_7d || 0) >= 0 ? 'success.main' : 'error.main' }}>
                    {formatPercent(card.price_change_7d)}
                  </Typography>
                </Paper>
              </Grid>
              <Grid item xs={12} sm={4}>
                <Paper sx={{ p: 2 }}>
                  <Typography color="text.secondary">Lagerort</Typography>
                  <Typography variant="h6" sx={{ mt: 1 }}>
                    {card.storage_path || 'Nicht zugewiesen'}
                  </Typography>
                </Paper>
              </Grid>
            </Grid>
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
              <Box sx={{ height: 320 }}>
                {card.price_history.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={[...card.price_history].reverse()}>
                      <XAxis dataKey="captured_at" tickFormatter={(value) => formatDate(value).slice(0, 10)} stroke="#8ea092" />
                      <YAxis stroke="#8ea092" tickFormatter={(value) => `${card.current_price_currency || 'EUR'} ${value}`} />
                      <Tooltip formatter={(value) => formatCurrency(Number(value), card.current_price_currency)} labelFormatter={(value) => formatDate(String(value))} />
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
              <CardMetadataList card={card} />
            </Paper>
          </Stack>
        </Grid>

        <Grid item xs={12} lg={5}>
          <Stack spacing={2.5}>
            <Paper sx={{ p: 2.5 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Preisstatus
              </Typography>
              <Stack spacing={1.25}>
                <StatusRow label="Prüfstatus">
                  <Chip label={monitorStateLabel(card.pricing)} color={monitorStateColor(card.pricing)} variant="outlined" size="small" />
                </StatusRow>
                <StatusRow label="Preisquelle">{priceSourceLabel(card.pricing.source || latestSnapshot?.provider_key)}</StatusRow>
                <StatusRow label="Preis-Match">{pricingLabel(card.pricing)}</StatusRow>
                <StatusRow label="Letztes Preisupdate">{formatDate(card.pricing.last_updated_at || latestSnapshot?.captured_at)}</StatusRow>
                <StatusRow label="Letzter Check">{formatDate(card.pricing.last_price_check_at)}</StatusRow>
                <StatusRow label="Nächster Check">{formatDate(card.pricing.next_price_check_at)}</StatusRow>
                {card.pricing.price_check_interval_hours ? (
                  <StatusRow label="Prüfintervall">{card.pricing.price_check_interval_hours}h</StatusRow>
                ) : null}
                {(card.pricing.failure_count ?? 0) > 0 ? (
                  <StatusRow label="Fehlversuche">
                    <Typography component="span" color="error.main" fontWeight={700}>
                      {card.pricing.failure_count}
                    </Typography>
                  </StatusRow>
                ) : null}

                <Divider sx={{ my: 0.75 }} />
                <Typography variant="subtitle2">Cardmarket-Produktlink</Typography>
                <StatusRow label="Linkstatus">
                  <Chip
                    label={cardmarketLinkLabel(cardmarketLink ? cardmarketLinkQuality : null)}
                    color={cardmarketLinkColor(cardmarketLink ? cardmarketLinkQuality : null)}
                    variant="outlined"
                    size="small"
                  />
                </StatusRow>
                <TextField
                  label="Cardmarket-Link"
                  type="url"
                  size="small"
                  fullWidth
                  value={cardmarketLinkDraft}
                  error={Boolean(trimmedCardmarketLinkDraft) && !cardmarketLinkDraftIsValid}
                  helperText={
                    trimmedCardmarketLinkDraft && !cardmarketLinkDraftIsValid
                      ? 'Bitte einen gültigen Cardmarket-Produktlink eintragen.'
                      : undefined
                  }
                  onChange={(event) => setCardmarketLinkDraft(event.target.value)}
                />
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button
                    variant="outlined"
                    startIcon={cardmarketLinkAction === 'save' ? <CircularProgress size={18} color="inherit" /> : <SaveRoundedIcon />}
                    disabled={
                      cardmarketLinkAction !== null
                      || (Boolean(trimmedCardmarketLinkDraft) && !cardmarketLinkDraftIsValid)
                      || cardmarketLinkDraftMatchesStored
                    }
                    onClick={() => void saveCardmarketLink(false)}
                  >
                    Speichern
                  </Button>
                  <Button
                    component="a"
                    href={cardmarketLinkDraftIsValid ? trimmedCardmarketLinkDraft : undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    variant="outlined"
                    startIcon={<OpenInNewRoundedIcon />}
                    disabled={!cardmarketLinkDraftIsValid}
                  >
                    Öffnen
                  </Button>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={cardmarketLinkAction === 'confirm' ? <CircularProgress size={18} color="inherit" /> : <TaskAltRoundedIcon />}
                    disabled={cardmarketLinkAction !== null || !cardmarketLinkDraftIsValid || cardmarketLinkIsManuallyConfirmed}
                    onClick={() => void saveCardmarketLink(true)}
                  >
                    {cardmarketLinkIsManuallyConfirmed ? 'Bestätigt' : 'Bestätigen'}
                  </Button>
                </Stack>
                {card.cardmarket_verified_at ? (
                  <StatusRow label={cardmarketLinkQuality === 'manual_verified' ? 'Manuell bestätigt am' : 'Verifiziert am'}>
                    {formatDate(card.cardmarket_verified_at)}
                  </StatusRow>
                ) : null}

                {hasCardmarketOfferData && latestSnapshot ? (
                  <>
                    <Divider sx={{ my: 0.75 }} />
                    <Typography variant="subtitle2">Cardmarket-Angebotsdaten</Typography>
                    {medianTop5Price !== null ? (
                      <StatusRow label="Median Top 5">{formatCurrency(medianTop5Price, latestSnapshot.currency)}</StatusRow>
                    ) : null}
                    {latestSnapshot.lowest_offer_price !== null && latestSnapshot.lowest_offer_price !== undefined ? (
                      <StatusRow label="Niedrigstes Angebot">
                        {formatCurrency(latestSnapshot.lowest_offer_price, latestSnapshot.currency)}
                      </StatusRow>
                    ) : null}
                    {latestSnapshot.avg_1d !== null && latestSnapshot.avg_1d !== undefined ? (
                      <StatusRow label="1-Tages-Durchschnitt">{formatCurrency(latestSnapshot.avg_1d, latestSnapshot.currency)}</StatusRow>
                    ) : null}
                    {latestSnapshot.avg_7d !== null && latestSnapshot.avg_7d !== undefined ? (
                      <StatusRow label="7-Tages-Durchschnitt">{formatCurrency(latestSnapshot.avg_7d, latestSnapshot.currency)}</StatusRow>
                    ) : null}
                    {latestSnapshot.avg_30d !== null && latestSnapshot.avg_30d !== undefined ? (
                      <StatusRow label="30-Tages-Durchschnitt">{formatCurrency(latestSnapshot.avg_30d, latestSnapshot.currency)}</StatusRow>
                    ) : null}
                    {latestSnapshot.price_trend !== null && latestSnapshot.price_trend !== undefined ? (
                      <StatusRow label="Preis-Trend">{formatCurrency(latestSnapshot.price_trend, latestSnapshot.currency)}</StatusRow>
                    ) : null}
                    {offersConsideredCount !== null ? (
                      <StatusRow label="Berücksichtigte Angebote">{offersConsideredCount}</StatusRow>
                    ) : null}
                    {top5OfferPrices.length > 0 ? (
                      <StatusRow label="Top-5-Angebote">
                        {top5OfferPrices.map((price) => formatCurrency(price, latestSnapshot.currency)).join(', ')}
                      </StatusRow>
                    ) : null}
                  </>
                ) : null}
              </Stack>

              <Stack direction="row" spacing={1.5} sx={{ mt: 2, flexWrap: 'wrap' }} useFlexGap>
                <Button
                  variant="contained"
                  startIcon={isRequestingPriceUpdate ? <CircularProgress size={18} color="inherit" /> : <RefreshRoundedIcon />}
                  onClick={triggerPriceUpdate}
                  disabled={isRequestingPriceUpdate || Boolean(activePriceJob)}
                >
                  {isRequestingPriceUpdate ? 'Preisupdate startet...' : 'Preis aktualisieren'}
                </Button>
              </Stack>

              {activePriceJob ? (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Preisupdate läuft...
                  </Typography>
                  <Stack direction="row" spacing={2} alignItems="center">
                    <Box sx={{ flex: 1 }}>
                      {activePriceJob.total_items && activePriceJob.total_items > 0 ? (
                        <LinearProgress
                          variant="determinate"
                          value={((activePriceJob.processed_items || 0) / activePriceJob.total_items) * 100}
                        />
                      ) : (
                        <LinearProgress />
                      )}
                    </Box>
                    <Typography variant="body2" color="text.secondary">
                      {activePriceJob.total_items && activePriceJob.total_items > 0
                        ? `${activePriceJob.processed_items || 0} / ${activePriceJob.total_items}`
                        : 'Wird vorbereitet...'}
                    </Typography>
                  </Stack>
                  {activePriceJob.next_scheduled_item_at ? (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Nächste Aktualisierung: {formatDate(activePriceJob.next_scheduled_item_at)}
                    </Typography>
                  ) : null}
                  {activePriceJob.rate_limit_per_minute ? (
                    <Typography variant="body2" color="text.secondary">
                      Rate-Limit: {activePriceJob.rate_limit_per_minute} Anfragen/Minute
                    </Typography>
                  ) : null}
                </Box>
              ) : null}

              {priceUpdateMessage ? (
                <Alert severity={priceUpdateSeverity} sx={{ mt: 2 }}>
                  {priceUpdateMessage}
                </Alert>
              ) : null}

              {card.pricing.note ? (
                <Alert severity={card.pricing.status === 'fallback' || card.pricing.status === 'unpriced' ? 'warning' : 'info'} sx={{ mt: 2 }}>
                  {card.pricing.note}
                </Alert>
              ) : null}

              {latestSnapshot?.parse_status && latestSnapshot.parse_status !== 'ok' ? (
                <Alert severity="info" sx={{ mt: 2 }}>
                  Parser-Status: {latestSnapshot.parse_status}
                </Alert>
              ) : null}
            </Paper>

            <Paper sx={{ p: 2.5 }}>
              <Typography variant="h6">Quellen & Snapshots</Typography>
              <Divider sx={{ my: 2 }} />
              <Typography color="text.secondary" sx={{ mb: 1 }}>
                Externe Zuordnungen
              </Typography>
              <List disablePadding>
                {sourceMappings.map((mapping) => (
                  <ListItem key={`${mapping.provider_key}-${mapping.external_id}-${mapping.external_url || ''}`} disableGutters sx={{ py: 1 }}>
                    <ListItemText
                      primary={`${priceSourceLabel(mapping.provider_key)} - ID ${mapping.external_id}`}
                      secondary={mapping.external_url || 'Keine externe URL'}
                      secondaryTypographyProps={{ sx: { overflowWrap: 'anywhere' } }}
                    />
                  </ListItem>
                ))}
                {sourceMappings.length === 0 ? (
                  <ListItem disableGutters sx={{ py: 1 }}>
                    <ListItemText secondary="Keine externe Zuordnung vorhanden." />
                  </ListItem>
                ) : null}
              </List>

              <Typography color="text.secondary" sx={{ mt: 2.5, mb: 1 }}>
                Letzte Preisstände
              </Typography>
              <List disablePadding>
                {card.price_history.slice(0, 6).map((entry) => (
                  <ListItem key={`${entry.provider_key}-${entry.captured_at}`} disableGutters sx={{ py: 1 }}>
                    <ListItemText
                      primary={`${priceSourceLabel(entry.provider_key)} - ${formatCurrency(entry.price, entry.currency)}`}
                      secondary={[
                        formatDate(entry.captured_at),
                        entry.match_quality ? priceMatchLabel(entry.match_quality) : null,
                        entry.set_code || null,
                        entry.rarity || null,
                      ]
                        .filter(Boolean)
                        .join(' | ')}
                    />
                  </ListItem>
                ))}
                {card.price_history.length === 0 ? (
                  <ListItem disableGutters sx={{ py: 1 }}>
                    <ListItemText secondary="Noch kein gültiger Preisstand vorhanden." />
                  </ListItem>
                ) : null}
              </List>
            </Paper>
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
