import { Avatar, Box, Chip, Stack, Typography } from '@mui/material';

import { resolveMediaUrl } from '../lib/api';
import { formatCurrency } from '../lib/format';
import { formatCardPrintDescriptor, formatCardTypeDescriptor } from '../lib/card-display';
import { CardSearchOption } from '../lib/card-search';

interface CardSearchResultItemProps {
  card: CardSearchOption;
  compact?: boolean;
}

export default function CardSearchResultItem({ card, compact = false }: CardSearchResultItemProps) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="flex-start">
      <Avatar
        src={resolveMediaUrl(card.image_url) || undefined}
        variant="rounded"
        sx={{
          width: compact ? 40 : 44,
          height: compact ? 56 : 60,
          bgcolor: 'rgba(255,255,255,0.06)',
          flexShrink: 0,
        }}
      />
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography fontWeight={800} noWrap>
          {card.name}
        </Typography>
        <Typography variant="body2" color="text.secondary" noWrap>
          {formatCardTypeDescriptor(card) || 'Keine Typdaten'}
        </Typography>
        <Typography variant="body2" color="text.secondary" noWrap>
          {formatCardPrintDescriptor(card)}
        </Typography>
        <Stack direction="row" spacing={0.75} sx={{ mt: 0.9 }} flexWrap="wrap" useFlexGap>
          {card.storage_path ? <Chip label={card.storage_path} size="small" variant="outlined" /> : null}
          {card.quantity !== undefined && card.quantity !== null ? (
            <Chip label={`Bestand ${card.quantity}`} size="small" variant="outlined" />
          ) : null}
          {card.current_market_price !== null && card.current_market_price !== undefined ? (
            <Chip
              label={formatCurrency(card.current_market_price, card.current_price_currency || 'EUR')}
              size="small"
              color="secondary"
              variant="outlined"
            />
          ) : null}
        </Stack>
      </Box>
    </Stack>
  );
}
