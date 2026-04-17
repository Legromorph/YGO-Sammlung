export interface StorageLocation {
  id: number;
  name: string;
  code?: string | null;
  location_type: string;
  description?: string | null;
  position_label?: string | null;
  parent_id?: number | null;
  path_cache: string;
  card_count: number;
  total_value: number;
  display_currency: string;
}

export interface AppSettings {
  preferred_currency: 'EUR' | 'USD' | string;
  preferred_card_language: string;
  preferred_search_language: string;
  preferred_price_language: string;
  created_at?: string;
  updated_at?: string;
}

export interface PriceHistoryPoint {
  captured_at: string;
  price: number;
  currency: string;
  metric: string;
  provider_key: string;
  match_quality?: string | null;
  note?: string | null;
  source_url?: string | null;
  source_product_id?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  language?: string | null;
  lowest_offer_price?: number | null;
  selected_market_price?: number | null;
  market_price_median_top5?: number | null;
  pricing_strategy_used?: string | null;
  offer_count_considered?: number | null;
  offers_considered_count?: number | null;
  outlier_detected?: boolean | null;
  price_trend?: number | null;
  avg_1d?: number | null;
  avg_7d?: number | null;
  avg_30d?: number | null;
  filters_used?: Record<string, unknown> | null;
  parse_status?: string | null;
  top5_offer_prices?: number[];
  raw_offer_prices_sample?: number[];
}

export interface SourceMapping {
  provider_key: string;
  external_id: string;
  external_url?: string | null;
  last_synced_at?: string | null;
}

export interface PricingStatus {
  status: string;
  is_updating: boolean;
  pending_job_id?: number | null;
  match_quality?: string | null;
  source?: string | null;
  note?: string | null;
  last_updated_at?: string | null;
  cardmarket_url?: string | null;
  cardmarket_link_mode?: string | null;
  last_price_check_at?: string | null;
  next_price_check_at?: string | null;
  price_check_interval_hours?: number | null;
  price_volatility_score?: number | null;
  price_check_priority?: number | null;
  price_stability_state?: string | null;
  failure_count?: number | null;
  consecutive_stable_checks?: number | null;
  last_error_message?: string | null;
  pending_job?: SyncJobResponse | null;
}

export interface SyncJobResponse {
  id: number;
  job_type: string;
  provider_key?: string | null;
  status: string;
  available_at?: string | null;
  priority?: number;
  payload?: Record<string, unknown> | null;
  log_excerpt?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  is_stuck?: boolean;
  stuck_reason?: string | null;
  can_retry?: boolean;
  // Progress tracking
  total_items?: number | null;
  processed_items?: number | null;
  successful_items?: number | null;
  failed_items?: number | null;
  next_scheduled_item_at?: string | null;
  rate_limit_per_minute?: number | null;
}

export interface CardLookupSuggestion {
  external_id: string;
  name: string;
  card_type?: string | null;
  attribute?: string | null;
  monster_type?: string | null;
  image_url?: string | null;
  set_count: number;
  default_market_price?: number | null;
  default_price_currency?: string | null;
  price_source?: string | null;
}

export interface CardLookupPrintOption {
  set_name?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  rarity_code?: string | null;
  cardmarket_product_url?: string | null;
  cardmarket_product_slug?: string | null;
  cardmarket_set_slug?: string | null;
  cardmarket_set_name?: string | null;
  cardmarket_product_name?: string | null;
  cardmarket_variant_name?: string | null;
  cardmarket_category?: string | null;
  cardmarket_match_quality?: string | null;
  cardmarket_verified_at?: string | null;
  market_price?: number | null;
  price_currency?: string | null;
  price_source?: string | null;
  price_note?: string | null;
  cardmarket_reference?: string | null;
  ygoprodeck_id?: string | null;
  display_label: string;
}

export interface CardLookupResponse {
  external_id: string;
  name: string;
  effect_text?: string | null;
  card_type?: string | null;
  subtype?: string | null;
  attribute?: string | null;
  monster_type?: string | null;
  archetype?: string | null;
  atk?: number | null;
  defense?: number | null;
  level?: number | null;
  rank?: number | null;
  link_rating?: number | null;
  link_arrows: string[];
  pendulum_scale?: number | null;
  pendulum_effect?: string | null;
  spell_trap_type?: string | null;
  image_url?: string | null;
  ygoprodeck_id?: string | null;
  default_market_price?: number | null;
  default_price_currency?: string | null;
  price_source?: string | null;
  price_note: string;
  condition_price_supported: boolean;
  cardmarket_reference?: string | null;
  print_options: CardLookupPrintOption[];
  cardmarket_product_url?: string | null;
  cardmarket_product_slug?: string | null;
  cardmarket_set_slug?: string | null;
  cardmarket_set_name?: string | null;
  cardmarket_product_name?: string | null;
  cardmarket_variant_name?: string | null;
  cardmarket_category?: string | null;
  cardmarket_match_quality?: string | null;
  cardmarket_verified_at?: string | null;
}

