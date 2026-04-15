# Integrationen und Grenzen

## Kartendaten und Bilder

### Default: YGOPRODeck

- Verwendet fuer:
  - Kartendaten-Sync
  - Bild-URLs
  - Default-Preis-Fallback
- Grund:
  - offene, dokumentierte API
  - Effekttexte, Typen, Attribute, ATK/DEF, Link- und Pendelinfos sind sauber verfuegbar
  - Bild-URLs sind direkt vorhanden und koennen lokal gespiegelt werden
- Referenz:
  - https://ygoprodeck.com/api-guide/

## Preise

### Aktiver MVP-Provider: `YgoProDeckPriceProvider`

- Nutzt `card_prices` als legalen Default-Fallback
- Speichert Preis-Snapshots in `price_history`
- Trendanalyse wird intern aus historischen Snapshots berechnet

### Vorbereiteter Provider: `CardmarketPriceProvider`

- Als abstrakte Schnittstelle vorhanden
- Im MVP bewusst nicht aktiv, solange keine belastbare, sauber freigeschaltete Credentials-Situation vorliegt
- Cardmarket dokumentiert zwar eine offizielle API, weist aber gleichzeitig darauf hin, dass aktuell keine neuen API-Zugaenge angenommen werden
- Fuer manuelle Produktlinks gibt es zusaetzlich einen nutzergetriggerten Public-Page-Import:
  - akzeptiert einzelne oeffentliche Cardmarket-Produktlinks fuer Yu-Gi-Oh!-Einzelkarten
  - liest Set, Raritaet, Nummer und Preis-Trend aus der sichtbaren Produktseite
  - reichert Kartentext, Typen und IDs danach weiter ueber YGOPRODeck an
  - ist bewusst als HTML-Fallback gekennzeichnet und ersetzt keine offizielle OAuth-API
- Die App kapselt Cardmarket-Referenzen trotzdem bereits in:
  - `cardmarket_reference`
  - `source_mappings`
  - Sync-/Provider-Status
- Referenzen:
  - https://help.cardmarket.com/es/cardmarket-api
  - https://api.cardmarket.com/ws/documentation/API_2.0:Main_Page

## YGO Omega

- Kein lokaler API-Zwang im System
- Optionaler Pfad `YGO_OMEGA_DIRECTORY` kann gesetzt werden
- Die App prueft dann nur den lokalen Installationspfad und dokumentiert den Status
- Es wird bewusst keine unklare oder reverse-engineerte Produktiv-Integration vorgetaeuscht
- Referenzen:
  - https://forum.duelistsunite.org/t/installation-and-troubleshooting-guide/3802
  - https://github.com/duelists-unite/omega-releases/releases

## Offene Punkte fuer spaetere Ausbaustufen

- print-genaues EU-Pricing
- Cardmarket OAuth-Implementierung, falls nutzbare offizielle Credentials vorliegen
- lokale Omega-Deck- oder Datenbank-Synchronisierung, sobald ein stabiler, dokumentierbarer Zugriff vorliegt
