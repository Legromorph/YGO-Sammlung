from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.card_metadata import CanonicalCardKind
from app.time_utils import utc_now


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Card(TimestampMixin, Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint(
            "card_kind IN ('monster', 'spell', 'trap', 'skill', 'token', 'other')",
            name="ck_cards_card_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    card_type: Mapped[str | None] = mapped_column(String(120))
    card_kind: Mapped[str] = mapped_column(String(20), default=CanonicalCardKind.OTHER.value, index=True)
    subtype: Mapped[str | None] = mapped_column(String(120))
    frame_type: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    attribute: Mapped[str | None] = mapped_column(String(50))
    monster_type: Mapped[str | None] = mapped_column(String(80))
    archetype: Mapped[str | None] = mapped_column(String(120))
    atk: Mapped[int | None] = mapped_column(Integer)
    defense: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[int | None] = mapped_column(Integer)
    rank: Mapped[int | None] = mapped_column(Integer)
    link_rating: Mapped[int | None] = mapped_column(Integer)
    link_arrows: Mapped[list[str] | None] = mapped_column(JSON)
    pendulum_scale: Mapped[int | None] = mapped_column(Integer)
    pendulum_effect: Mapped[str | None] = mapped_column(Text)
    spell_trap_type: Mapped[str | None] = mapped_column(String(80))
    limitations: Mapped[dict | None] = mapped_column(JSON)
    source_payload: Mapped[dict | None] = mapped_column(JSON)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    card_prints: Mapped[list["CardPrint"]] = relationship(back_populates="card", cascade="all, delete-orphan")


class CardSet(TimestampMixin, Base):
    __tablename__ = "card_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(80), index=True, default="ygoprodeck")
    name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    set_code: Mapped[str | None] = mapped_column(String(80), index=True)
    card_count: Mapped[int | None] = mapped_column(Integer)
    loaded_card_count: Mapped[int | None] = mapped_column(Integer)
    loaded_print_count: Mapped[int | None] = mapped_column(Integer)
    release_date: Mapped[date | None] = mapped_column(Date)
    source_payload: Mapped[dict | None] = mapped_column(JSON)
    sync_warning: Mapped[str | None] = mapped_column(Text)
    cardmarket_set_slug: Mapped[str | None] = mapped_column(String(255))
    cardmarket_set_name: Mapped[str | None] = mapped_column(String(255))
    cardmarket_aliases: Mapped[list[str] | None] = mapped_column(JSON)
    cardmarket_slug_match_quality: Mapped[str | None] = mapped_column(String(40))
    cardmarket_slug_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cards_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    card_prints: Mapped[list["CardPrint"]] = relationship(back_populates="card_set")
    purchase_batches: Mapped[list["PurchaseBatch"]] = relationship(back_populates="card_set")


class StorageLocation(TimestampMixin, Base):
    __tablename__ = "storage_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    code: Mapped[str | None] = mapped_column(String(80))
    location_type: Mapped[str] = mapped_column(String(50), index=True, default="other")
    description: Mapped[str | None] = mapped_column(Text)
    position_label: Mapped[str | None] = mapped_column(String(80))
    path_cache: Mapped[str] = mapped_column(String(500), default="")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("storage_locations.id", ondelete="SET NULL"))

    parent: Mapped["StorageLocation | None"] = relationship(remote_side="StorageLocation.id", back_populates="children")
    children: Mapped[list["StorageLocation"]] = relationship(back_populates="parent")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="storage_location")
    purchase_batches: Mapped[list["PurchaseBatch"]] = relationship(back_populates="storage_location")


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    preferred_currency: Mapped[str] = mapped_column(String(8), default="EUR")
    preferred_card_language: Mapped[str] = mapped_column(String(16), default="de")
    preferred_search_language: Mapped[str] = mapped_column(String(16), default="de,en")
    preferred_price_language: Mapped[str] = mapped_column(String(16), default="de")


