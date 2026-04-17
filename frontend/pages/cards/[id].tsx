import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
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
  Typography,
} from '@mui/material';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import api, { getApiErrorMessage, resolveMediaUrl } from '../../lib/api';
import { formatCurrency, formatDate, formatPercent } from '../../lib/format';
import { cardmarketLinkColor, cardmarketLinkLabel, monitorStateColor, monitorStateLabel, pricingColor, pricingLabel, pricingUpdateLabel } from '../../lib/pricing';
import { CardDetail } from '../../lib/types';

type MetadataKey = 'card_type' | 'subtype' | 'attribute' | 'monster_type' | 'atk' | 'defense' | 'level' | 'rank' | 'link_rating';

const metadataRows: Array<{ label: string; key: MetadataKey }> = [
  { label: 'Kartentyp', key: 'card_type' },
  { label: 'Untertyp', key: 'subtype' },
  { label: 'Attribut', key: 'attribute' },
  { label: 'Monster-Typ', key: 'monster_type' },
  { label: 'ATK', key: 'atk' },
  { label: 'DEF', key: 'defense' },
  { label: 'Level', key: 'level' },
  { label: 'Rank', key: 'rank' },
  { label: 'Link', key: 'link_rating' },
];

function formatMetadataValue(card: CardDetail, key: MetadataKey): string {
  const value = card[key];

  if (value === null || value === undefined || value === '') {
    return 'n/a';
  }

  return typeof value === 'number' ? String(value) : value;
}

function formatCardmarketLanguage(value: unknown): string {
  if (value === 3 || value === '3') {
    return 'Deutsch';
  }
  if (value === 1 || value === '1') {
    return 'Englisch';
  }
  if (typeof value === 'string' && value.trim()) {
    return value.toString();
  }
  return 'n/a';
}

function formatCardmarketCondition(value: unknown): string {
  const numeric = typeof value === 'number' ? value : Number(value);
  const labels: Record<number, string> = {
    1: 'Mint',
    2: 'Near Mint',
    3: 'Excellent',
    4: 'Good',
    5: 'Poor',
  };
  return Number.isFinite(numeric) && labels[numeric] ? labels[numeric] : typeof value === 'string' && value.trim() ? value.toString() : 'n/a';
}

