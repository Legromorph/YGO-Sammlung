import { List, ListItem, ListItemText } from '@mui/material';

import {
  CardMetadataKey,
  canonicalCardKindFromType,
  cardTypeLabel,
  metadataFieldAllowed,
  metadataFieldLabel,
  spellTrapTypeLabel,
} from '../lib/card-metadata';
import { CardDetail, CanonicalCardKind } from '../lib/types';

export interface CardMetadataRow {
  label: string;
  value: string;
}

const metadataKeys: CardMetadataKey[] = [
  'card_type',
  'subtype',
  'spell_trap_type',
  'attribute',
  'monster_type',
  'archetype',
  'atk',
  'defense',
  'level',
  'rank',
  'link_rating',
  'pendulum_scale',
];

function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined && value !== '';
}

function isRedundantSubtype(value: unknown, kind: CanonicalCardKind): boolean {
  const normalized = String(value || '').trim().toLowerCase();
  return normalized === kind || (kind === 'spell' && normalized === 'spell') || (kind === 'trap' && normalized === 'trap');
}

export function buildCardMetadataRows(card: CardDetail): CardMetadataRow[] {
  const kind = card.card_kind || canonicalCardKindFromType(card.card_type);
  const rows = metadataKeys
    .filter((key) => hasValue(card[key]) && metadataFieldAllowed(kind, key))
    .filter((key) => key !== 'subtype' || !isRedundantSubtype(card.subtype, kind))
    .map((key) => {
      const rawValue = card[key];
      const value =
        key === 'spell_trap_type'
          ? spellTrapTypeLabel(String(rawValue), kind)
          : key === 'card_type'
            ? cardTypeLabel(String(rawValue))
            : String(rawValue);
      return { label: metadataFieldLabel(key, kind), value };
    });

  if (kind === 'monster' && card.link_arrows.length) {
    rows.push({ label: 'Link-Pfeile', value: card.link_arrows.join(', ') });
  }
  if (card.edition) {
    rows.push({ label: 'Edition', value: card.edition });
  }
  if (card.release_date) {
    rows.push({ label: 'Veröffentlichung', value: card.release_date });
  }
  if (card.tags.length) {
    rows.push({ label: 'Tags', value: card.tags.join(', ') });
  }
  return rows;
}

export default function CardMetadataList({ card }: { card: CardDetail }) {
  const rows = buildCardMetadataRows(card);
  return (
    <List disablePadding>
      {rows.map((row, index) => (
        <ListItem
          key={row.label}
          disableGutters
          divider={index < rows.length - 1}
          sx={{ py: 1.15 }}
        >
          <ListItemText primary={row.label} secondary={row.value} />
        </ListItem>
      ))}
    </List>
  );
}
