# YGO Sammlung

Docker-basierte Webanwendung zur Verwaltung einer Yu-Gi-Oh!-Kartensammlung mit FastAPI, Next.js, PostgreSQL, lokaler Bildspeicherung und modularen Provider-Schnittstellen fuer Preise, Kartendaten und spaetere YGO-Omega-Anbindung.

## Architekturuebersicht

- Frontend: Next.js 14 mit React, Material UI, Recharts und einer responsiven Admin-Shell
- Backend: FastAPI mit SQLAlchemy 2, Pydantic 2, sauberer Service- und Provider-Trennung
- Datenbank: PostgreSQL fuer Inventar, Preisverlauf, Decks, Sammlungen, Jobs und Source-Mappings
- Worker/Scheduler: dedizierter DB-Polling-Worker plus Scheduler-Service fuer Preisupdates, Bilddownloads, Trend-Rebuilds und Kartendaten-Sync
- Assets: lokales Docker-Volume fuer Kartenbilder und Thumbnails unter `/app/media`

## Technologieentscheidung

- FastAPI bleibt, weil das bestehende Repo bereits darauf aufsetzt und sich mit Pydantic, Async-SQLAlchemy und automatischer OpenAPI-Dokumentation sehr gut fuer ein produktionsnahes Verwaltungs-MVP eignet.
- Next.js bleibt, weil das vorhandene Frontend bereits React-basiert ist und sich damit eine moderne Desktop-optimierte Oberfläche mit SSR-faehigem Produktionsbuild sauber integrieren laesst.
- PostgreSQL ist die Standardwahl fuer relationale Bestandsdaten, Preis-Historien und spaetere Volltext-/Reporting-Erweiterungen.
- Ein DB-basierter Worker mit atomischem Claiming ueber PostgreSQL bleibt fuer dieses MVP robuster als ein separater Broker-Only-Flow, weil `sync_jobs` damit direkt die Source of Truth fuer Queue, Status und Recovery sind.
- YGOPRODeck ist der Default fuer Kartendaten und Bilder, weil dort Metadaten und Bild-URLs offen dokumentiert sind. Die Preis-Schicht ist trotzdem modular, damit spaeter eine andere Quelle oder eine offizielle Cardmarket-Anbindung ergänzt werden kann.

## Projektstruktur

```text
.
├─ backend/
│  ├─ alembic/
│  ├─ app/
│  │  ├─ api/endpoints/
│  │  ├─ integrations/
│  │  ├─ services/
│  │  ├─ celery_app.py
│  │  ├─ config.py
│  │  ├─ database.py
│  │  ├─ main.py
│  │  ├─ models.py
│  │  ├─ schemas.py
│  │  └─ worker.py
│  ├─ Dockerfile
│  ├─ requirements.txt
│  └─ seed.py
├─ docs/
│  ├─ architecture.md
│  ├─ erd.md
│  └─ integrations.md
├─ frontend/
│  ├─ components/
│  ├─ lib/
│  ├─ pages/
│  ├─ public/
│  ├─ styles/
│  ├─ Dockerfile
│  └─ package.json
├─ docker-compose.yml
└─ .env.example
```

## Datenmodell

Die Anwendung trennt bewusst zwischen Kartenmetadaten, Prints und Besitz:

- `cards`: kanonische Kartendaten wie Name, Typ, Effekttext, ATK/DEF, Attribute
- `card_sets`: synchronisierter Set-Katalog fuer Bulk-Erfassung, Set-Suche und Print-Zuordnung
- `card_prints`: sprach- und setbezogene Editionen mit Setname, Setcode, Seltenheit, Kartennummer
- `inventory_items`: konkrete Besitzpositionen mit Zustand, Menge, Kaufpreis, aktuellem Marktpreis und Lagerort
- `storage_locations`: physische Lagerorte mit optionaler Hierarchie und gecachtem Pfad
- `price_history`: Zeitreihe der Preis-Snapshots pro Inventarposition
- `decks` / `deck_cards`: Decklisten mit Main/Extra/Side und Preisaufschluesselung
- `collections` / `collection_cards`: freie Sammlungen oder Kategorien
- `sync_jobs`: Worker-Jobs mit Status, atomischem Claiming, Log-Auszug und Fehlern
- `image_assets`: lokal gespeicherte Bilder samt Thumbnail-Metadaten
- `source_mappings`: Zuordnung interner Datensaetze zu externen IDs

