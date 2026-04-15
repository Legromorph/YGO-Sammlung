import { useEffect, useMemo, useState } from 'react';
import ReplayRoundedIcon from '@mui/icons-material/ReplayRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Grid,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import api, { getApiErrorMessage } from '../lib/api';
import { formatDate } from '../lib/format';
import { SyncJob, SyncOverview } from '../lib/types';

const jobTypes = [
  { key: 'price_update', label: 'Preisupdate' },
  { key: 'image_sync', label: 'Bildsync' },
  { key: 'trend_rebuild', label: 'Trend-Rebuild' },
  { key: 'card_data_sync', label: 'Kartendaten-Sync' },
];

function statusColor(status: string): 'success' | 'error' | 'warning' | 'info' | 'default' {
  if (status === 'completed') {
    return 'success';
  }
  if (status === 'failed') {
    return 'error';
  }
  if (status === 'running') {
    return 'info';
  }
  return 'warning';
}

function progressValue(job: SyncJob): number | null {
  if (!job.total_items || job.total_items <= 0) {
    return null;
  }
  const processed = Math.max(0, job.processed_items || 0);
  return Math.max(0, Math.min(100, (processed / job.total_items) * 100));
}

function hasActiveProgress(job: SyncJob): boolean {
  return job.status === 'running' || job.status === 'pending';
}

