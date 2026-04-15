from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrmSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AppSettingsPayload(BaseModel):
    preferred_currency: str = "EUR"
    preferred_card_language: str = "de"
    preferred_search_language: str = "de"
    preferred_price_language: str = "de"


class AppSettingsResponse(OrmSchema):
    id: int
    preferred_currency: str
    preferred_card_language: str
    preferred_search_language: str
    preferred_price_language: str
    created_at: datetime
    updated_at: datetime


class StorageLocationPayload(BaseModel):
    name: str
    code: str | None = None
    location_type: str = "other"
    description: str | None = None
    position_label: str | None = None
    parent_id: int | None = None


class StorageLocationResponse(OrmSchema):
    id: int
    name: str
    code: str | None = None
    location_type: str
    description: str | None = None
    position_label: str | None = None
    parent_id: int | None = None
    path_cache: str
    card_count: int = 0
    total_value: float = 0
    display_currency: str = "EUR"


class PriceHistoryPoint(BaseModel):
    captured_at: datetime
    price: float
    currency: str
    metric: str
    provider_key: str
    match_quality: str | None = None
    note: str | None = None
    source_url: str | None = None
    source_product_id: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    language: str | None = None
    lowest_offer_price: float | None = None
    selected_market_price: float | None = None
    pricing_strategy_used: str | None = None
    offer_count_considered: int | None = None
    outlier_detected: bool | None = None
    price_trend: float | None = None
    avg_1d: float | None = None
    avg_7d: float | None = None
    avg_30d: float | None = None
    filters_used: dict[str, Any] | None = None
    raw_offer_prices_sample: list[float] = Field(default_factory=list)


class SourceMappingResponse(OrmSchema):
    provider_key: str
    external_id: str
    external_url: str | None = None
    last_synced_at: datetime | None = None


class PricingStatus(BaseModel):
    status: str
    is_updating: bool = False
    pending_job_id: int | None = None
    match_quality: str | None = None
    source: str | None = None
    note: str | None = None
    last_updated_at: datetime | None = None
    cardmarket_url: str | None = None
    cardmarket_link_mode: str | None = None
    last_price_check_at: datetime | None = None
    next_price_check_at: datetime | None = None
    price_check_interval_hours: int | None = None
    price_volatility_score: float | None = None
    price_check_priority: int | None = None
    price_stability_state: str | None = None
    failure_count: int | None = None
    consecutive_stable_checks: int | None = None
    last_error_message: str | None = None
    pending_job: "SyncJobResponse | None" = None


class CardLookupSuggestion(BaseModel):
    external_id: str
    name: str
    card_type: str | None = None
    attribute: str | None = None
    monster_type: str | None = None
    image_url: str | None = None
    set_count: int = 0
    default_market_price: float | None = None
    default_price_currency: str | None = None
    price_source: str | None = None


class CardLookupPrintOption(BaseModel):
    set_name: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    rarity_code: str | None = None
    cardmarket_product_url: str | None = None
    cardmarket_product_slug: str | None = None
    cardmarket_set_slug: str | None = None
    cardmarket_set_name: str | None = None
    cardmarket_product_name: str | None = None
    cardmarket_variant_name: str | None = None
    cardmarket_category: str | None = None
    cardmarket_match_quality: str | None = None
    cardmarket_verified_at: datetime | None = None
    market_price: float | None = None
    price_currency: str | None = None
    price_source: str | None = None
    price_note: str | None = None
    cardmarket_reference: str | None = None
    ygoprodeck_id: str | None = None
    display_label: str


class CardLookupResponse(BaseModel):
    external_id: str
    name: str
    effect_text: str | None = None
    card_type: str | None = None
    subtype: str | None = None
    attribute: str | None = None
    monster_type: str | None = None
    archetype: str | None = None
    atk: int | None = None
    defense: int | None = None
    level: int | None = None
    rank: int | None = None
    link_rating: int | None = None
    link_arrows: list[str] = Field(default_factory=list)
    pendulum_scale: int | None = None
    pendulum_effect: str | None = None
    spell_trap_type: str | None = None
    image_url: str | None = None
    ygoprodeck_id: str | None = None
    default_market_price: float | None = None
    default_price_currency: str | None = None
    price_source: str | None = None
    price_note: str
    condition_price_supported: bool = False
    cardmarket_reference: str | None = None
    print_options: list[CardLookupPrintOption] = Field(default_factory=list)
    cardmarket_product_url: str | None = None
    cardmarket_product_slug: str | None = None
    cardmarket_set_slug: str | None = None
    cardmarket_set_name: str | None = None
    cardmarket_product_name: str | None = None
    cardmarket_variant_name: str | None = None
    cardmarket_category: str | None = None
    cardmarket_match_quality: str | None = None
    cardmarket_verified_at: datetime | None = None