Details und ERD-Beschreibung: [docs/erd.md](docs/erd.md)

## Schnellstart

1. `.env.example` nach `.env` kopieren.
2. Docker Desktop oder Docker Engine starten.
3. Anwendung bauen und starten:

```bash
docker compose up --build
```

4. Frontend: `http://localhost:3000`
5. API: `http://localhost:8000`
6. OpenAPI: `http://localhost:8000/docs`

Beim ersten Start fuehrt das Backend automatisch `alembic upgrade head` und das Seed-Skript aus.

## Wichtige API-Endpunkte

- `GET /api/health/`
- `GET /api/dashboard/`
- `GET/POST/PUT/DELETE /api/cards/`
- `GET /api/cards/filters`
- `GET /api/cards/{id}/price-history`
- `GET /api/sets/`
- `GET /api/sets/{id}/cards`
- `POST /api/inventory/bulk-add-from-set`
- `GET/POST/PUT/DELETE /api/storage-locations/`
- `GET/POST/PUT/DELETE /api/decks/`
- `GET/POST/PUT/DELETE /api/collections/`
- `GET /api/sync/`
- `GET /api/sync/jobs`
- `GET /api/sync/jobs/{id}`
- `POST /api/sync/jobs`
- `POST /api/sync/jobs/{id}/retry`
- `GET /media/...` fuer lokal gespeicherte Kartenbilder

## Hintergrundjobs

- `price_update`: holt neue Marktpreise ueber den aktiven PriceProvider
- `image_sync`: laedt fehlende Kartenbilder lokal in das Volume
- `trend_rebuild`: berechnet 7d/30d-Aenderungen und einen Trend-Score neu
- `card_data_sync`: reichert lokale Karten mit YGOPRODeck-Metadaten an

- Der `worker`-Container pollt `sync_jobs` direkt aus PostgreSQL, claimt Jobs atomar per `FOR UPDATE SKIP LOCKED` und setzt sie sauber auf `running`, `completed` oder `failed`.
- Der `scheduler`-Container erzeugt die periodischen Jobs direkt in `sync_jobs`.
- Fehlgeschlagene Jobs koennen ueber die Sync-Seite oder `POST /api/sync/jobs/{id}/retry` erneut gestartet werden.
- Lange laufende `running`-Jobs werden automatisch als fehlgeschlagen markiert, damit kein Eintrag still haengen bleibt.

## Frontend-Funktionen

- Dashboard mit KPIs, Wertverlauf, Preisgewinnern, Preisverlierern und Review-Kandidaten
- Kartenliste mit Filterpanel, Pagination, Preisindikatoren, Edit-/Delete-Aktionen
- Set-Erfassung mit Set-Suche, Sammelwerten, nummern-sortierter Kartenliste, Live-Zusammenfassung und Bulk-Speichern
- Karten-Detailseite mit Preisverlauf und Source-Mappings
- CRUD fuer Lagerorte, Decklisten und Sammlungen
- Sync-/Provider-Status für Datenquellen und Worker-Jobs

## Bulk-Set-Erfassung

