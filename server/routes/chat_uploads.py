"""Uploading files into an assistant conversation.

The POST stores the bytes and returns immediately with `status: parsing`, then
extraction runs as a background task and the client polls. A 25 MB workbook can
take tens of seconds to parse, which is far too long to hold a request open —
especially behind the Apps front door — and the user should see the chip appear
the moment the bytes land, not when openpyxl finishes.
"""

import logging
from typing import List

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from middleware.auth import get_db_client
from routes.roles import _get_current_username
from services import file_extract, upload_store

router = APIRouter()

logger = logging.getLogger(__name__)

# Read the body in chunks and stop early: a caller sending a 2 GB file should be
# rejected without that 2 GB ever being held in memory.
_CHUNK = 1024 * 1024


@router.post("")
@router.post("/")
async def upload_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    conversation_id: str = Form(""),
    env: str = Form("dev"),
    w: WorkspaceClient = Depends(get_db_client),
):
    username = _get_current_username(w)

    ceiling = upload_store.max_upload_bytes()
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > ceiling:
            raise HTTPException(
                status_code=413,
                detail=f"That file is larger than the {ceiling // 1_048_576} MB limit.",
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    try:
        created = upload_store.create_upload(
            env, username, file.filename or "file", data,
            mime=file.content_type or "", conversation_id=conversation_id or "",
        )
    except upload_store.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("storing upload failed for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Could not store that file: {exc}")

    background.add_task(_parse, env, created["id"], file.filename or "file")
    meta = upload_store.get_upload(env, created["id"], username) or created
    return upload_store.public_meta(meta)


def _parse(env: str, upload_id: str, filename: str) -> None:
    """Background extraction. Failures are recorded on the row, never raised."""
    try:
        result = upload_store.parse_upload(env, upload_id)
        logger.info("parsed upload %s (%s): %s", upload_id, filename, result.get("status"))
    except Exception:  # noqa: BLE001
        logger.exception("background parse crashed for upload %s (%s)", upload_id, filename)


@router.get("")
@router.get("/")
def list_uploads(conversation_id: str = "", env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    if not conversation_id:
        return {"uploads": []}
    return {"uploads": [upload_store.public_meta(m) for m in upload_store.list_uploads(env, username, conversation_id)]}


@router.get("/limits")
def upload_limits():
    """What the composer should accept, so the client and server cannot disagree."""
    return {
        "max_bytes": upload_store.max_upload_bytes(),
        "max_per_conversation": upload_store.max_per_conversation(),
        "extensions": sorted(file_extract.supported_extensions().keys()),
    }


@router.get("/{upload_id}")
def get_upload(upload_id: str, env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    meta = upload_store.get_upload(env, upload_id, username)
    if meta is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return upload_store.public_meta(meta)


@router.delete("/{upload_id}")
def delete_upload(upload_id: str, env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    if not upload_store.delete_upload(env, username, upload_id):
        raise HTTPException(status_code=404, detail="File not found.")
    return {"status": "deleted"}
