import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Alert, Avatar, Box, Chip, CircularProgress, Grid, List, ListItemButton, Paper, Stack, Typography } from '@mui/material';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import StatCard from '../components/stat-card';
import PageHeader from '../components/page-header';
import api, { getApiErrorMessage, resolveMediaUrl } from '../lib/api';
import { formatCardPrintDescriptor } from '../lib/card-display';
import { formatCurrency, formatDate, formatPercent } from '../lib/format';
import { DashboardResponse, DashboardTrendItem } from '../lib/types';

type DashboardSectionVariant = 'gainer' | 'loser' | 'trend' | 'missing' | 'review' | 'recent';

function DashboardSection({
  title,
  items,
  variant,
  emptyText,
}: {
  title: string;
  items: DashboardTrendItem[];
  variant: DashboardSectionVariant;
  emptyText: string;
}) {
  return (
    <Paper sx={{ p: 2.5, height: '100%' }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        {title}
      </Typography>
      {items.length ? (
        <List disablePadding sx={{ display: 'grid', gap: 0.75 }}>
          {items.map((item) => (
            <ListItemButton
              key={`${variant}-${item.inventory_item_id}`}
              component={Link}
              href={`/cards/${item.inventory_item_id}`}
              sx={{
                alignItems: 'flex-start',
                gap: 1.5,
                py: 1.5,
                px: 1.5,
                borderRadius: 2,
                border: '1px solid rgba(255,255,255,0.06)',
                background: 'rgba(255,255,255,0.02)',
                transition: 'transform 160ms ease, border-color 160ms ease, background-color 160ms ease',
                textDecoration: 'none',
                color: 'inherit',
                '&:hover': {
                  transform: 'translateY(-1px)',
                  borderColor: 'rgba(216,169,76,0.26)',
                  background: 'rgba(216,169,76,0.06)',
                },
                '&.Mui-focusVisible': {
                  borderColor: 'rgba(216,169,76,0.55)',
                  background: 'rgba(216,169,76,0.09)',
                },
              }}
            >
              <Avatar
                src={resolveMediaUrl(item.image_url) || undefined}
                variant="rounded"
                sx={{ width: 46, height: 64, bgcolor: 'rgba(255,255,255,0.05)', flexShrink: 0 }}
              />
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography fontWeight={800} noWrap>
                  {item.name}
                </Typography>
                <Typography variant="body2" color="text.secondary" noWrap>
                  {formatCardPrintDescriptor(item)}
                </Typography>
                <Typography variant="body2" color="text.secondary" noWrap>
                  {item.storage_path || 'Kein Lagerort'}
                  {item.quantity > 1 ? ` | Bestand ${item.quantity}` : ''}
                </Typography>
                <Stack direction="row" spacing={0.75} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                  {variant === 'review' && item.review_reasons?.length
                    ? item.review_reasons.map((reason) => <Chip key={reason} label={reason} size="small" variant="outlined" color="warning" />)
                    : null}
                  {variant === 'missing' ? <Chip label="Kein Preis" size="small" color="warning" variant="outlined" /> : null}
                  {(variant === 'gainer' || variant === 'loser' || variant === 'trend') && item.price_change_7d !== null && item.price_change_7d !== undefined ? (
                    <Chip
                      label={formatPercent(item.price_change_7d)}
                      size="small"
                      color={(item.price_change_7d || 0) >= 0 ? 'success' : 'error'}
                      variant="outlined"
                    />
                  ) : null}
                  {(variant === 'gainer' || variant === 'loser' || variant === 'trend') && item.price_change_30d !== null && item.price_change_30d !== undefined ? (
                    <Chip label={`30d ${formatPercent(item.price_change_30d)}`} size="small" variant="outlined" />
                  ) : null}
                  {(variant === 'gainer' || variant === 'loser' || variant === 'trend') && item.trend_score !== null && item.trend_score !== undefined ? (
                    <Chip label={`Score ${item.trend_score.toFixed(1)}`} size="small" variant="outlined" color="secondary" />
                  ) : null}
                  {variant === 'recent' && item.last_priced_at ? (
                    <Chip label={formatDate(item.last_priced_at)} size="small" variant="outlined" color="secondary" />
                  ) : null}
                  {variant === 'trend' && item.current_market_price !== null && item.current_market_price !== undefined ? (
                    <Chip
                      label={formatCurrency(item.current_market_price, item.current_price_currency || 'EUR')}
                      size="small"
                      variant="outlined"
                      color="primary"
                    />
                  ) : null}
                  {variant === 'review' && item.current_market_price !== null && item.current_market_price !== undefined ? (
                    <Chip
                      label={formatCurrency(item.current_market_price, item.current_price_currency || 'EUR')}
                      size="small"
                      variant="outlined"
                      color="primary"
                    />
                  ) : null}
                  {variant === 'missing' && item.last_price_match_quality ? (
                    <Chip label={item.last_price_match_quality} size="small" variant="outlined" color="warning" />
                  ) : null}
                </Stack>
              </Box>
              <Box sx={{ textAlign: 'right', flexShrink: 0, minWidth: 96 }}>
                <Typography fontWeight={800}>
                  {item.current_market_price !== null && item.current_market_price !== undefined
                    ? formatCurrency(item.current_market_price, item.current_price_currency || 'EUR')
                    : 'n/a'}
                </Typography>
                {item.last_priced_at ? (
                  <Typography variant="body2" color="text.secondary">
                    {formatDate(item.last_priced_at)}
                  </Typography>
                ) : null}
              </Box>
            </ListItemButton>
          ))}
        </List>
      ) : (
        <Box sx={{ p: 2.5, color: 'text.secondary' }}>{emptyText}</Box>
      )}
    </Paper>
  );
}

function JobsSection({ jobs }: { jobs: DashboardResponse['recent_jobs'] }) {
  return (
    <Paper sx={{ p: 2.5, height: '100%' }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Letzte Jobs
      </Typography>
      <List disablePadding sx={{ display: 'grid', gap: 0.75 }}>
        {jobs.length ? (
          jobs.map((job) => (
            <Box
              key={job.id}
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: 2,
                py: 1.25,
                px: 1.5,
                borderRadius: 2,
                border: '1px solid rgba(255,255,255,0.06)',
                background: 'rgba(255,255,255,0.02)',
              }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography fontWeight={800}>{job.job_type}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {job.log_excerpt || formatDate(job.created_at)}
                </Typography>
                {job.is_stuck ? <Chip label={job.stuck_reason || 'Stuck'} size="small" color="warning" variant="outlined" sx={{ mt: 1 }} /> : null}
              </Box>
              <Chip
                label={job.status}
                size="small"
                color={job.status === 'completed' ? 'success' : job.status === 'failed' ? 'error' : 'warning'}
                variant="outlined"
              />
            </Box>
          ))
        ) : (
          <Box sx={{ p: 2.5, color: 'text.secondary' }}>Noch keine Jobs vorhanden.</Box>
        )}
      </List>
    </Paper>
  );
}

export default function Home() {
  const [stats, setStats] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const response = await api.get<DashboardResponse>('/dashboard/');
        if (active) {
          setStats(response.data);
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
  }, []);

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  if (!stats) {
    return <CircularProgress />;
  }

  return (
    <Stack spacing={3}>
      <PageHeader title="Dashboard" description="Überblick über Bestand, Wertentwicklung und offene Prüfungen." />

      <Grid container spacing={2.5}>
        <Grid item xs={12} sm={6} xl={3}>
          <StatCard label="Gesamtanzahl" value={stats.total_cards.toString()} sublabel={`${stats.distinct_items} Inventarpositionen`} />
        </Grid>
        <Grid item xs={12} sm={6} xl={3}>
          <StatCard
            label="Sammlungswert"
            value={formatCurrency(stats.total_value, stats.display_currency)}
            sublabel="Aktueller Marktwert der Positionen"
            trend={`${stats.priced_cards} mit Preis`}
          />
        </Grid>
        <Grid item xs={12} sm={6} xl={3}>
          <StatCard label="Karten mit Bild" value={stats.cards_with_images.toString()} sublabel="Lokal ausgelieferte Bilder" accent="secondary" />
        </Grid>
        <Grid item xs={12} sm={6} xl={3}>
          <StatCard
            label="Preisupdates"
            value={stats.recent_price_updates.length.toString()}
            sublabel="Kürzlich aktualisierte Karten"
            accent="warning"
          />
        </Grid>
      </Grid>

      <Grid container spacing={2.5}>
        <Grid item xs={12} xl={7}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Wertverlauf der Sammlung
            </Typography>
            <Box sx={{ height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stats.value_history}>
                  <defs>
                    <linearGradient id="valueFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#d8a94c" stopOpacity={0.6} />
                      <stop offset="100%" stopColor="#d8a94c" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" stroke="#8ea092" />
                  <YAxis stroke="#8ea092" tickFormatter={(value) => `${stats.display_currency} ${value}`} />
                  <Tooltip formatter={(value) => formatCurrency(Number(value), stats.display_currency)} />
                  <Area type="monotone" dataKey="total_value" stroke="#d8a94c" strokeWidth={3} fill="url(#valueFill)" />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6} xl={5}>
          <DashboardSection title="Top Preissteigerungen" items={stats.top_gainers} variant="gainer" emptyText="Keine Gewinner gefunden." />
        </Grid>
        <Grid item xs={12} md={6} xl={5}>
          <DashboardSection title="Top Preisrückgänge" items={stats.top_losers} variant="loser" emptyText="Keine Verlierer gefunden." />
        </Grid>
        <Grid item xs={12} md={6} xl={4}>
          <DashboardSection title="Aktuell trendende Karten" items={stats.trending_cards} variant="trend" emptyText="Keine Trendkarten gefunden." />
        </Grid>
        <Grid item xs={12} md={6} xl={3}>
          <DashboardSection title="Karten ohne Preis" items={stats.missing_price_cards} variant="missing" emptyText="Alle Karten haben aktuell einen Preis." />
        </Grid>
        <Grid item xs={12} lg={7}>
          <DashboardSection title="Review-Kandidaten" items={stats.review_candidates} variant="review" emptyText="Keine Review-Kandidaten gefunden." />
        </Grid>
        <Grid item xs={12} lg={5}>
          <DashboardSection title="Zuletzt aktualisierte Preise" items={stats.recent_price_updates} variant="recent" emptyText="Noch keine Preisupdates vorhanden." />
        </Grid>
        <Grid item xs={12} lg={5}>
          <JobsSection jobs={stats.recent_jobs} />
        </Grid>
      </Grid>
    </Stack>
  );
}
