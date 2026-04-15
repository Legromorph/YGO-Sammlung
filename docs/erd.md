# ERD-Beschreibung

## Kernbeziehungen

- `cards 1:n card_prints`
  Eine kanonische Karte kann mehrere Prints bzw. Editionen besitzen.

- `card_prints 1:n inventory_items`
  Eine Edition kann mehrfach im Besitz sein, etwa in unterschiedlichem Zustand oder an verschiedenen Lagerorten.

- `storage_locations 1:n inventory_items`
  Jede Inventarposition kann einem physischen Lagerort zugewiesen werden.

- `storage_locations 1:n storage_locations`
  Lagerorte koennen hierarchisch modelliert werden, etwa `Binder Rot > Seite 12 > Slot 3`.

- `inventory_items 1:n price_history`
  Jede Preisabfrage erzeugt einen Snapshot zur Trendberechnung.

- `decks 1:n deck_cards`
  Deckkarten referenzieren bevorzugt `inventory_items`, speichern aber zusaetzlich `card_print_id`, damit Decks bei geloeschten Inventarpositionen nicht unbrauchbar werden.

- `collections 1:n collection_cards`
  Sammlungen funktionieren analog zu Decks, aber ohne Main/Extra/Side-Semantik.

- `card_prints 1:n image_assets`
  Pro Print kann mindestens ein lokales Bildasset gespeichert werden.

- `cards | card_prints | inventory_items -> source_mappings`
  Externe IDs werden generisch an interne Datensaetze gemappt.

- `sync_jobs`
  Persistiert manuelle und periodische Hintergrundjobs inklusive Status, Payload und Fehlermeldungen.

## Designentscheidung

Die Trennung `cards -> card_prints -> inventory_items` ist der zentrale Punkt des Datenmodells. Sie ermoeglicht:

- identische Karte in mehreren Sets/Sprachen
- gleiche Edition an mehreren Lagerorten
- unterschiedliche Zustaende und Einkaufspreise
- Preis-Historien pro Besitzposition
- spaetere Provider- oder Marketplace-Erweiterungen ohne Modellbruch
