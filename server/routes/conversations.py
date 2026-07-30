"""Conversation history for the assistant drawer.

The transcript itself is written by the chat route as turns complete (see
`agent_proxy.proxy_chat`); these endpoints are what the history dropdown reads,
renames and deletes. Everything is scoped to the calling user — a conversation is
private to whoever had it, with no sharing model on purpose.
"""

import logging
from typing import Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import get_db_client
from routes.roles import _get_current_username
from services import conversation_store as store

router = APIRouter()

logger = logging.getLogger(__name__)


class NewConversation(BaseModel):
    id: Optional[str] = None
    profile_id: Optional[str] = ""


class RenameConversation(BaseModel):
    title: str


@router.get("")
@router.get("/")
def list_conversations(env: str = "dev", limit: int = 50, w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    return {"conversations": store.list_conversations(env, username, limit)}


@router.post("")
@router.post("/")
def create_conversation(body: NewConversation, env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    """Start a conversation.

    The drawer generates the id so it can attach files and render before the first
    turn is sent; passing it here keeps both sides on the same id.
    """
    username = _get_current_username(w)
    created = store.create_conversation(env, username, body.profile_id or "", conversation_id=body.id)
    # Opening a new conversation is the natural moment to tidy old ones up: it is
    # off the hot path of answering, and it is when the list just grew.
    try:
        store.prune_conversations(env, username)
    except Exception as e:  # noqa: BLE001
        logger.warning("pruning conversations for %s failed: %s", username, e)
    return created


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    bundle = store.read_conversation(env, username, conversation_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    from services import upload_store

    meta, messages, uploads = bundle
    return {
        "conversation": meta,
        "messages": messages,
        # Files stay attached for the life of the conversation, so a restored one
        # shows its chips and the agent can still query what was uploaded.
        "attachments": [upload_store.public_meta(u) for u in uploads],
    }


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, body: RenameConversation, env: str = "dev",
                        w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    if not store.rename_conversation(env, username, conversation_id, body.title):
        raise HTTPException(status_code=404, detail="Conversation not found, or the title was empty.")
    return {"status": "ok", "title": body.title.strip()}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    username = _get_current_username(w)
    if not store.delete_conversation(env, username, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "deleted"}
