from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import session_scope
from app.models import Card, CardPrint, Collection, CollectionCard, Deck, DeckCard, InventoryItem, PriceHistory, StorageLocation
from app.services.storage import rebuild_location_paths
from app.time_utils import utc_now


async def seed_demo_data() -> None:
    async with session_scope() as db:
        existing = await db.scalar(select(Card.id).limit(1))
        if existing:
            return

        binder_red = StorageLocation(name="Binder Rot", location_type="binder", description="High-value staples", path_cache="")
        binder_red_page = StorageLocation(name="Seite 12", location_type="page", parent=binder_red, position_label="Slot 3", path_cache="")
        binder_green = StorageLocation(name="Binder Grün", location_type="binder", description="Engine pieces", path_cache="")
        trade_binder = StorageLocation(name="Trade Binder", location_type="trade_binder", description="Tauschkarten", path_cache="")
        deckbox_black = StorageLocation(name="Deckbox Schwarz", location_type="deckbox", description="Turnierdeck", path_cache="")
        db.add_all([binder_red, binder_red_page, binder_green, trade_binder, deckbox_black])
        await db.flush()
        await rebuild_location_paths(db)

        blue_eyes = Card(name="Blue-Eyes White Dragon", normalized_name="blue-eyes white dragon", card_type="Normal Monster", card_kind="monster", description="This legendary dragon is a powerful engine of destruction.", attribute="LIGHT", monster_type="Dragon", atk=3000, defense=2500, level=8)
        ash = Card(name="Ash Blossom & Joyous Spring", normalized_name="ash blossom & joyous spring", card_type="Tuner Monster", card_kind="monster", description="When a card or effect is activated that includes any of these effects...", attribute="FIRE", monster_type="Zombie", atk=0, defense=1800, level=3)
        imperm = Card(name="Infinite Impermanence", normalized_name="infinite impermanence", card_type="Trap Card", card_kind="trap", description="Target 1 face-up monster your opponent controls; negate its effects.", spell_trap_type="normal")
        pot = Card(name="Pot of Prosperity", normalized_name="pot of prosperity", card_type="Spell Card", card_kind="spell", description="Banish 3 or 6 cards from your Extra Deck face-down; excavate cards from the top of your Deck.", spell_trap_type="normal")
        nibiru = Card(name="Nibiru, the Primal Being", normalized_name="nibiru, the primal being", card_type="Effect Monster", card_kind="monster", description="During the Main Phase, if your opponent Normal or Special Summoned 5 or more monsters this turn...", attribute="LIGHT", monster_type="Rock", atk=3000, defense=600, level=11)
        db.add_all([blue_eyes, ash, imperm, pot, nibiru])
        await db.flush()

        prints = [
            CardPrint(card=blue_eyes, language="de", set_name="Legend of Blue Eyes White Dragon", set_code="LOB-G001", card_number="001", rarity="Ultra Rare"),
            CardPrint(card=ash, language="de", set_name="Maximum Crisis", set_code="MACR-DE036", card_number="036", rarity="Secret Rare"),
            CardPrint(card=imperm, language="de", set_name="Flames of Destruction", set_code="FLOD-DE077", card_number="077", rarity="Secret Rare"),
            CardPrint(card=pot, language="de", set_name="Blazing Vortex", set_code="BLVO-DE065", card_number="065", rarity="Secret Rare"),
            CardPrint(card=nibiru, language="en", set_name="2019 Gold Sarcophagus Tin", set_code="TN19-EN013", card_number="013", rarity="Prismatic Secret Rare"),
        ]
        db.add_all(prints)
        await db.flush()

        items = [
            InventoryItem(card_print=prints[0], storage_location=binder_red_page, condition="near_mint", quantity=1, purchase_price=42.0, current_market_price=74.0, current_price_currency="EUR", last_price_source="manual", notes="Vintage pickup"),
            InventoryItem(card_print=prints[1], storage_location=trade_binder, condition="near_mint", quantity=3, purchase_price=7.5, current_market_price=12.9, current_price_currency="EUR", last_price_source="manual"),
            InventoryItem(card_print=prints[2], storage_location=deckbox_black, condition="excellent", quantity=2, purchase_price=5.0, current_market_price=10.4, current_price_currency="EUR", last_price_source="manual"),
            InventoryItem(card_print=prints[3], storage_location=binder_green, condition="near_mint", quantity=1, purchase_price=34.0, current_market_price=51.5, current_price_currency="EUR", last_price_source="manual"),
            InventoryItem(card_print=prints[4], storage_location=trade_binder, condition="good", quantity=2, purchase_price=4.5, current_market_price=8.8, current_price_currency="EUR", last_price_source="manual"),
        ]
        db.add_all(items)
        await db.flush()

        now = utc_now()
        history_points = [
            (items[0], [58.0, 63.0, 70.0, 74.0]),
            (items[1], [8.5, 9.2, 11.8, 12.9]),
            (items[2], [9.6, 10.0, 10.2, 10.4]),
            (items[3], [41.0, 44.0, 48.0, 51.5]),
            (items[4], [6.4, 6.8, 7.9, 8.8]),
        ]
        for item, prices in history_points:
            for offset, price in enumerate(prices):
                db.add(
                    PriceHistory(
                        inventory_item=item,
                        card_print=item.card_print,
                        provider_key="seed",
                        metric="market",
                        currency="EUR",
                        price=price,
                        captured_at=now - timedelta(days=(len(prices) - offset) * 7),
                        payload={"seed": True},
                    )
                )

        deck = Deck(name="Kashtira Control", description="Sample tournament deck", format="Advanced")
        deck.cards = [
            DeckCard(inventory_item=items[1], card_print=items[1].card_print, quantity=3, section="main"),
            DeckCard(inventory_item=items[2], card_print=items[2].card_print, quantity=2, section="main"),
            DeckCard(inventory_item=items[3], card_print=items[3].card_print, quantity=1, section="main"),
        ]
        collection = Collection(name="Staples 2026", description="High-playability staples", color="#D6A64D")
        collection.cards = [
            CollectionCard(inventory_item=items[1], card_print=items[1].card_print, quantity=3),
            CollectionCard(inventory_item=items[2], card_print=items[2].card_print, quantity=2),
            CollectionCard(inventory_item=items[4], card_print=items[4].card_print, quantity=2),
        ]
        db.add_all([deck, collection])