export default function CardDetailPage() {
  const router = useRouter();
  const [card, setCard] = useState<CardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRequestingPriceUpdate, setIsRequestingPriceUpdate] = useState(false);
  const [priceUpdateMessage, setPriceUpdateMessage] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const latestSnapshot = card?.price_history?.[0] ?? null;
  const latestFilters = (latestSnapshot?.filters_used ?? {}) as Record<string, unknown>;
  const cardmarketLink = latestSnapshot?.source_url || card?.cardmarket_product_url || card?.pricing.cardmarket_url || null;
  const cardmarketLinkQuality = latestSnapshot?.match_quality || card?.cardmarket_match_quality || card?.pricing.cardmarket_link_mode || null;
  const cardmarketLinkIsExact = cardmarketLinkQuality === 'exact_verified' || cardmarketLinkQuality === 'exact_verified_variant';
  const cardmarketLinkIsSafe = cardmarketLinkIsExact || cardmarketLinkQuality === 'set_name_verified_name_only';
  const medianTop5Price = latestSnapshot?.market_price_median_top5 ?? latestSnapshot?.selected_market_price ?? latestSnapshot?.price ?? null;
  const offersConsideredCount = latestSnapshot?.offers_considered_count ?? latestSnapshot?.offer_count_considered ?? null;
  const top5OfferPrices = latestSnapshot?.top5_offer_prices?.length ? latestSnapshot.top5_offer_prices : latestSnapshot?.raw_offer_prices_sample ?? [];

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

  const triggerPriceUpdate = async () => {
    if (!card) {
      return;
    }

    setIsRequestingPriceUpdate(true);
    setPriceUpdateMessage(null);
    try {
      const response = await api.post<{ id?: number }>(`/cards/${card.id}/price-update`);
      const jobId = response.data?.id;
      setPriceUpdateMessage(jobId ? `Preisupdate angefordert. Job ${jobId} wurde angelegt.` : 'Preisupdate angefordert.');
      setReloadToken((value) => value + 1);
    } catch (requestError) {
      setPriceUpdateMessage(getApiErrorMessage(requestError));
    } finally {
      setIsRequestingPriceUpdate(false);
    }
  };

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  if (!card) {
    return <CircularProgress />;
  }

  return (
    <Stack spacing={3}>
      <Button component={Link} href="/cards" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>
        Zurueck zur Kartenliste
      </Button>

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
              {cardmarketLinkQuality ? (
                <Chip label={cardmarketLinkLabel(cardmarketLinkQuality)} color={cardmarketLinkColor(cardmarketLinkQuality)} variant="outlined" />
              ) : null}
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

      <Grid container spacing={2.5}>
        <Grid item xs={12} lg={7}>
          <Paper sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Preisverlauf
            </Typography>
            <Box sx={{ height: 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={[...card.price_history].reverse()}>
                  <XAxis dataKey="captured_at" tickFormatter={(value) => formatDate(value).slice(0, 10)} stroke="#8ea092" />
                  <YAxis stroke="#8ea092" tickFormatter={(value) => `${card.current_price_currency || 'EUR'} ${value}`} />
                  <Tooltip formatter={(value) => formatCurrency(Number(value), card.current_price_currency)} labelFormatter={(value) => formatDate(String(value))} />
                  <Line type="monotone" dataKey="price" stroke="#d8a94c" strokeWidth={3} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} lg={5}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Preisstatus
            </Typography>
            <Stack spacing={1.25}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Pruefstatus</Typography>
                <Chip label={monitorStateLabel(card.pricing)} color={monitorStateColor(card.pricing)} variant="outlined" size="small" />
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Match</Typography>
                <Typography fontWeight={700}>{pricingLabel(card.pricing)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Cardmarket-Link</Typography>
                <Typography fontWeight={700}>{cardmarketLinkQuality || 'n/a'}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Quelle</Typography>
                <Typography fontWeight={700}>{latestSnapshot?.provider_key || card.pricing.source || 'n/a'}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Letzter Check</Typography>
                <Typography fontWeight={700}>{formatDate(card.pricing.last_price_check_at || latestSnapshot?.captured_at)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Naechster Check</Typography>
                <Typography fontWeight={700}>{formatDate(card.pricing.next_price_check_at)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Intervall</Typography>
                <Typography fontWeight={700}>{card.pricing.price_check_interval_hours ? `${card.pricing.price_check_interval_hours}h` : 'n/a'}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Volatilitaet</Typography>
                <Typography fontWeight={700}>
                  {card.pricing.price_volatility_score !== undefined && card.pricing.price_volatility_score !== null
                    ? `${card.pricing.price_volatility_score.toFixed(2)}`
                    : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Prioritaet</Typography>
                <Typography fontWeight={700}>{card.pricing.price_check_priority ?? 'n/a'}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Niedrigstes Angebot</Typography>
                <Typography fontWeight={700}>
                  {latestSnapshot ? formatCurrency(latestSnapshot.lowest_offer_price, latestSnapshot.currency) : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Marktpreis (Median Top 5)</Typography>
                <Typography fontWeight={700}>
                  {latestSnapshot ? formatCurrency(medianTop5Price, latestSnapshot.currency) : formatCurrency(card.current_market_price, card.current_price_currency)}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">1-Tages-Durchschnitt</Typography>
                <Typography fontWeight={700}>
                  {latestSnapshot?.avg_1d !== undefined && latestSnapshot?.avg_1d !== null
                    ? formatCurrency(latestSnapshot.avg_1d, latestSnapshot.currency)
                    : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">7-Tages-Durchschnitt</Typography>
                <Typography fontWeight={700}>
                  {latestSnapshot?.avg_7d !== undefined && latestSnapshot?.avg_7d !== null
                    ? formatCurrency(latestSnapshot.avg_7d, latestSnapshot.currency)
                    : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">30-Tages-Durchschnitt</Typography>
                <Typography fontWeight={700}>
                  {latestSnapshot?.avg_30d !== undefined && latestSnapshot?.avg_30d !== null
                    ? formatCurrency(latestSnapshot.avg_30d, latestSnapshot.currency)
                    : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Angebote fuer Median</Typography>
                <Typography fontWeight={700}>{offersConsideredCount ?? 'n/a'}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Top-5-Angebote</Typography>
                <Typography fontWeight={700}>
                  {top5OfferPrices.length > 0
                    ? top5OfferPrices.map((price) => formatCurrency(price, latestSnapshot?.currency || card.current_price_currency)).join(', ')
                    : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Fehlversuche</Typography>
                <Typography fontWeight={700}>{card.pricing.failure_count ?? 0}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Sprache</Typography>
                <Typography fontWeight={700}>{formatCardmarketLanguage(latestFilters.language ?? card.language)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Mindestzustand</Typography>
                <Typography fontWeight={700}>{formatCardmarketCondition(latestFilters.min_condition)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Preis-Trend</Typography>
                <Typography fontWeight={700}>
                  {latestSnapshot?.price_trend !== undefined && latestSnapshot?.price_trend !== null
                    ? formatCurrency(latestSnapshot.price_trend, latestSnapshot.currency)
                    : 'n/a'}
                </Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Letztes Preisupdate</Typography>
                <Typography fontWeight={700}>{formatDate(card.pricing.last_updated_at || latestSnapshot?.captured_at)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Verifiziert am</Typography>
                <Typography fontWeight={700}>{formatDate(card.cardmarket_verified_at || latestSnapshot?.captured_at)}</Typography>
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography color="text.secondary">Print-Kontext</Typography>
                <Typography fontWeight={700}>
                  {[card.cardmarket_set_name || card.set_name, card.set_code, card.card_number, card.rarity, card.language.toUpperCase()]
                    .filter(Boolean)
                    .join(' | ') || 'n/a'}
                </Typography>
              </Box>
            </Stack>

            <Stack direction="row" spacing={1.5} sx={{ mt: 2, flexWrap: 'wrap' }} useFlexGap>
              <Button variant="contained" onClick={triggerPriceUpdate} disabled={isRequestingPriceUpdate || card.pricing.is_updating}>
                {isRequestingPriceUpdate ? 'Preisupdate startet...' : 'Preis aktualisieren'}
              </Button>
              {pricingUpdateLabel(card.pricing) ? (
                <Chip label={pricingUpdateLabel(card.pricing)} color="warning" variant="outlined" />
              ) : null}
            </Stack>

            {card.pricing.pending_job ? (
              <Box sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Preisupdate läuft...
                </Typography>
                <Stack direction="row" spacing={2} alignItems="center">
                  <Box sx={{ flex: 1 }}>
                    {card.pricing.pending_job.total_items && card.pricing.pending_job.total_items > 0 ? (
                      <LinearProgress
                        variant="determinate"
                        value={((card.pricing.pending_job.processed_items || 0) / card.pricing.pending_job.total_items) * 100}
                      />
                    ) : (
                      <LinearProgress />
                    )}
                  </Box>
                  <Typography variant="body2" color="text.secondary">
                    {card.pricing.pending_job.total_items && card.pricing.pending_job.total_items > 0
                      ? `${card.pricing.pending_job.processed_items || 0} / ${card.pricing.pending_job.total_items}`
                      : 'Wird vorbereitet...'}
                  </Typography>
                </Stack>
                {card.pricing.pending_job.next_scheduled_item_at ? (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    Nächste Aktualisierung: {formatDate(card.pricing.pending_job.next_scheduled_item_at)}
                  </Typography>
                ) : null}
                {card.pricing.pending_job.rate_limit_per_minute ? (
                  <Typography variant="body2" color="text.secondary">
                    Rate-Limit: {card.pricing.pending_job.rate_limit_per_minute} Anfragen/Minute
                  </Typography>
                ) : null}
              </Box>
            ) : null}

            {priceUpdateMessage ? (
              <Alert severity={priceUpdateMessage.toLowerCase().includes('fehl') ? 'error' : 'info'} sx={{ mt: 2 }}>
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

            {cardmarketLink ? (
              <Button
                component="a"
                href={cardmarketLink}
                target="_blank"
                rel="noreferrer"
                startIcon={<OpenInNewRoundedIcon />}
                variant={cardmarketLinkIsExact ? 'contained' : 'outlined'}
                color={cardmarketLinkIsSafe ? 'primary' : 'warning'}
                disabled={!cardmarketLink || cardmarketLinkQuality === 'failed'}
                sx={{ mt: 2.5 }}
              >
                {cardmarketLinkIsExact ? 'Zum verifizierten Cardmarket-Produkt' : cardmarketLinkQuality === 'set_name_verified_name_only' ? 'Cardmarket-Produkt (Name-only)' : 'Cardmarket-Produkt oeffnen'}
              </Button>
            ) : null}
          </Paper>
        </Grid>
        <Grid item xs={12} lg={7}>
          <Paper sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Kartendetails
            </Typography>
            <List disablePadding>
              {metadataRows.map((row) => (
                <ListItem key={row.label} disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  <ListItemText primary={row.label} secondary={formatMetadataValue(card, row.key)} />
                </ListItem>
              ))}
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText primary="Edition" secondary={card.edition || 'n/a'} />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText primary="Release" secondary={card.release_date || 'n/a'} />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText
                  primary="Cardmarket-Set"
                  secondary={[card.cardmarket_set_name, card.cardmarket_set_slug].filter(Boolean).join(' | ') || 'n/a'}
                />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText
                  primary="Cardmarket-Produkt"
                  secondary={[card.cardmarket_product_name, card.cardmarket_variant_name].filter(Boolean).join(' | ') || 'n/a'}
                />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText primary="Cardmarket-Kategorie" secondary={card.cardmarket_category || 'n/a'} />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText primary="Cardmarket-Qualitaet" secondary={card.cardmarket_match_quality || card.pricing.cardmarket_link_mode || 'n/a'} />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <ListItemText
                  primary="Erwarteter Print"
                  secondary={[card.cardmarket_expected_set_name, card.cardmarket_expected_rarity, card.cardmarket_expected_language]
                    .filter(Boolean)
                    .join(' | ') || 'n/a'}
                />
              </ListItem>
              <ListItem disableGutters sx={{ py: 1.1 }}>
                <ListItemText primary="Tags" secondary={card.tags.length ? card.tags.join(', ') : 'Keine'} />
              </ListItem>
            </List>
          </Paper>
        </Grid>
        <Grid item xs={12} lg={5}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6">Quellen & Snapshots</Typography>
            <Divider sx={{ my: 2 }} />
            <Typography color="text.secondary" sx={{ mb: 1 }}>
              Source Mappings
            </Typography>
            <List disablePadding>
              {card.source_mappings.map((mapping) => (
                <ListItem key={`${mapping.provider_key}-${mapping.external_id}`} disableGutters sx={{ py: 1 }}>
                  <ListItemText primary={`${mapping.provider_key}: ${mapping.external_id}`} secondary={mapping.external_url || 'Keine externe URL'} />
                </ListItem>
              ))}
            </List>

            <Typography color="text.secondary" sx={{ mt: 2.5, mb: 1 }}>
              Letzte Snapshots
            </Typography>
            <List disablePadding>
              {card.price_history.slice(0, 6).map((entry) => (
                <ListItem key={`${entry.provider_key}-${entry.captured_at}`} disableGutters sx={{ py: 1 }}>
                  <ListItemText
                    primary={`${entry.provider_key} - ${formatCurrency(entry.price, entry.currency)}`}
                    secondary={[
                      formatDate(entry.captured_at),
                      entry.match_quality || null,
                      entry.set_code || null,
                      entry.rarity || null,
                    ]
                      .filter(Boolean)
                      .join(' | ')}
                  />
                </ListItem>
              ))}
            </List>
          </Paper>
        </Grid>
      </Grid>
    </Stack>
  );
}
