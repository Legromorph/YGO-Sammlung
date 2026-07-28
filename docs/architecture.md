# Architektur

## Schichten

1. Frontend
   Next.js liefert eine responsive Verwaltungsoberfläche mit Dashboard, Kartenliste, Detailansicht, Lagerorten, Decks, Sammlungen und Sync-Status.

2. API
   FastAPI kapselt die Anwendung als REST-API. Die Endpunkte sind bewusst dünn und delegieren Fachlogik an `app/services`.

3. Domain- und Service-Schicht
   Kanonische Kartenmetadaten und Feldregeln liegen in `app/domain/card_metadata.py`.
   Karten-CRUD, Suche, Serialisierung, Cardmarket-Auflösung sowie Job-Orchestrierung und
   Sync-Aufgaben sind in getrennte Service-Module aufgeteilt.

4. Integrationen
   Preis-, Bild- und Kartendatenquellen liegen in `app/integrations`. Dadurch bleibt die technische und rechtliche Trennung sauber:
   - `card_data.py`
   - `prices.py`
   - `images.py`
   - `ygo_omega.py`

5. Persistenz
   SQLAlchemy 2 bildet das relationale Modell auf PostgreSQL ab. Alembic liefert die initiale Migration.

6. Background Processing
   Ein DB-basierter Worker claimt Jobs atomar aus `sync_jobs`. Ein separater Scheduler plant fällige Preis-, Bild-, Trend- und Kartendaten-Jobs.

7. Sicherung und Export
   Die API erzeugt CSV- und JSON-Exporte. Ein separater Compose-Dienst sichert PostgreSQL
   und das Medien-Volume atomar in einem konfigurierbaren Backup-Verzeichnis.

## Datenfluss

- UI -> REST API -> Services -> SQLAlchemy -> PostgreSQL
- Scheduler -> `sync_jobs` -> Worker -> Sync Service -> Provider -> PostgreSQL / Media Volume
- Bilder -> lokales Volume -> Backend `StaticFiles` -> Frontend

## Warum kein Microservice-Split

Das Projekt bleibt bewusst ein Monorepo mit klar getrennten Schichten statt einer unnötig komplexen Microservice-Landschaft. Dadurch bleibt der lokale Betrieb mit `docker compose up --build` einfach, während Preisprovider und Datenquellen trotzdem modular austauschbar bleiben.
