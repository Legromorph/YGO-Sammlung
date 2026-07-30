from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.database import get_db
from app.services.backups import create_backup_archive, restore_backup_archive
from app.time_utils import utc_now

router = APIRouter()


@router.get("/download")
async def download_backup(db: AsyncSession = Depends(get_db)) -> FileResponse:
    archive_path = await create_backup_archive(db)
    timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"ygo-sammlung-backup-{timestamp}.zip",
        background=BackgroundTask(lambda: archive_path.unlink(missing_ok=True)),
    )


@router.post("/restore", status_code=status.HTTP_200_OK)
async def restore_backup(
    backup: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if not backup.filename or not backup.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bitte ein ZIP-Backup hochladen.")

    temporary = tempfile.NamedTemporaryFile(prefix="ygo-restore-", suffix=".zip", delete=False)
    temporary_path = Path(temporary.name)
    try:
        while chunk := await backup.read(1024 * 1024):
            temporary.write(chunk)
        temporary.close()

        try:
            result = await restore_backup_archive(db, temporary_path)
            await db.commit()
            return result
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Backup konnte nicht eingespielt werden.") from exc
    finally:
        temporary.close()
        temporary_path.unlink(missing_ok=True)
        await backup.close()