export interface CardSummary {
  id: number;
  card_id: number;
  card_print_id: number;
  name: string;
  language: string;
  set_name?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  condition: string;
  quantity: number;
  purchase_price?: number | null;
  current_market_price?: number | null;
  current_price_currency: string;
  total_value: number;
  price_change_7d?: number | null;
  price_change_30d?: number | null;
  trend_score?: number | null;
  card_type?: string | null;
  attribute?: string | null;
  monster_type?: string | null;
  atk?: number | null;
  defense?: number | null;
  level?: number | null;
  rank?: number | null;
  link_rating?: number | null;
  storage_location_id?: number | null;
  storage_location_name?: string | null;
  storage_path?: string | null;
  has_image: boolean;
  has_price: boolean;
  image_url: string;
  last_priced_at?: string | null;
  last_price_source?: string | null;
  last_price_match_quality?: string | null;
  last_price_note?: string | null;
  pricing: PricingStatus;
  notes?: string | null;
  updated_at: string;
}

export interface CardDetail extends CardSummary {
  effect_text?: string | null;
  subtype?: string | null;
  archetype?: string | null;
  spell_trap_type?: string | null;
  rarity_code?: string | null;
  edition?: string | null;
  release_date?: string | null;
  cardmarket_reference?: string | null;
  cardmarket_product_url?: string | null;
  cardmarket_product_slug?: string | null;
  cardmarket_set_slug?: string | null;
  cardmarket_set_name?: string | null;
  cardmarket_product_name?: string | null;
  cardmarket_variant_name?: string | null;
  cardmarket_category?: string | null;
  cardmarket_match_quality?: string | null;
  cardmarket_verified_at?: string | null;
  cardmarket_expected_rarity?: string | null;
  cardmarket_expected_language?: string | null;
  cardmarket_expected_set_name?: string | null;
  tags: string[];
  link_arrows: string[];
  pendulum_scale?: number | null;
  pendulum_effect?: string | null;
  price_history: PriceHistoryPoint[];
  source_mappings: SourceMapping[];
}