- Die Seite `Set-Erfassung` sucht im synchronisierten YGOPRODeck-Set-Katalog und laedt die Set-Karten bei Bedarf automatisch nach.
- Die Set-Synchronisierung trennt Kataloggroesse und lokal geladene Kartenanzahl. Unvollstaendige Sets werden nicht stillschweigend als vollstaendig behandelt, sondern mit Warnstatus markiert.
- Die Kartenliste ist nach Kartennummer natuerlich sortiert und zeigt Bild, Name, Setnummer, Seltenheit, vorhandenen Bestand und Preishinweis.
- Der obere Preis ist ein `Display-Gesamtpreis` fuer den gesamten Einkaufsvorgang, nicht ein Preis pro Karte.
- Der Display-Gesamtpreis wird live auf die aktuell eingetragene Gesamtanzahl verteilt. Die Summe aller gespeicherten Zeilen bleibt dabei exakt auf den Gesamtbetrag gerundet.
- Lagerort, Zustand, Sprache und Notiz werden als Sammelwerte auf den Einkaufsvorgang angewendet.
- Gespeichert werden nur Karten mit Menge groesser `0`.
- Die Bulk-Aktion laeuft transaktional ueber `POST /api/inventory/bulk-add-from-set`.
- Jeder Bulk-Import erzeugt einen eigenen `purchase_batch` mit zugehoerigen `purchase_batch_items`, damit die Charge spaeter nachvollziehbar bleibt.
- Die Inventarzeilen speichern sowohl den verteilten Preis pro Karte als auch den exakten Gesamtankauf der jeweiligen Zeile.
- Als Startwert fuer Marktpreise nutzt der Bulk-Import zuerst vorhandene lokale Preis-Snapshots und faellt dann auf den YGOPRODeck-Setpreis des gewaehlten Prints zurueck.

- Direkt nach erfolgreichem Bulk-Import wird automatisch ein gezielter `price_update`-Job nur fuer die neu importierten `inventory_items` und `card_prints` gestartet.
- Die Set-Erfassungsseite pollt diesen Jobstatus und zeigt `Preisupdate laeuft` bzw. das letzte erfolgreiche Preisupdate sichtbar an.
- Der Preisjob wird vom dedizierten Worker direkt geclaimt; er bleibt damit nicht mehr still auf `pending`, wenn der Import bereits erfolgreich gespeichert wurde.

## Preislogik

- Preis-Matching laeuft auf `card_print`-Ebene statt nur ueber den Kartennamen.
- Fuer den Match werden mindestens `set_code`, `card_number`, `rarity` und die aus dem Printcode ableitbare Sprache beruecksichtigt.
- Unsichere Namens-Fallbacks werden nicht mehr stillschweigend als Marktpreis uebernommen. Wenn kein verlasslicher Print-Match existiert, bleibt der Preis leer und wird als Fallback markiert.
- Die API liefert pro Inventarposition einen Preisstatus mit Match-Qualitaet, Quelle, letztem Update und einem Cardmarket-Link.
- Wenn eine exakte Cardmarket-Produktreferenz lokal bekannt ist, wird sie auf der Kartenprofilseite direkt verwendet. Andernfalls verlinkt die UI auf die passende Cardmarket-Kartenansicht.

## Entwicklungsnotizen

- Der Produktionscontainer des Frontends baut ein Next.js-Standalone-Bundle.
- Build-Artefakte wie `.next/`, `node_modules/` und `__pycache__/` werden per `.gitignore` ausgespart.
- Das aktuelle MVP fokussiert die im Prompt priorisierten Bereiche: Kartenverwaltung, Lagerorte, Web-GUI, Preisverlauf, Dashboard, Decks/Sammlungen und lokale Bilder.

## Grenzen und Integrationen

- Cardmarket und YGO Omega werden bewusst modular gekapselt, aber nicht als wackelige Schein-Integration ausgeliefert.
- Details und rechtlich/technische Grenzen stehen in [docs/integrations.md](docs/integrations.md).

## TODOs

- CSV-Import/Export
- Volltextsuche mit PostgreSQL GIN/TSVector
- Deck-Exportformate
- Kartenanlage direkt aus Remote-Suche im UI
- Individuelle Einzelpreise pro Karte innerhalb der Bulk-Set-Erfassung
- Authentifizierung, Benutzer- und Rollenmodell
- Genauere, print-spezifische Preisprovider fuer den EU-Markt