export default function SyncStatusPage() {
  const [overview, setOverview] = useState<SyncOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [triggeringJob, setTriggeringJob] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [error, setError] = useState<string | null>(null);

  const load = async (showRefreshState = false) => {
    if (!overview) {
      setLoading(true);
    }
    if (showRefreshState) {
      setRefreshing(true);
    }
    try {
      const response = await api.get<SyncOverview>('/sync/');
      setOverview(response.data);
      setError(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void load();
    }, 5000);

    return () => {
      window.clearInterval(interval);
    };
  }, []);

  const trigger = async (jobType: string) => {
    setTriggeringJob(jobType);
    try {
      await api.post('/sync/jobs', { job_type: jobType, force: false, payload: { trigger: 'manual' } });
      await load(true);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setTriggeringJob(null);
    }
  };

  const retry = async (jobId: number) => {
    setRetryingJobId(jobId);
    try {
      await api.post(`/sync/jobs/${jobId}/retry`);
      await load(true);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setRetryingJobId(null);
    }
  };

  const filteredJobs = useMemo(() => {
    const jobs = overview?.jobs || [];
    if (statusFilter === 'all') {
      return jobs;
    }
    return jobs.filter((job) => job.status === statusFilter);
  }, [overview?.jobs, statusFilter]);

  const stuckJobs = useMemo(
    () => (overview?.jobs || []).filter((job) => job.is_stuck),
    [overview?.jobs],
  );

  if (loading && !overview) {
    return <CircularProgress />;
  }

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 3 }}>
        <Stack direction={{ xs: 'column', lg: 'row' }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography variant="h4">Sync-Status & Jobs</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.75 }}>
              Manuelle Jobstarts, Provider-Status und die aktuelle Worker-Ausfuehrung auf Basis von `sync_jobs`.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            startIcon={refreshing ? <CircularProgress size={16} color="inherit" /> : <ReplayRoundedIcon />}
            onClick={() => void load(true)}
            disabled={refreshing}
          >
            Aktualisieren
          </Button>
        </Stack>
      </Paper>

      {error ? <Alert severity="error">{error}</Alert> : null}
      {stuckJobs.length > 0 ? (
        <Alert severity="warning">
          {stuckJobs.length} Job(s) wirken auffaellig: {stuckJobs.map((job) => `#${job.id} ${job.stuck_reason || job.status}`).join(', ')}
        </Alert>
      ) : null}

      <Grid container spacing={2.5}>
        {(overview?.providers || []).map((provider) => (
          <Grid item xs={12} md={6} xl={3} key={`${provider.category}-${provider.key}`}>
            <Paper sx={{ p: 2.5, height: '100%' }}>
              <Typography variant="overline" color="primary.light">
                {provider.category}
              </Typography>
              <Typography variant="h6">{provider.label}</Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap' }}>
                <Chip label={provider.active ? 'aktiv' : 'inaktiv'} color={provider.active ? 'success' : 'default'} variant="outlined" />
                <Chip label={provider.available ? 'verfuegbar' : 'begrenzt'} color={provider.available ? 'secondary' : 'warning'} variant="outlined" />
              </Stack>
              <Typography color="text.secondary" sx={{ mt: 1.5 }}>
                {provider.notes}
              </Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>

      <Paper sx={{ p: 2.5 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Jobs starten
        </Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
          {jobTypes.map((job) => (
            <Button
              key={job.key}
              variant="contained"
              startIcon={<SyncRoundedIcon />}
              disabled={triggeringJob === job.key}
              onClick={() => void trigger(job.key)}
            >
              {triggeringJob === job.key ? 'Starte...' : job.label}
            </Button>
          ))}
        </Stack>
      </Paper>

      <Paper sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} justifyContent="space-between">
          <Box>
            <Typography variant="h6">Jobliste</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Sichtbar sind aktuelle Joblaeufe inklusive Retry fuer fehlgeschlagene Preisjobs.
            </Typography>
          </Box>
          <TextField
            select
            label="Statusfilter"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="all">Alle</MenuItem>
            <MenuItem value="pending">Pending</MenuItem>
            <MenuItem value="running">Running</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
            <MenuItem value="failed">Failed</MenuItem>
          </TextField>
        </Stack>
      </Paper>

      <Paper sx={{ overflow: 'hidden' }}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Job</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Provider</TableCell>
              <TableCell>Fortschritt</TableCell>
              <TableCell>Erstellt</TableCell>
              <TableCell>Abschluss</TableCell>
              <TableCell>Hinweis</TableCell>
              <TableCell align="right">Aktion</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filteredJobs.map((job: SyncJob) => (
              <TableRow key={job.id}>
                <TableCell>
                  <Stack spacing={0.5}>
                    <Typography fontWeight={700}>#{job.id} {job.job_type}</Typography>
                    {job.payload?.['trigger'] ? (
                      <Typography variant="body2" color="text.secondary">
                        Trigger: {String(job.payload['trigger'])}
                      </Typography>
                    ) : null}
                  </Stack>
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip label={job.status} size="small" color={statusColor(job.status)} variant="outlined" />
                    {job.is_stuck ? <Chip label="auffaellig" size="small" color="warning" variant="outlined" /> : null}
                  </Stack>
                </TableCell>
                <TableCell>{job.provider_key || 'internal'}</TableCell>
                <TableCell sx={{ minWidth: 220 }}>
                  {progressValue(job) !== null ? (
                    <Stack spacing={0.6}>
                      <LinearProgress variant="determinate" value={progressValue(job) || 0} />
                      <Typography variant="body2" color="text.secondary">
                        {(job.processed_items || 0)} / {job.total_items || 0}
                        {job.rate_limit_per_minute ? ` | ${job.rate_limit_per_minute}/min` : ''}
                      </Typography>
                    </Stack>
                  ) : hasActiveProgress(job) ? (
                    <Stack spacing={0.6}>
                      <LinearProgress />
                      <Typography variant="body2" color="text.secondary">
                        Wird vorbereitet...
                      </Typography>
                    </Stack>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      n/a
                    </Typography>
                  )}
                </TableCell>
                <TableCell>{formatDate(job.created_at)}</TableCell>
                <TableCell>{formatDate(job.completed_at || job.started_at || null)}</TableCell>
                <TableCell>{job.error_message || job.stuck_reason || job.log_excerpt || 'n/a'}</TableCell>
                <TableCell align="right">
                  {job.can_retry ? (
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={retryingJobId === job.id ? <CircularProgress size={14} color="inherit" /> : <ReplayRoundedIcon />}
                      disabled={retryingJobId === job.id}
                      onClick={() => void retry(job.id)}
                    >
                      Retry
                    </Button>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      -
                    </Typography>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Stack>
  );
}
