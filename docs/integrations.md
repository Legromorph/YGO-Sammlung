# Integrationen und Grenzen

## Kartendaten und Bilder

### YGOPRODeck

- Liefert Kartendaten, Bild-URLs und druckspezifische TCGPlayer-Marktdaten.
- Providerfelder werden unmittelbar in `app/domain/card_metadata.py` normalisiert.
- `race` wird abhängig von der kanonischen Kartenart entweder als Monster-Typ oder als
  Zauber-/Fallentyp interpretiert.
- Kartenbilder werden in das lokale Medien-Volume gespiegelt.

Referenz: <https://api.ygoprodeck.com/api-guide/>

## Preise

### YgoProDeckPriceProvider

- Nutzt `tcgplayer_data=yes` für druckspezifische TCGPlayer-Marktpreise in USD.
- Kann den allgemeinen Cardmarket-Kartenpreis aus dem YGOPRODeck-Datensatz in EUR als
  sichtbar markierten, nicht druckspezifischen Fallback verwenden.
- Verwirft Nullpreise, negative Werte und nicht endliche Zahlen.
- Speichert nur positive Snapshots in `price_history`.
- Vergleicht im Preisverlauf nur Werte derselben Währung.

### CardmarketPriceProvider

- Führt keine HTML-Abfragen, Browser-Simulation oder Varianten-Probes gegen Cardmarket aus.
- Ein automatisch gebauter Produktlink bleibt unbestätigt, bis er in der Kartenansicht
  manuell bestätigt wurde.
- Ein Link kann unabhängig von der automatischen Erzeugung manuell gesetzt, geändert,
  entfernt und bestätigt werden.
- Cardmarket-Preise werden manuell gepflegt. Eine automatische Preisabfrage bleibt
  deaktiviert, bis autorisierte API-Zugangsdaten und eine passende API-Anbindung vorhanden sind.
- Unbestätigte Kandidaten werden niemals als Quelle für einen Cardmarket-Preis verwendet.

Die gekapselte Struktur für eine spätere autorisierte Anbindung bleibt erhalten:

- `cardmarket_reference`
- `cardmarket_product_url`
- `source_mappings`
- Provider- und Preisstatus

Referenzen:

- <https://help.cardmarket.com/en/cardmarket-api>
- <https://api.cardmarket.com/ws/documentation/API_2.0:Main_Page>

## YGO Omega

- `YGO_OMEGA_DIRECTORY` kann optional auf eine lokale Installation zeigen.
- Die Anwendung prüft nur den lokalen Pfad und zeigt dessen Status.
- Eine nicht dokumentierte Produktivintegration wird bewusst nicht simuliert.

## Spätere Ausbaustufen

- Offizielles, druckgenaues EU-Pricing
- Autorisierte Cardmarket-API-Anbindung
- Dokumentierte Omega-Deck- oder Datenbanksynchronisierung
