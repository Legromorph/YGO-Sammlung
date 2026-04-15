# Architektur

## Schichten

1. Frontend
   Next.js liefert eine responsive Verwaltungsoberflaeche mit Dashboard, Kartenliste, Detailansicht, Lagerorten, Decks, Sammlungen und Sync-Status.

2. API
   FastAPI kapselt die Anwendung als REST-API. Die Endpunkte sind bewusst duenn und delegieren Fachlogik an `app/services`.

3. Domain- und Service-Schicht
   Die Service-Module kuemmern sich um Listenansichten, Upserts, Dashboard-Berechnungen, Trend-Rebuilds und Sync-Orchestrierung.

4. Integrationen
   Preis-, Bild- und Kartendatenquellen liegen in `app/integrations`. Dadurch bleibt die technische und rechtliche Trennung sauber:
   - `card_data.py`
   - `prices.py`
   - `images.py`
   - `ygo_omega.py`

5. Persistenz
   SQLAlchemy 2 bildet das relationale Modell auf PostgreSQL ab. Alembic liefert die initiale Migration.

6. Background Processing
   Celery Worker verarbeitet Jobs, Celery Beat plant periodische Ausfuehrungen. Job-Status und Logs werden in `sync_jobs` persistiert.

## Datenfluss

- UI -> REST API -> Services -> SQLAlchemy -> PostgreSQL
- Celery Beat -> Celery Worker -> Sync Service -> Provider -> PostgreSQL / Media Volume
- Bilder -> lokales Volume -> Backend `StaticFiles` -> Frontend

## Warum kein Microservice-Split

Das Projekt bleibt bewusst ein Monorepo mit klar getrennten Schichten statt einer unnötig komplexen Microservice-Landschaft. Dadurch bleibt der lokale Betrieb mit `docker compose up --build` einfach, waehrend Preisprovider und Datenquellen trotzdem modular austauschbar bleiben.
