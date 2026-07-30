from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AppSetting,
    Card,
    CardPrint,
    CardSet,
    Collection,
    CollectionCard,
    Deck,
    DeckCard,
    ImageAsset,
    InventoryItem,
    PriceHistory,
    PriceMonitorState,
    PurchaseBatch,
    PurchaseBatchItem,
    SourceMapping,
    StorageLocation,
    SyncJob,
)
from app.services.exports import build_collection_json_export
from app.time_utils import utc_now


BACKUP_SCHEMA = "ygo-sammlung.backup"
BACKUP_VERSION = 1

RESTORE_MODELS = (
    AppSetting,
    Card,
    CardSet,
    StorageLocation,
    CardPrint,
    PurchaseBatch,
    InventoryItem,
    PurchaseBatchItem,
    PriceHistory,
    Deck,
    DeckCard,
    Collection,
    CollectionCard,
    ImageAsset,
    SourceMapping,
    PriceMonitorState,
)

RUNTIME_ONLY_MODELS = (SyncJob,)
CLEAR_MODELS = (*RESTORE_MODELS, *RUNTIME_ONLY_MODELS)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _convert_column_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return _parse_datetime(value)
    if isinstance(column.type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(column.type, Numeric):
        return Decimal(str(value))
    return value


def _model_from_row(model, row: dict[str, Any]):
    values = {
        column.name: _convert_column_value(column, row.get(column.name))
        for column in model.__table__.columns
        if column.name in row
    }
    return model(**values)


async def create_backup_archive(db: AsyncSession) -> Path:
    backup = await build_collection_json_export(db)
    backup["schema"] = BACKUP_SCHEMA
    backup["version"] = BACKUP_VERSION
    backup["media_root"] = "media"

    temporary = tempfile.NamedTemporaryFile(prefix="ygo-sammlung-", suffix=".zip", delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()

    media_root = settings.media_root_path
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "collection.json",
                json.dumps(backup, ensure_ascii=False, separators=(",", ":")),
            )
            if media_root.exists():
                for media_file in media_root.rglob("*"):
                    if media_file.is_file():
                        archive.write(media_file, Path("media") / media_file.relative_to(media_root))
        return temporary_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _read_backup_payload(archive_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path) as archive:
        try:
            with archive.open("collection.json") as payload_file:
                payload = json.load(payload_file)
        except KeyError as exc:
            raise ValueError("Backup enthält keine collection.json.") from exc

    if payload.get("schema") not in {BACKUP_SCHEMA, "ygo-sammlung.collection-export"}:
        raise ValueError("Backup-Schema wird nicht unterstützt.")
    if int(payload.get("version", 0)) != BACKUP_VERSION:
        raise ValueError("Backup-Version wird nicht unterstützt.")
    if not isinstance(payload.get("tables"), dict):
        raise ValueError("Backup enthält keine Tabellendaten.")
    return payload


def _validate_archive_paths(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("Backup enthält einen ungültigen Dateipfad.")


def _restore_media(archive_path: Path) -> None:
    media_root = settings.media_root_path
    temporary_media = Path(tempfile.mkdtemp(prefix="ygo-media-restore-"))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if not member.filename.startswith("media/") or member.is_dir():
                    continue
                target_path = temporary_media / member_path.relative_to("media")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

        media_root.mkdir(parents=True, exist_ok=True)
        for existing_item in media_root.iterdir():
            if existing_item.is_dir() and not existing_item.is_symlink():
                shutil.rmtree(existing_item)
            else:
                existing_item.unlink()
        for item in temporary_media.iterdir():
            shutil.move(str(item), str(media_root / item.name))
        settings.cards_media_path.mkdir(parents=True, exist_ok=True)
    finally:
        shutil.rmtree(temporary_media, ignore_errors=True)


async def _reset_sequences(db: AsyncSession) -> None:
    for model in CLEAR_MODELS:
        table_name = model.__tablename__
        await db.execute(
            text(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table_name}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                    (SELECT COUNT(*) FROM {table_name}) > 0
                )
                """
            )
        )


async def restore_backup_archive(db: AsyncSession, archive_path: Path) -> dict[str, Any]:
    _validate_archive_paths(archive_path)
    payload = _read_backup_payload(archive_path)
    tables = payload["tables"]

    for model in reversed(CLEAR_MODELS):
        await db.execute(delete(model))
    await db.flush()

    restored_counts: dict[str, int] = {}
    for model in RESTORE_MODELS:
        rows = tables.get(model.__tablename__, [])
        if not isinstance(rows, list):
            raise ValueError(f"Tabelle {model.__tablename__} ist ungültig.")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Tabelle {model.__tablename__} enthält eine ungültige Zeile.")
            db.add(_model_from_row(model, row))
        restored_counts[model.__tablename__] = len(rows)
        await db.flush()

    await _reset_sequences(db)
    _restore_media(archive_path)

    return {
        "schema": BACKUP_SCHEMA,
        "version": BACKUP_VERSION,
        "restored_at": utc_now().isoformat(),
        "tables": restored_counts,
    }
