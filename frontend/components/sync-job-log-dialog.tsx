import { useEffect, useMemo, useState } from 'react';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

import api, { getApiErrorMessage } from '../lib/api';
import { formatDate } from '../lib/format';
import { SyncJob } from '../lib/types';

type SyncJobLogDialogProps = {
  open: boolean;
  job: SyncJob | null;
  onClose: () => void;
};

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

export default function SyncJobLogDialog({ open, job, onClose }: SyncJobLogDialogProps) {
  const [jobDetail, setJobDetail] = useState<SyncJob | null>(job);
  const [loading, setLoading] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setCopyState('idle');
      setError(null);
      return;
    }
    setJobDetail(job);
  }, [job, open]);

  useEffect(() => {
    if (!open || !job?.id) {
      return;
    }

    let active = true;
    const load = async () => {
      setLoading(true);
      try {
        const response = await api.get<SyncJob>(`/sync/jobs/${job.id}`);
        if (!active) {
          return;
        }
        setJobDetail(response.data);
        setError(null);
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, [job?.id, open]);

  useEffect(() => {
    if (!open || !jobDetail?.id || !['pending', 'running'].includes(jobDetail.status)) {
      return;
    }

    let active = true;
    const interval = window.setInterval(async () => {
      try {
        const response = await api.get<SyncJob>(`/sync/jobs/${jobDetail.id}`);
        if (!active) {
          return;
        }
        setJobDetail(response.data);
        setError(null);
      } catch (requestError) {
        if (active) {
          setError(getApiErrorMessage(requestError));
        }
      }
    }, 3000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [jobDetail?.id, jobDetail?.status, open]);

  const logText = useMemo(() => {
    if (jobDetail?.log_details?.trim()) {
      return jobDetail.log_details;
    }
    if (jobDetail?.error_message?.trim()) {
      return jobDetail.error_message;
    }
    if (jobDetail?.log_excerpt?.trim()) {
      return jobDetail.log_excerpt;
    }
    return 'Kein Detail-Log verfügbar.';
  }, [jobDetail?.error_message, jobDetail?.log_details, jobDetail?.log_excerpt]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(logText);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg">
      <DialogTitle sx={{ pb: 1.5 }}>
        <Stack direction="row" spacing={2} alignItems="flex-start" justifyContent="space-between">
          <Box>
            <Typography variant="h6">Job-Log #{jobDetail?.id || job?.id || 'n/a'}</Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
              <Chip
                label={jobDetail?.status || job?.status || 'unbekannt'}
                size="small"
                color={statusColor(jobDetail?.status || job?.status || 'pending')}
                variant="outlined"
              />
              <Chip label={jobDetail?.job_type || job?.job_type || 'job'} size="small" variant="outlined" />
              {jobDetail?.provider_key || job?.provider_key ? (
                <Chip label={jobDetail?.provider_key || job?.provider_key || 'provider'} size="small" variant="outlined" />
              ) : null}
            </Stack>
          </Box>
          <Tooltip title={copyState === 'copied' ? 'Komplettes Log kopiert' : copyState === 'failed' ? 'Kopieren fehlgeschlagen' : 'Komplettes Log kopieren'}>
            <span>
              <IconButton onClick={() => void handleCopy()} disabled={loading && !jobDetail} color={copyState === 'copied' ? 'success' : 'default'}>
                <ContentCopyRoundedIcon />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      </DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2}>
          {error ? <Alert severity="error">{error}</Alert> : null}
          {jobDetail?.error_message ? <Alert severity="error">{jobDetail.error_message}</Alert> : null}
          <Box sx={{ display: 'grid', gap: 1, gridTemplateColumns: { xs: '1fr', md: 'repeat(4, minmax(0, 1fr))' } }}>
            <Typography variant="body2" color="text.secondary">
              Erstellt: {formatDate(jobDetail?.created_at || job?.created_at || null)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Gestartet: {formatDate(jobDetail?.started_at || job?.started_at || null)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Abgeschlossen: {formatDate(jobDetail?.completed_at || job?.completed_at || null)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Fortschritt: {(jobDetail?.processed_items || job?.processed_items || 0)} / {(jobDetail?.total_items || job?.total_items || 0)}
            </Typography>
          </Box>
          {loading && !jobDetail ? (
            <Box sx={{ py: 6, display: 'grid', placeItems: 'center' }}>
              <CircularProgress />
            </Box>
          ) : (
            <TextField
              value={logText}
              fullWidth
              multiline
              minRows={18}
              maxRows={18}
              InputProps={{
                readOnly: true,
                sx: {
                  alignItems: 'flex-start',
                  '& textarea': {
                    fontFamily: 'Consolas, "Liberation Mono", Menlo, monospace',
                    fontSize: 13,
                    lineHeight: 1.5,
                    whiteSpace: 'pre',
                    overflow: 'auto !important',
                  },
                },
              }}
            />
          )}
        </Stack>
      </DialogContent>
    </Dialog>
  );
}