export interface CardListResponse {
  items: CardSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface CardFilterOptions {
  rarities: string[];
  conditions: string[];
  card_types: string[];
  attributes: string[];
  monster_types: string[];
  storage_locations: StorageLocation[];
}

export interface CardSetSummary {
  id: number;
  provider_key: string;
  name: string;
  set_code?: string | null;
  card_count: number;
  expected_card_count: number;
  loaded_card_count: number;
  loaded_print_count: number;
  is_complete: boolean;
  warning?: string | null;
  release_date?: string | null;
  last_synced_at?: string | null;
}

export interface SetCardRow {
  card_print_id: number;
  card_id: number;
  name: string;
  language: string;
  card_number?: string | null;
  set_code?: string | null;
  rarity?: string | null;
  card_type?: string | null;
  image_url: string;
  existing_quantity: number;
  current_market_price?: number | null;
  current_price_currency?: string | null;
}

export interface SetCardsResponse {
  set: CardSetSummary;
  items: SetCardRow[];
}

export interface BulkSetImportLinePayload {
  card_print_id: number;
  quantity: number;
}

export interface BulkSetImportPayload {
  set_id: number;
  display_total_price: number;
  currency: string;
  storage_location_id?: number | null;
  condition: string;
  language: string;
  notes?: string | null;
  items: BulkSetImportLinePayload[];
}

export interface BulkSetImportAllocationLine {
  inventory_item_id: number;
  card_print_id: number;
  quantity: number;
  allocated_purchase_price_per_unit?: number | null;
  allocated_purchase_total: number;
}

export interface BulkSetImportResponse {
  purchase_batch_id: number;
  created_items: number;
  merged_items: number;
  imported_lines: number;
  total_quantity: number;
  imported_inventory_item_ids: number[];
  imported_card_print_ids: number[];
  display_total_price: number;
  purchase_batch_total_price: number;
  currency: string;
  allocated_unit_price?: number | null;
  total_allocated_price: number;
  allocation_difference: number;
  allocation_lines: BulkSetImportAllocationLine[];
  rounding_remainder_cents: number;
  price_sync_job?: SyncJob | null;
  price_sync_job_error?: string | null;
}

export interface CardPayload {
  card_id?: number | null;
  card_print_id?: number | null;
  name: string;
  language: string;
  set_name?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  rarity_code?: string | null;
  edition?: string | null;
  release_date?: string | null;
  condition: string;
  quantity: number;
  purchase_price?: number | null;
  current_market_price?: number | null;
  current_price_currency: string;
  storage_location_id?: number | null;
  cardmarket_reference?: string | null;
  cardmarket_product_url?: string | null;
  cardmarket_product_slug?: string | null;
  cardmarket_set_slug?: string | null;
  cardmarket_set_name?: string | null;
  cardmarket_product_name?: string | null;
  cardmarket_variant_name?: string | null;
  cardmarket_category?: string | null;
  cardmarket_match_quality?: string | null;
  cardmarket_verified_at?: string | null;
  cardmarket_expected_rarity?: string | null;
  cardmarket_expected_language?: string | null;
  cardmarket_expected_set_name?: string | null;
  notes?: string | null;
  tags: string[];
  external_ids: Record<string, string>;
  effect_text?: string | null;
  card_type?: string | null;
  subtype?: string | null;
  attribute?: string | null;
  monster_type?: string | null;
  archetype?: string | null;
  atk?: number | null;
  defense?: number | null;
  level?: number | null;
  rank?: number | null;
  link_rating?: number | null;
  link_arrows: string[];
  pendulum_scale?: number | null;
  pendulum_effect?: string | null;
  spell_trap_type?: string | null;
  increment_existing_quantity_on_duplicate?: boolean;
}

export interface DeckCardPayload {
  inventory_item_id?: number | null;
  quantity: number;
  section: string;
  is_missing: boolean;
  notes?: string | null;
}

export interface DeckCard {
  id: number;
  inventory_item_id?: number | null;
  card_print_id?: number | null;
  card_name: string;
  set_code?: string | null;
  section: string;
  quantity: number;
  is_missing: boolean;
  current_market_price?: number | null;
  total_price: number;
  notes?: string | null;
}

export interface DeckSummary {
  id: number;
  name: string;
  description?: string | null;
  format: string;
  card_count: number;
  total_value: number;
  display_currency: string;
  updated_at: string;
}

export interface DeckDetail extends DeckSummary {
  cards: DeckCard[];
}

export interface DeckPayload {
  name: string;
  description?: string | null;
  format: string;
  cards: DeckCardPayload[];
}

export interface CollectionCardPayload {
  inventory_item_id?: number | null;
  quantity: number;
  notes?: string | null;
}

export interface CollectionCard {
  id: number;
  inventory_item_id?: number | null;
  card_print_id?: number | null;
  card_name: string;
  set_code?: string | null;
  quantity: number;
  current_market_price?: number | null;
  total_price: number;
  notes?: string | null;
}

export interface CollectionSummary {
  id: number;
  name: string;
  description?: string | null;
  color?: string | null;
  card_count: number;
  total_value: number;
  display_currency: string;
  updated_at: string;
}

export interface CollectionDetail extends CollectionSummary {
  cards: CollectionCard[];
}

export interface CollectionPayload {
  name: string;
  description?: string | null;
  color?: string | null;
  cards: CollectionCardPayload[];
}

export interface DashboardTrendItem {
  inventory_item_id: number;
  card_id: number;
  card_print_id: number;
  name: string;
  set_name?: string | null;
  set_code?: string | null;
  card_number?: string | null;
  rarity?: string | null;
  language?: string | null;
  image_url?: string | null;
  storage_path?: string | null;
  current_market_price?: number | null;
  current_price_currency?: string | null;
  price_change_7d?: number | null;
  price_change_30d?: number | null;
  trend_score?: number | null;
  quantity: number;
  last_priced_at?: string | null;
  last_price_source?: string | null;
  last_price_match_quality?: string | null;
  review_reasons?: string[];
}

export interface DashboardValuePoint {
  date: string;
  total_value: number;
  display_currency: string;
}

export interface SyncJob {
  id: number;
  job_type: string;
  provider_key?: string | null;
  status: string;
  available_at?: string | null;
  priority?: number;
  payload?: Record<string, unknown> | null;
  log_excerpt?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  is_stuck?: boolean;
  stuck_reason?: string | null;
  can_retry?: boolean;
  total_items?: number | null;
  processed_items?: number | null;
  successful_items?: number | null;
  failed_items?: number | null;
  next_scheduled_item_at?: string | null;
  rate_limit_per_minute?: number | null;
}

export interface DashboardResponse {
  total_cards: number;
  distinct_items: number;
  total_value: number;
  priced_cards: number;
  cards_with_images: number;
  value_history: DashboardValuePoint[];
  top_gainers: DashboardTrendItem[];
  top_losers: DashboardTrendItem[];
  trending_cards: DashboardTrendItem[];
  missing_price_cards: DashboardTrendItem[];
  review_candidates: DashboardTrendItem[];
  recent_price_updates: DashboardTrendItem[];
  recent_jobs: SyncJob[];
  display_currency: string;
}

export interface ProviderStatus {
  key: string;
  label: string;
  category: string;
  configured: boolean;
  available: boolean;
  active: boolean;
  notes: string;
}

export interface SyncOverview {
  providers: ProviderStatus[];
  jobs: SyncJob[];
}
