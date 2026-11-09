"""Admin Panel → Data Migration: snapshot this app's data, or load another app's.

The mechanism and its trade-offs are in `services/data_migration.py`. This module
is the HTTP edge: who may do it (app administrators), which connection each part
goes through, and the one guard a replace needs that a merge doesn't — not
deleting the importer's own admin access.

Every route is a sync `def`. An export or import is seconds of blocking psycopg2
work, and on the event loop it would stall every other request, the chat
stream included.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import os
from typing import Any, Dict, List, Optional

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from config.settings import get_app_environment
from database import _schema_for, content_env, get_db_connection, log_user_action
from middleware.auth import get_db_client
from services import access, access_migration
from services import data_migration as dm
from services import settings_store

router = APIRouter()
logger = logging.getLogger(__name__)

#: Largest snapshot accepted, compressed or not. Held in memory while it is
#: parsed, so this is a memory bound as much as an upload one.
MAX_MB = int(os.environ.get("MIGRATION_MAX_MB", "512"))


def _groups(raw: Optional[str]) -> List[str]:
    if raw is None or not raw.strip():
        return [g["key"] for g in dm.GROUPS if g["default"]]
    picked = [g.strip() for g in raw.split(",") if g.strip()]
    unknown = [g for g in picked if g not in dm.GROUP_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown group(s): {', '.join(unknown)}")
    return picked


def _source() -> Dict[str, Any]:
    """Where a snapshot came from, recorded in the file for whoever imports it."""
    content, settings = content_env(), settings_store.settings_env()
    return {
        "app_environment": get_app_environment() or "local",
        "content_env": content,
        "schema": _schema_for(content) or "public",
        "settings_env": settings,
        "settings_schema": _schema_for(settings) or "public",
        "instance": os.environ.get("LAKEBASE_INSTANCE_NAME", ""),
    }


def _stores(specs: List[dm.TableSpec]) -> List[tuple]:
    """(env, specs) for each store the tables live in: the content store, then settings.

    Physical, because `settings_env()` names a real schema — usually `dev` — and
    the default mapping would send it to the content store, where nothing reads
    access lists or settings from.
    """
    content, settings = dm.partition(specs)
    return [(env, part) for env, part in ((content_env(), content), (settings_store.settings_env(), settings)) if part]


@router.get("/groups")
def list_groups(w: WorkspaceClient = Depends(get_db_client)):
    access.require_app_admin(w)
    return {"groups": dm.GROUPS, "modes": list(dm.MODES), "this_app": _source()}


@router.get("/summary")
def summary(w: WorkspaceClient = Depends(get_db_client)):
    """What an export would contain, table by table."""
    access.require_app_admin(w)
    tables: List[Dict[str, Any]] = []
    for env, specs in _stores(dm.TABLES):
        conn = get_db_connection(env, physical=True)
        try:
            tables.extend(dm.summarize(conn.cursor(), specs))
            conn.rollback()
        finally:
            conn.close()
    order = {s.name: i for i, s in enumerate(dm.TABLES)}
    tables.sort(key=lambda t: order.get(t["table"], 99))
    return {"tables": tables, "this_app": _source()}


@router.get("/export")
def export_snapshot(groups: Optional[str] = None, w: WorkspaceClient = Depends(get_db_client)):
    who = access.require_app_admin(w)
    picked = _groups(groups)
    username = who.username

    tables: Dict[str, Any] = {}
    for env, specs in _stores(dm.tables_for(picked)):
        conn = get_db_connection(env, physical=True)
        try:
            tables.update(dm.export_tables(conn.cursor(), specs))
            conn.rollback()  # read-only; end the transaction before the pool takes it back
        finally:
            conn.close()

    source = _source()
    document = dm.snapshot_document(tables, groups=picked, source=source, exported_by=username)
    body = gzip.compress(json.dumps(document, separators=(",", ":"), default=str).encode("utf-8"))
    counts = {name: len(t["rows"]) for name, t in tables.items()}
    logger.warning("Data snapshot exported by %s: groups=%s rows=%s", username, ",".join(picked), counts)
    _audit(username, "export_snapshot", f"Exported a data snapshot ({', '.join(picked)}).",
           {"rows": counts, "source": source})

    stamp = document["exported_at"][:10]
    filename = f"command-center-{source['app_environment']}-{stamp}.json.gz"
    return Response(
        content=body,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _read_snapshot(file: UploadFile) -> Dict[str, Any]:
    limit = MAX_MB * 1024 * 1024
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail=f"Snapshot is larger than {MAX_MB} MB (MIGRATION_MAX_MB).")
    if raw[:2] == b"\x1f\x8b":
        try:
            # Read through a bound rather than `gzip.decompress`: a small file can
            # inflate to far more than the limit above.
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(limit + 1)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Could not decompress the snapshot: {exc}")
        if len(raw) > limit:
            raise HTTPException(status_code=413, detail=f"Snapshot expands to more than {MAX_MB} MB (MIGRATION_MAX_MB).")
    try:
        snapshot = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Not a readable snapshot: {exc}")
    problems = dm.validate_snapshot(snapshot)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    return snapshot


def legacy_tables(snapshot: Dict[str, Any], picked: List[str]) -> tuple:
    """(tables to import, notes) for a snapshot, converting one from before sharing.

    A format-1 file carries role mappings and no access lists; imported as it
    stands, everything in it would be reachable by administrators alone.
    """
    tables = snapshot["tables"]
    notes: List[str] = []
    if int(snapshot.get("format_version") or 1) >= 2:
        return tables, notes
    old_env = (snapshot.get("source") or {}).get("env")
    if old_env and old_env != content_env():
        notes.append(f"This snapshot is of the old {old_env.capitalize()} workspace. What it holds is imported as "
                     "published, like everything else here; preview first.")
    if "access" in picked and "object_permissions" not in tables:
        tables = {**tables, **access_migration.tables_from_legacy_snapshot(tables)}
        notes.append("This snapshot is from before sharing: its role mappings were turned into access lists and "
                     "administrators, the way this app's own were.")
    return tables, notes


def _still_admin(cur, who: access.Caller) -> bool:
    """Whether the importer would still be an app admin, read inside the import.

    Replacing the administrators replaces the target's access control with the
    source's. If the source's doesn't include the person importing, they finish
    the import locked out of the Admin Panel they did it from, and with checks on
    nobody may be left who can fix it. Checked against the uncommitted rows, so a
    replace that would do that is rolled back instead.
    """
    if access.permissions_disabled() or os.environ.get("DEV_MODE", "").lower() == "true":
        return True
    cur.execute("SELECT principal, principal_type FROM app_admins")
    rows = cur.fetchall()
    return any(access.matches(*(tuple(r.values()) if hasattr(r, "keys") else tuple(r))[:2], who.username, who.groups)
               for r in rows)


@router.post("/import")
def import_snapshot(
    file: UploadFile = File(...),
    mode: str = Form("merge"),
    groups: Optional[str] = Form(None),
    dry_run: bool = Form(True),
    w: WorkspaceClient = Depends(get_db_client),
):
    """Load a snapshot into this app. `dry_run` (the default) previews it.

    A preview runs the real import and rolls it back, so the counts it reports are
    what an import would do, not a guess at it.
    """
    who = access.require_app_admin(w)
    if mode not in dm.MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(dm.MODES)}")
    snapshot = _read_snapshot(file)
    picked = _groups(groups)
    username = who.username
    tables, notes = legacy_tables(snapshot, picked)
    ignored = sorted(t for t in snapshot["tables"] if t not in dm.SPECS and t not in dm.LEGACY_TABLES)

    report: List[Dict[str, Any]] = []
    connections = []
    try:
        # One unpooled connection per store touched, each holding its transaction
        # open until every part has succeeded, so a failure in the settings schema
        # also undoes the content import. (Two schemas cannot share one transaction
        # on the legacy layout, where each env is its own database; this is as
        # close as that layout allows.)
        for env, specs in _stores(dm.tables_for(picked)):
            conn = get_db_connection(env, pooled=False, physical=True)
            connections.append(conn)
            cur = conn.cursor()
            report.extend(dm.import_tables(cur, tables, specs, mode))
            replaces_admins = mode == "replace" and "app_admins" in tables and any(s.name == "app_admins" for s in specs)
            if replaces_admins and not _still_admin(cur, who):
                raise HTTPException(status_code=409, detail=(
                    "This import would replace the administrators with ones that don't include you, locking "
                    "you out of this page. Make yourself or your group an administrator in the source app and "
                    "export again, or import with Merge."
                ))
        for conn in connections:
            if dry_run:
                conn.rollback()
            else:
                conn.commit()
    except HTTPException:
        for conn in connections:
            conn.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        for conn in connections:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
        logger.exception("Data snapshot import failed (mode=%s)", mode)
        raise HTTPException(status_code=500, detail=f"Import failed and nothing was changed: {exc}")
    finally:
        for conn in connections:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    order = {s.name: i for i, s in enumerate(dm.TABLES)}
    report.sort(key=lambda r: order.get(r["table"], 99))
    totals = {k: sum(r[k] for r in report) for k in ("in_file", "inserted", "skipped", "deleted")}
    if not dry_run:
        # Settings and the admin list are cached for a few seconds per worker;
        # this worker at least should show the imported ones at once.
        settings_store.invalidate()
        access._forget_admins()
        logger.warning("Data snapshot imported by %s: mode=%s groups=%s totals=%s source=%s",
                       username, mode, ",".join(picked), totals, snapshot.get("source"))
        _audit(username, "import_snapshot", f"Imported a data snapshot ({mode}; {', '.join(picked)}).",
               {"totals": totals, "source": snapshot.get("source"),
                "exported_at": snapshot.get("exported_at"), "exported_by": snapshot.get("exported_by")})

    return {
        "dry_run": dry_run,
        "mode": mode,
        "groups": picked,
        "tables": report,
        "totals": totals,
        "ignored_tables": ignored,
        "notes": notes,
        "snapshot": {k: snapshot.get(k) for k in ("exported_at", "exported_by", "source", "groups", "format_version")},
    }


def _audit(username: str, action: str, explanation: str, context: Dict[str, Any]) -> None:
    """Put the migration in Action Logs, next to every other consequential act.

    Moving a deployment's data is exactly the kind of thing the audit trail is
    for. Best effort: a failed log line must not undo a migration that succeeded.
    """
    try:
        log_user_action(
            widget_id="data-migration", widget_name="Data migration", explanation=explanation,
            context=json.dumps(context, default=str), action_name=action, username=username, env=content_env(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record %s in action_logs: %s", action, exc)
