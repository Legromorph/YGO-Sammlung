import { ReactNode } from 'react';
import { Box, Paper, Typography } from '@mui/material';

interface PageHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export default function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <Paper
      sx={{
        p: { xs: 2.25, sm: 3 },
        display: 'flex',
        justifyContent: 'space-between',
        gap: 2,
        alignItems: 'center',
        flexWrap: 'wrap',
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h4">{title}</Typography>
        {description ? (
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>
            {description}
          </Typography>
        ) : null}
      </Box>
      {action}
    </Paper>
  );
}
