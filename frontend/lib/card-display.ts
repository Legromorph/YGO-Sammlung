type CardPrintDescriptorSource = {
  set_name?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  language?: string | null;
};
type CardTypeDescriptorSource = {
  card_type?: string | null;
  attribute?: string | null;
  monster_type?: string | null;
};

export function formatCardPrintDescriptor(card: CardPrintDescriptorSource): string {
  const parts = [card.set_name || card.set_code || 'Kein Set', card.card_number || null, card.rarity || null, card.language ? card.language.toUpperCase() : null].filter(
    Boolean,
  );
  return parts.join(' | ');
}

export function formatCardTypeDescriptor(card: CardTypeDescriptorSource): string {
  const parts = [card.card_type || null, card.attribute || null, card.monster_type || null].filter(Boolean);
  return parts.join(' | ');
}

export function formatCardQuantityDescriptor(quantity?: number | null): string {
  if (quantity === undefined || quantity === null) {
    return 'n/a';
  }
  return `${quantity}`;
}