class CardPayload(BaseModel):
    card_id: int | None = None
    card_print_id: int | None = None
    name: str
    language: str = "de"
    set_name: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    rarity_code: str | None = None
    edition: str | None = None
    release_date: date | None = None
    condition: str = "near_mint"
    quantity: int = Field(default=1, ge=1)
    purchase_price: float | None = Field(default=None, ge=0)
    current_market_price: float | None = Field(default=None, ge=0)
    current_price_currency: str = "EUR"
    storage_location_id: int | None = None
    cardmarket_reference: str | None = None
    cardmarket_product_url: str | None = None
    cardmarket_product_slug: str | None = None
    cardmarket_set_slug: str | None = None
    cardmarket_set_name: str | None = None
    cardmarket_product_name: str | None = None
    cardmarket_variant_name: str | None = None
    cardmarket_category: str | None = None
    cardmarket_match_quality: str | None = None
    cardmarket_verified_at: datetime | None = None
    cardmarket_expected_rarity: str | None = None
    cardmarket_expected_language: str | None = None
    cardmarket_expected_set_name: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    effect_text: str | None = None
    card_type: str | None = None
    subtype: str | None = None
    attribute: str | None = None
    monster_type: str | None = None
    archetype: str | None = None
    atk: int | None = None
    defense: int | None = None
    level: int | None = None
    rank: int | None = None
    link_rating: int | None = None
    link_arrows: list[str] = Field(default_factory=list)
    pendulum_scale: int | None = None
    pendulum_effect: str | None = None
    spell_trap_type: str | None = None


class CardSummary(BaseModel):
    id: int
    card_id: int
    card_print_id: int
    name: str
    language: str
    set_name: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    condition: str
    quantity: int
    purchase_price: float | None = None
    current_market_price: float | None = None
    current_price_currency: str
    total_value: float
    price_change_7d: float | None = None
    price_change_30d: float | None = None
    trend_score: float | None = None
    card_type: str | None = None
    attribute: str | None = None
    monster_type: str | None = None
    atk: int | None = None
    defense: int | None = None
    level: int | None = None
    rank: int | None = None
    link_rating: int | None = None
    storage_location_id: int | None = None
    storage_location_name: str | None = None
    storage_path: str | None = None
    has_image: bool
    has_price: bool
    image_url: str
    last_priced_at: datetime | None = None
    last_price_source: str | None = None
    last_price_match_quality: str | None = None
    last_price_note: str | None = None
    pricing: PricingStatus
    notes: str | None = None
    updated_at: datetime


class CardDetail(CardSummary):
    effect_text: str | None = None
    subtype: str | None = None
    archetype: str | None = None
    spell_trap_type: str | None = None
    rarity_code: str | None = None
    edition: str | None = None
    release_date: date | None = None
    cardmarket_reference: str | None = None
    cardmarket_product_url: str | None = None
    cardmarket_product_slug: str | None = None
    cardmarket_set_slug: str | None = None
    cardmarket_set_name: str | None = None
    cardmarket_product_name: str | None = None
    cardmarket_variant_name: str | None = None
    cardmarket_category: str | None = None
    cardmarket_match_quality: str | None = None
    cardmarket_verified_at: datetime | None = None
    cardmarket_expected_rarity: str | None = None
    cardmarket_expected_language: str | None = None
    cardmarket_expected_set_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    link_arrows: list[str] = Field(default_factory=list)
    pendulum_scale: int | None = None
    pendulum_effect: str | None = None
    price_history: list[PriceHistoryPoint] = Field(default_factory=list)
    source_mappings: list[SourceMappingResponse] = Field(default_factory=list)


class CardListResponse(BaseModel):
    items: list[CardSummary]
    total: int
    page: int
    page_size: int


class CardFilterOptions(BaseModel):
    rarities: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    card_types: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    monster_types: list[str] = Field(default_factory=list)
    storage_locations: list[StorageLocationResponse] = Field(default_factory=list)


class CardSetSummary(BaseModel):
    id: int
    provider_key: str
    name: str
    set_code: str | None = None
    card_count: int = 0
    expected_card_count: int = 0
    loaded_card_count: int = 0
    loaded_print_count: int = 0
    is_complete: bool = True
    warning: str | None = None
    release_date: date | None = None
    last_synced_at: datetime | None = None


class SetCardRow(BaseModel):
    card_print_id: int
    card_id: int
    name: str
    language: str
    card_number: str | None = None
    set_code: str | None = None
    rarity: str | None = None
    card_type: str | None = None
    image_url: str
    existing_quantity: int = 0
    current_market_price: float | None = None
    current_price_currency: str | None = None


class SetCardsResponse(BaseModel):
    set: CardSetSummary
    items: list[SetCardRow] = Field(default_factory=list)


class BulkSetImportLinePayload(BaseModel):
    card_print_id: int
    quantity: int = Field(default=0, ge=0)


class BulkSetImportPayload(BaseModel):
    set_id: int
    display_total_price: float = Field(ge=0)
    currency: str = "EUR"
    storage_location_id: int | None = None
    condition: str = "near_mint"
    language: str = "de"
    notes: str | None = None
    items: list[BulkSetImportLinePayload] = Field(default_factory=list)


