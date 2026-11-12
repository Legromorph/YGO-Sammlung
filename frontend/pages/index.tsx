import Link from 'next/link';
import { type ReactNode, useEffect, useState } from 'react';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded';
import LayersRoundedIcon from '@mui/icons-material/LayersRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import {
  Alert,
  Avatar,
  Box,
  Button,
  CircularProgress,
  Grid,
  List,
  ListItemButton,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import PageHeader from '../components/page-header';
import StatCard from '../components/stat-card';
import api, { getApiErrorMessage, resolveMediaUrl } from '../lib/api';
import { formatCardPrintDescriptor } from '../lib/card-display';
import { formatCurrency, formatPercent } from '../lib/format';
import { DashboardResponse, DashboardTrendItem, SyncJob } from '../lib/types';

function CardRow({ item, right }: { item: DashboardTrendItem; right: ReactNode }) {
  return (
    <ListItemButton
      component={Link}
      href={`/cards/${item.inventory_item_id}`}
      sx={{ gap: 1.5, py: 1, px: 1.25, borderRadius: 2, color: 'inherit' }}
    >
      <Avatar
        src={resolveMediaUrl(item.image_url) || undefined}
        variant="rounded"
        sx={{ width: 34, height: 48, bgcolor: 'rgba(255,255,255,0.05)', flexShrink: 0 }}
      />
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography fontWeight={700} noWrap>
          {item.name}
          {item.quantity > 1 ? (
            <Typography component="span" color="text.secondary" fontWeight={400}>
              {` ×${item.quantity}`}
            </Typography>
          ) : null}
        </Typography>
        <Typography variant="body2" color="text.secondary" noWrap>
          {formatCardPrintDescriptor(item)}
        </Typography>
      </Box>
      <Box sx={{ textAlign: 'right', flexShrink: 0 }}>{right}</Box>
    </ListItemButton>
  );
}

function EmptyHint({ children }: { children: ReactNode }) {
  return (
    <Typography color="text.secondary" sx={{ p: 2 }}>
      {children}
    </Typography>
  );
}

function AttentionRow({ count, label, href }: { count: number; label: string; href: string }) {
  if (!count) {
    return null;
  }
  return (
    <ListItemButton component={Link} href={href} sx={{ borderRadius: 2, gap: 1.5, color: 'inherit' }}>
      <WarningAmberRoundedIcon color="warning" />
      <Typography sx={{ flex: 1 }}>
        <strong>{count}</strong> {label}
      </Typography>
      <ChevronRightRoundedIcon color="action" />
    </ListItemButton>
  );
}

