import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CardDetail } from '../lib/types';
import CardMetadataList from './card-metadata-list';

function buildCard(overrides: Partial<CardDetail>): CardDetail {
  return {
    id: 1,
    card_id: 1,
    card_print_id: 1,
    name: 'Testkarte',
    language: 'de',
    condition: 'near_mint',
    quantity: 1,
    current_price_currency: 'EUR',
    total_value: 0,
    card_kind: 'other',
    has_image: false,
    has_price: false,
    image_url: '',
    pricing: { status: 'unpriced', is_updating: false },
    updated_at: '2026-07-28T00:00:00+00:00',
    tags: [],
    link_arrows: [],
    price_history: [],
    source_mappings: [],
    ...overrides,
  };
}

describe('CardMetadataList', () => {
  it('zeigt Schnellzauber und blendet unzulässige Monsterfelder aus', () => {
    render(
      <CardMetadataList
        card={buildCard({
          card_type: 'Spell Card',
          card_kind: 'spell',
          subtype: 'Spell',
          spell_trap_type: 'quick_play',
          monster_type: 'Quick-Play',
          attribute: 'SPELL',
          atk: 999,
          defense: 999,
        })}
      />,
    );

    expect(screen.getByText('Zauberkarte')).toBeInTheDocument();
    expect(screen.getByText('Zauberkartentyp')).toBeInTheDocument();
    expect(screen.getByText('Schnellzauber')).toBeInTheDocument();
    expect(screen.queryByText('Monster-Typ')).not.toBeInTheDocument();
    expect(screen.queryByText('ATK')).not.toBeInTheDocument();
    expect(screen.queryByText('Untertyp')).not.toBeInTheDocument();
  });

  it('zeigt kampfrelevante Werte bei Monstern', () => {
    render(
      <CardMetadataList
        card={buildCard({
          card_type: 'Effect Monster',
          card_kind: 'monster',
          monster_type: 'Spellcaster',
          attribute: 'DARK',
          atk: 2500,
          defense: 2100,
          level: 7,
        })}
      />,
    );

    expect(screen.getByText('Effektmonster')).toBeInTheDocument();
    expect(screen.getByText('Monster-Typ')).toBeInTheDocument();
    expect(screen.getByText('2500')).toBeInTheDocument();
    expect(screen.getByText('2100')).toBeInTheDocument();
  });
});