class CardPrint(TimestampMixin, Base):
    __tablename__ = "card_prints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    set_id: Mapped[int | None] = mapped_column(ForeignKey("card_sets.id", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(16), default="de", index=True)
    set_name: Mapped[str | None] = mapped_column(String(255))
    set_code: Mapped[str | None] = mapped_column(String(80), index=True)
    card_number: Mapped[str | None] = mapped_column(String(80))
    rarity: Mapped[str | None] = mapped_column(String(120))
    rarity_code: Mapped[str | None] = mapped_column(String(80))
    edition: Mapped[str | None] = mapped_column(String(80))
    release_date: Mapped[date | None] = mapped_column(Date)
    remote_image_url: Mapped[str | None] = mapped_column(String(600))
    cardmarket_product_url: Mapped[str | None] = mapped_column(String(600))
    cardmarket_product_slug: Mapped[str | None] = mapped_column(String(255))
    cardmarket_set_slug: Mapped[str | None] = mapped_column(String(255))
    cardmarket_set_name: Mapped[str | None] = mapped_column(String(255))
    cardmarket_product_name: Mapped[str | None] = mapped_column(String(255))
    cardmarket_variant_name: Mapped[str | None] = mapped_column(String(255))
    cardmarket_category: Mapped[str | None] = mapped_column(String(80), default="Products/Singles")
    cardmarket_match_quality: Mapped[str | None] = mapped_column(String(40))
    cardmarket_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cardmarket_expected_rarity: Mapped[str | None] = mapped_column(String(120))
    cardmarket_expected_language: Mapped[str | None] = mapped_column(String(16))
    cardmarket_expected_set_name: Mapped[str | None] = mapped_column(String(255))

    card: Mapped[Card] = relationship(back_populates="card_prints")
    card_set: Mapped[CardSet | None] = relationship(back_populates="card_prints")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="card_print")
    image_assets: Mapped[list["ImageAsset"]] = relationship(back_populates="card_print", cascade="all, delete-orphan")


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_items_quantity_positive"),
        CheckConstraint("purchase_price IS NULL OR purchase_price >= 0", name="ck_inventory_items_purchase_price_nonnegative"),
        CheckConstraint(
            "allocated_purchase_total IS NULL OR allocated_purchase_total >= 0",
            name="ck_inventory_items_allocated_total_nonnegative",
        ),
        CheckConstraint(
            "current_market_price IS NULL OR current_market_price > 0",
            name="ck_inventory_items_market_price_positive",
        ),
        Index(
            "ix_inventory_items_print_condition_location",
            "card_print_id",
            "condition",
            "storage_location_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_print_id: Mapped[int] = mapped_column(ForeignKey("card_prints.id", ondelete="CASCADE"))
    storage_location_id: Mapped[int | None] = mapped_column(ForeignKey("storage_locations.id", ondelete="SET NULL"))
    purchase_batch_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_batches.id", ondelete="SET NULL"))
    condition: Mapped[str] = mapped_column(String(40), index=True, default="near_mint")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    allocated_purchase_total: Mapped[float | None] = mapped_column(Numeric(10, 2))
    current_market_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    current_price_currency: Mapped[str] = mapped_column(String(8), default="EUR")
    last_price_source: Mapped[str | None] = mapped_column(String(80))
    last_priced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_price_match_quality: Mapped[str | None] = mapped_column(String(40))
    last_price_note: Mapped[str | None] = mapped_column(Text)
    price_change_7d: Mapped[float | None] = mapped_column(default=0)
    price_change_30d: Mapped[float | None] = mapped_column(default=0)
    trend_score: Mapped[float | None] = mapped_column(default=0)
    cardmarket_reference: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(JSON)

    card_print: Mapped[CardPrint] = relationship(back_populates="inventory_items")
    storage_location: Mapped[StorageLocation | None] = relationship(back_populates="inventory_items")
    purchase_batch: Mapped["PurchaseBatch | None"] = relationship(back_populates="inventory_items")
    price_history: Mapped[list["PriceHistory"]] = relationship(back_populates="inventory_item", cascade="all, delete-orphan")
    price_monitor_state: Mapped["PriceMonitorState | None"] = relationship(
        back_populates="inventory_item",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
    )
    deck_cards: Mapped[list["DeckCard"]] = relationship(back_populates="inventory_item")
    collection_cards: Mapped[list["CollectionCard"]] = relationship(back_populates="inventory_item")
    purchase_batch_items: Mapped[list["PurchaseBatchItem"]] = relationship(back_populates="inventory_item")


class PurchaseBatch(TimestampMixin, Base):
    __tablename__ = "purchase_batches"
    __table_args__ = (
        CheckConstraint("total_price >= 0", name="ck_purchase_batches_total_price_nonnegative"),
        CheckConstraint("total_units >= 0", name="ck_purchase_batches_total_units_nonnegative"),
        CheckConstraint(
            "allocated_unit_price IS NULL OR allocated_unit_price >= 0",
            name="ck_purchase_batches_allocated_unit_price_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(80), index=True, default="set_import")
    label: Mapped[str | None] = mapped_column(String(255))
    set_id: Mapped[int | None] = mapped_column(ForeignKey("card_sets.id", ondelete="SET NULL"))
    storage_location_id: Mapped[int | None] = mapped_column(ForeignKey("storage_locations.id", ondelete="SET NULL"))
    language: Mapped[str | None] = mapped_column(String(16))
    condition: Mapped[str | None] = mapped_column(String(40))
    total_price: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    total_units: Mapped[int] = mapped_column(Integer, default=0)
    allocated_unit_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    rounding_remainder_cents: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)

    card_set: Mapped[CardSet | None] = relationship(back_populates="purchase_batches")
    storage_location: Mapped[StorageLocation | None] = relationship(back_populates="purchase_batches")
    items: Mapped[list["PurchaseBatchItem"]] = relationship(back_populates="purchase_batch", cascade="all, delete-orphan")
    inventory_items: Mapped[list[InventoryItem]] = relationship(back_populates="purchase_batch")


class PurchaseBatchItem(TimestampMixin, Base):
    __tablename__ = "purchase_batch_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_batch_items_quantity_positive"),
        CheckConstraint(
            "allocated_purchase_price_per_unit IS NULL OR allocated_purchase_price_per_unit >= 0",
            name="ck_purchase_batch_items_unit_price_nonnegative",
        ),
        CheckConstraint(
            "allocated_purchase_total >= 0",
            name="ck_purchase_batch_items_total_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_batch_id: Mapped[int] = mapped_column(ForeignKey("purchase_batches.id", ondelete="CASCADE"))
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id", ondelete="SET NULL"))
    card_print_id: Mapped[int | None] = mapped_column(ForeignKey("card_prints.id", ondelete="SET NULL"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    allocated_purchase_price_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 4))
    allocated_purchase_total: Mapped[float] = mapped_column(Numeric(10, 2))

    purchase_batch: Mapped[PurchaseBatch] = relationship(back_populates="items")
    inventory_item: Mapped[InventoryItem | None] = relationship(back_populates="purchase_batch_items")
    card_print: Mapped[CardPrint | None] = relationship()


class PriceHistory(TimestampMixin, Base):
    __tablename__ = "price_history"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_price_history_price_positive"),
        Index("ix_price_history_inventory_captured", "inventory_item_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True)
    card_print_id: Mapped[int] = mapped_column(ForeignKey("card_prints.id", ondelete="CASCADE"))
    provider_key: Mapped[str] = mapped_column(String(80))
    metric: Mapped[str] = mapped_column(String(80), default="market")
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    payload: Mapped[dict | None] = mapped_column(JSON)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    inventory_item: Mapped[InventoryItem] = relationship(back_populates="price_history")
    card_print: Mapped[CardPrint] = relationship()


class Deck(TimestampMixin, Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(80), default="Advanced")

    cards: Mapped[list["DeckCard"]] = relationship(back_populates="deck", cascade="all, delete-orphan")


class DeckCard(TimestampMixin, Base):
    __tablename__ = "deck_cards"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_deck_cards_quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id", ondelete="SET NULL"))
    card_print_id: Mapped[int | None] = mapped_column(ForeignKey("card_prints.id", ondelete="SET NULL"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(20), default="main")
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    deck: Mapped[Deck] = relationship(back_populates="cards")
    inventory_item: Mapped[InventoryItem | None] = relationship(back_populates="deck_cards")
    card_print: Mapped[CardPrint | None] = relationship()


class Collection(TimestampMixin, Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(30))

    cards: Mapped[list["CollectionCard"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class CollectionCard(TimestampMixin, Base):
    __tablename__ = "collection_cards"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_collection_cards_quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"))
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id", ondelete="SET NULL"))
    card_print_id: Mapped[int | None] = mapped_column(ForeignKey("card_prints.id", ondelete="SET NULL"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text)

    collection: Mapped[Collection] = relationship(back_populates="cards")
    inventory_item: Mapped[InventoryItem | None] = relationship(back_populates="collection_cards")
    card_print: Mapped[CardPrint | None] = relationship()


class PriceMonitorState(TimestampMixin, Base):
    __tablename__ = "price_monitor_states"
    __table_args__ = (
        CheckConstraint("price_check_interval_hours > 0", name="ck_price_monitor_interval_positive"),
        CheckConstraint("failure_count >= 0", name="ck_price_monitor_failure_count_nonnegative"),
        CheckConstraint(
            "consecutive_stable_checks >= 0",
            name="ck_price_monitor_stable_checks_nonnegative",
        ),
        Index(
            "ix_price_monitor_due_priority",
            "next_price_check_at",
            "price_check_priority",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), unique=True, index=True)
    last_price_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_price_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    price_check_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    price_volatility_score: Mapped[float] = mapped_column(default=0)
    price_check_priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    price_stability_state: Mapped[str] = mapped_column(String(50), default="new", index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_stable_checks: Mapped[int] = mapped_column(Integer, default=0)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text)

    inventory_item: Mapped[InventoryItem] = relationship(back_populates="price_monitor_state")


class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        Index(
            "ix_sync_jobs_claim",
            "status",
            "available_at",
            "priority",
            "created_at",
        ),
        Index(
            "uq_sync_jobs_running_lock_key",
            "lock_key",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    provider_key: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), index=True, default="pending")
    lock_key: Mapped[str] = mapped_column(String(120))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    log_excerpt: Mapped[str | None] = mapped_column(Text)
    log_details: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Progress tracking fields
    total_items: Mapped[int | None] = mapped_column(Integer)
    processed_items: Mapped[int | None] = mapped_column(Integer, default=0)
    successful_items: Mapped[int | None] = mapped_column(Integer, default=0)
    failed_items: Mapped[int | None] = mapped_column(Integer, default=0)
    next_scheduled_item_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)


class ImageAsset(TimestampMixin, Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_print_id: Mapped[int] = mapped_column(ForeignKey("card_prints.id", ondelete="CASCADE"))
    provider_key: Mapped[str] = mapped_column(String(80))
    remote_url: Mapped[str | None] = mapped_column(String(600))
    local_path: Mapped[str | None] = mapped_column(String(600))
    thumbnail_path: Mapped[str | None] = mapped_column(String(600))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    card_print: Mapped[CardPrint] = relationship(back_populates="image_assets")


class SourceMapping(TimestampMixin, Base):
    __tablename__ = "source_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    provider_key: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    external_url: Mapped[str | None] = mapped_column(String(600))
    payload: Mapped[dict | None] = mapped_column(JSON)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
