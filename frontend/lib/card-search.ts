export interface CardSearchOption {
  id: number;
  name: string;
  set_name?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  language?: string | null;
  image_url?: string | null;
  current_market_price?: number | null;
  current_price_currency?: string | null;
  storage_path?: string | null;
  quantity?: number | null;
  card_type?: string | null;
  attribute?: string | null;
  monster_type?: string | null;
}

export function cardSearchLabel(card: CardSearchOption): string {
  const meta = [card.set_name || card.set_code || null, card.card_number || null, card.rarity || null, card.language ? card.language.toUpperCase() : null].filter(
    Boolean,
  );
  return meta.length ? `${card.name} • ${meta.join(' • ')}` : card.name;
}