class SyncJobResponse(BaseModel):
    id: int
    job_type: str
    provider_key: str | None = None
    status: str
    available_at: datetime | None = None
    priority: int = 0
    payload: dict | None = None
    log_excerpt: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    is_stuck: bool = False
    stuck_reason: str | None = None
    can_retry: bool = False
    # Progress tracking
    total_items: int | None = None
    processed_items: int | None = None
    successful_items: int | None = None
    failed_items: int | None = None
    next_scheduled_item_at: datetime | None = None
    rate_limit_per_minute: int | None = None


class BulkSetImportResponse(BaseModel):
    purchase_batch_id: int
    created_items: int
    merged_items: int
    imported_lines: int
    total_quantity: int
    imported_inventory_item_ids: list[int] = Field(default_factory=list)
    imported_card_print_ids: list[int] = Field(default_factory=list)
    display_total_price: float
    currency: str
    allocated_unit_price: float | None = None
    total_allocated_price: float
    rounding_remainder_cents: int = 0
    price_sync_job: SyncJobResponse | None = None
    price_sync_job_error: str | None = None


class DeckCardPayload(BaseModel):
    inventory_item_id: int | None = None
    quantity: int = Field(default=1, ge=1)
    section: str = "main"
    is_missing: bool = False
    notes: str | None = None


class DeckPayload(BaseModel):
    name: str
    description: str | None = None
    format: str = "Advanced"
    cards: list[DeckCardPayload] = Field(default_factory=list)


class DeckCardResponse(BaseModel):
    id: int
    inventory_item_id: int | None = None
    card_print_id: int | None = None
    card_name: str
    set_code: str | None = None
    section: str
    quantity: int
    is_missing: bool
    current_market_price: float | None = None
    total_price: float
    notes: str | None = None


class DeckSummary(BaseModel):
    id: int
    name: str
    description: str | None = None
    format: str
    card_count: int
    total_value: float
    display_currency: str = "EUR"
    updated_at: datetime


class DeckDetail(DeckSummary):
    cards: list[DeckCardResponse] = Field(default_factory=list)


class CollectionCardPayload(BaseModel):
    inventory_item_id: int | None = None
    quantity: int = Field(default=1, ge=1)
    notes: str | None = None


class CollectionPayload(BaseModel):
    name: str
    description: str | None = None
    color: str | None = None
    cards: list[CollectionCardPayload] = Field(default_factory=list)


class CollectionCardResponse(BaseModel):
    id: int
    inventory_item_id: int | None = None
    card_print_id: int | None = None
    card_name: str
    set_code: str | None = None
    quantity: int
    current_market_price: float | None = None
    total_price: float
    notes: str | None = None


class CollectionSummary(BaseModel):
    id: int
    name: str
    description: str | None = None
    color: str | None = None
    card_count: int
    total_value: float
    display_currency: str = "EUR"
    updated_at: datetime


class CollectionDetail(CollectionSummary):
    cards: list[CollectionCardResponse] = Field(default_factory=list)


class DashboardTrendItem(BaseModel):
    inventory_item_id: int
    card_id: int
    card_print_id: int
    name: str
    set_name: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    language: str | None = None
    image_url: str | None = None
    storage_path: str | None = None
    current_market_price: float | None = None
    current_price_currency: str | None = None
    price_change_7d: float | None = None
    price_change_30d: float | None = None
    trend_score: float | None = None
    quantity: int
    last_priced_at: datetime | None = None
    last_price_source: str | None = None
    last_price_match_quality: str | None = None
    review_reasons: list[str] = Field(default_factory=list)


class DashboardValuePoint(BaseModel):
    date: date
    total_value: float
    display_currency: str = "EUR"


class DashboardResponse(BaseModel):
    total_cards: int
    distinct_items: int
    total_value: float
    priced_cards: int
    cards_with_images: int
    value_history: list[DashboardValuePoint]
    top_gainers: list[DashboardTrendItem]
    top_losers: list[DashboardTrendItem]
    trending_cards: list[DashboardTrendItem]
    missing_price_cards: list[DashboardTrendItem]
    review_candidates: list[DashboardTrendItem]
    recent_price_updates: list[DashboardTrendItem]
    recent_jobs: list[SyncJobResponse]
    display_currency: str = "EUR"


class SyncJobPayload(BaseModel):
    job_type: str
    force: bool = False
    payload: dict | None = None


class ProviderStatus(BaseModel):
    key: str
    label: str
    category: str
    configured: bool
    available: bool
    active: bool
    notes: str


class SyncOverview(BaseModel):
    providers: list[ProviderStatus]
    jobs: list[SyncJobResponse]


class HealthResponse(BaseModel):
    status: str
    database: bool
    redis: bool
    image_directory: bool
    active_providers: dict[str, str]
