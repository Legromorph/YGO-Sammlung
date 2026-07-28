import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CardPayload } from '../../lib/types';
import InventoryFields from './inventory-fields';

const form: CardPayload = {
  name: 'Book of Moon',
  language: 'de',
  condition: 'near_mint',
  quantity: 1,
  current_price_currency: 'EUR',
  tags: [],
  external_ids: {},
  link_arrows: [],
};

describe('InventoryFields', () => {
  it('markiert einen eingegebenen Marktpreis als manuell gepflegt', () => {
    const onUpdate = vi.fn();
    render(
      <InventoryFields
        visible
        form={form}
        hasLookup={false}
        storageLocations={[]}
        setCodeLanguageError={null}
        marketPriceHelperText=""
        tagText=""
        onLanguageChange={vi.fn()}
        onUpdate={onUpdate}
        onTagTextChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Marktpreis'), { target: { value: '2.75' } });

    expect(onUpdate).toHaveBeenCalledWith({
      current_market_price: 2.75,
      current_price_source: 'manual',
      current_price_match_quality: 'manual',
      current_price_note: 'Manuell gepflegter Marktpreis.',
    });
  });

  it('rendert keine Felder, solange die Druckvariante noch nicht feststeht', () => {
    render(
      <InventoryFields
        visible={false}
        form={form}
        hasLookup={false}
        storageLocations={[]}
        setCodeLanguageError={null}
        marketPriceHelperText=""
        tagText=""
        onLanguageChange={vi.fn()}
        onUpdate={vi.fn()}
        onTagTextChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText('Marktpreis')).not.toBeInTheDocument();
  });
});
