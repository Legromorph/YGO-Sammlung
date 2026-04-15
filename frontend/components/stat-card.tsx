import { Box, Chip, Paper, Typography } from '@mui/material';

interface StatCardProps {
  label: string;
  value: string;
  sublabel?: string;
  trend?: string;
  accent?: 'primary' | 'secondary' | 'success' | 'warning' | 'error';
}

export default function StatCard({ label, value, sublabel, trend, accent = 'primary' }: StatCardProps) {
  return (
    <Paper
      sx={{
        p: 2.5,
        height: '100%',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00))',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Typography color="text.secondary">{label}</Typography>
        {trend ? <Chip size="small" label={trend} color={accent} variant="outlined" /> : null}
      </Box>
      <Typography variant="h4" sx={{ mt: 2, mb: 0.75 }}>
        {value}
      </Typography>
      {sublabel ? (
        <Typography variant="body2" color="text.secondary">
          {sublabel}
        </Typography>
      ) : null}
    </Paper>
  );
}
