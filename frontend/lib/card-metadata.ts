import { CanonicalCardKind } from './types';

export type CardMetadataKey =
  | 'card_type'
  | 'subtype'
  | 'spell_trap_type'
  | 'attribute'
  | 'monster_type'
  | 'archetype'
  | 'atk'
  | 'defense'
  | 'level'
  | 'rank'
  | 'link_rating'
  | 'pendulum_scale';

const monsterOnlyFields = new Set<CardMetadataKey>([
  'attribute',
  'monster_type',
  'atk',
  'defense',
  'level',
  'rank',
  'link_rating',
  'pendulum_scale',
]);

const spellTrapOnlyFields = new Set<CardMetadataKey>(['spell_trap_type']);

const cardTypeLabels: Record<string, string> = {
  'Spell Card': 'Zauberkarte',
  'Trap Card': 'Fallenkarte',
  'Normal Monster': 'Normalmonster',
  'Effect Monster': 'Effektmonster',
  'Fusion Monster': 'Fusionsmonster',
  'Synchro Monster': 'Synchromonster',
  'XYZ Monster': 'Xyz-Monster',
  'Xyz Monster': 'Xyz-Monster',
  'Link Monster': 'Linkmonster',
  'Ritual Monster': 'Ritualmonster',
  'Pendulum Effect Monster': 'Pendel-Effektmonster',
  'Pendulum Normal Monster': 'Pendel-Normalmonster',
};

const sharedSpellTrapLabels: Record<string, string> = {
  quick_play: 'Schnellzauber',
  equip: 'Ausrüstungszauber',
  field: 'Spielfeldzauber',
  ritual: 'Ritualzauber',
  counter: 'Konterfalle',
};

export function canonicalCardKindFromType(cardType?: string | null): CanonicalCardKind {
  const normalized = (cardType || '').toLowerCase();
  if (normalized.includes('spell')) return 'spell';
  if (normalized.includes('trap')) return 'trap';
  if (normalized.includes('skill')) return 'skill';
  if (normalized.includes('token')) return 'token';
  if (normalized.includes('monster')) return 'monster';
  return 'other';
}

export function cardTypeLabel(value?: string | null): string {
  if (!value) return '';
  return cardTypeLabels[value] || value;
}

export function spellTrapTypeLabel(value: string | null | undefined, kind: CanonicalCardKind): string {
  if (!value) return '';
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  if (sharedSpellTrapLabels[normalized]) {
    return sharedSpellTrapLabels[normalized];
  }
  if (normalized === 'normal') {
    return kind === 'trap' ? 'Normale Falle' : 'Normalzauber';
  }
  if (normalized === 'continuous') {
    return kind === 'trap' ? 'Permanente Fallenkarte' : 'Permanente Zauberkarte';
  }
  return value;
}

export function metadataFieldAllowed(kind: CanonicalCardKind, key: CardMetadataKey): boolean {
  if (monsterOnlyFields.has(key)) {
    return kind === 'monster';
  }
  if (spellTrapOnlyFields.has(key)) {
    return kind === 'spell' || kind === 'trap';
  }
  return true;
}

export function metadataFieldLabel(key: CardMetadataKey, kind: CanonicalCardKind): string {
  if (key === 'spell_trap_type') {
    return kind === 'trap' ? 'Fallenkartentyp' : 'Zauberkartentyp';
  }
  const labels: Record<CardMetadataKey, string> = {
    card_type: 'Kartentyp',
    subtype: 'Untertyp',
    spell_trap_type: 'Zauber-/Fallentyp',
    attribute: 'Attribut',
    monster_type: 'Monster-Typ',
    archetype: 'Archetyp',
    atk: 'ATK',
    defense: 'DEF',
    level: 'Level',
    rank: 'Rang',
    link_rating: 'Linkwert',
    pendulum_scale: 'Pendel-Skala',
  };
  return labels[key];
}