export default function Home() {
  const [stats, setStats] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moversTab, setMoversTab] = useState<'up' | 'down'>('up');
  const [refreshJob, setRefreshJob] = useState<SyncJob | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .get<DashboardResponse>('/dashboard/')
      .then((response) => {
        if (active) {
          setStats(response.data);
          setError(null);
        }
      })
      .catch((requestError) => {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const refreshAllPrices = async () => {
    setRefreshError(null);
    try {
      const response = await api.post<SyncJob>('/sync/jobs', { job_type: 'price_update', force: true, payload: { trigger: 'dashboard' } });
      setRefreshJob(response.data);
    } catch (requestError) {
      setRefreshError(getApiErrorMessage(requestError));
    }
  };

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }
  if (!stats) {
    return <CircularProgress />;
  }

  const currency = stats.display_currency;
  const actions = (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      <Button component={Link} href="/cards?add=1" variant="contained" startIcon={<AddRoundedIcon />}>
        Karte hinzufügen
      </Button>
      <Button component={Link} href="/set-import" variant="outlined" startIcon={<LayersRoundedIcon />}>
        Display erfassen
      </Button>
      {stats.distinct_items > 0 ? (
        <Button variant="text" startIcon={<RefreshRoundedIcon />} onClick={() => void refreshAllPrices()} disabled={Boolean(refreshJob)}>
          Alle Preise aktualisieren
        </Button>
      ) : null}
    </Stack>
  );

  if (stats.distinct_items === 0) {
    return (
      <Stack spacing={3}>
        <PageHeader title="Willkommen" description="Deine Sammlung ist noch leer. Leg los mit einer einzelnen Karte oder einem ganzen Display." action={actions} />
      </Stack>
    );
  }

  const history = stats.value_history;
  const firstValue = history.find((point) => point.total_value > 0)?.total_value ?? null;
  const valueChange = firstValue ? ((stats.total_value - firstValue) / firstValue) * 100 : null;
  const pricedShare = Math.round((stats.priced_cards / stats.distinct_items) * 100);
  const balance = stats.purchase_value > 0 ? stats.purchase_value_market - stats.purchase_value : null;
  const attentionCount = stats.missing_price_count + stats.uncertain_price_count + stats.stale_price_count + stats.failed_jobs_count;
  const movers = moversTab === 'up' ? stats.top_gainers : stats.top_losers;

  return (
    <Stack spacing={3}>
      <PageHeader title="Übersicht" description="Wert und Entwicklung deiner Sammlung auf einen Blick." action={actions} />

      {refreshJob ? (
        <Alert severity="info" onClose={() => setRefreshJob(null)} action={<Button color="inherit" size="small" component={Link} href="/sync-status">Status</Button>}>
          Preisupdate für alle Karten gestartet. Es läuft im Hintergrund weiter.
        </Alert>
      ) : null}
      {refreshError ? <Alert severity="error" onClose={() => setRefreshError(null)}>{refreshError}</Alert> : null}

      <Grid container spacing={2.5}>
        <Grid item xs={12} sm={6} lg={3}>
          <StatCard
            label="Sammlungswert"
            value={formatCurrency(stats.total_value, currency)}
            sublabel="Aktueller Marktwert"
            trend={valueChange !== null ? `${formatPercent(valueChange)} / 14 T.` : undefined}
            accent={(valueChange || 0) >= 0 ? 'success' : 'error'}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <StatCard label="Karten" value={stats.total_cards.toString()} sublabel={`${stats.distinct_items} verschiedene Positionen`} accent="secondary" />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <StatCard
            label="Bilanz ggü. Einkauf"
            value={balance !== null ? `${balance >= 0 ? '+' : ''}${formatCurrency(balance, currency)}` : '–'}
            sublabel={stats.purchase_value > 0 ? `Einkauf ${formatCurrency(stats.purchase_value, currency)}` : 'Noch keine Einkaufspreise erfasst'}
            accent={(balance || 0) >= 0 ? 'success' : 'error'}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <StatCard
            label="Preisabdeckung"
            value={`${pricedShare}%`}
            sublabel={`${stats.priced_cards} von ${stats.distinct_items} Positionen mit Preis`}
            accent={pricedShare >= 90 ? 'success' : 'warning'}
          />
        </Grid>
      </Grid>

      <Grid container spacing={2.5}>
        <Grid item xs={12} lg={8}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Wertverlauf (14 Tage)
            </Typography>
            <Box sx={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history}>
                  <defs>
                    <linearGradient id="valueFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#d8a94c" stopOpacity={0.5} />
                      <stop offset="100%" stopColor="#d8a94c" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="date" stroke="#8ea092" tickFormatter={(value: string) => value.slice(8, 10) + '.' + value.slice(5, 7) + '.'} />
                  <YAxis stroke="#8ea092" width={80} tickFormatter={(value) => formatCurrency(Number(value), currency)} />
                  <Tooltip formatter={(value) => formatCurrency(Number(value), currency)} />
                  <Area type="monotone" dataKey="total_value" name="Wert" stroke="#d8a94c" strokeWidth={3} fill="url(#valueFill)" />
                </AreaChart>
              </ResponsiveContainer>
            </Box>
          </Paper>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Braucht Aufmerksamkeit
            </Typography>
            {attentionCount ? (
              <List disablePadding>
                <AttentionRow count={stats.missing_price_count} label="Positionen ohne Preis" href="/cards?has_price=no" />
                <AttentionRow count={stats.uncertain_price_count} label="Preise nur als Kartenpreis (Print nicht exakt)" href="/cards" />
                <AttentionRow count={stats.stale_price_count} label="Preise älter als 30 Tage" href="/cards" />
                <AttentionRow count={stats.failed_jobs_count} label="fehlgeschlagene Hintergrundjobs (7 Tage)" href="/sync-status" />
              </List>
            ) : (
              <Stack direction="row" spacing={1.5} alignItems="center" sx={{ p: 1.5 }}>
                <CheckCircleRoundedIcon color="success" />
                <Typography>Alles in Ordnung.</Typography>
              </Stack>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Wertvollste Karten
            </Typography>
            {stats.most_valuable_cards.length ? (
              <List disablePadding>
                {stats.most_valuable_cards.map((item) => (
                  <CardRow
                    key={item.inventory_item_id}
                    item={item}
                    right={
                      <>
                        <Typography fontWeight={800}>{formatCurrency((item.current_market_price || 0) * item.quantity, currency)}</Typography>
                        {item.quantity > 1 ? (
                          <Typography variant="body2" color="text.secondary">
                            {formatCurrency(item.current_market_price, currency)} / Stk.
                          </Typography>
                        ) : null}
                      </>
                    }
                  />
                ))}
              </List>
            ) : (
              <EmptyHint>Noch keine Karten mit Preis.</EmptyHint>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="h6">Preisbewegungen (7 Tage)</Typography>
              <Tabs value={moversTab} onChange={(_, value) => setMoversTab(value)} sx={{ minHeight: 0 }}>
                <Tab value="up" label="Gewinner" sx={{ minHeight: 0, py: 1 }} />
                <Tab value="down" label="Verlierer" sx={{ minHeight: 0, py: 1 }} />
              </Tabs>
            </Stack>
            {movers.length ? (
              <List disablePadding>
                {movers.map((item) => (
                  <CardRow
                    key={item.inventory_item_id}
                    item={item}
                    right={
                      <>
                        <Typography fontWeight={800} color={(item.price_change_7d || 0) >= 0 ? 'success.main' : 'error.main'}>
                          {formatPercent(item.price_change_7d)}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {formatCurrency(item.current_market_price, currency)}
                        </Typography>
                      </>
                    }
                  />
                ))}
              </List>
            ) : (
              <EmptyHint>{moversTab === 'up' ? 'Keine Preissteigerungen in den letzten 7 Tagen.' : 'Keine Preisrückgänge in den letzten 7 Tagen.'}</EmptyHint>
            )}
          </Paper>
        </Grid>
      </Grid>
    </Stack>
  );
}
