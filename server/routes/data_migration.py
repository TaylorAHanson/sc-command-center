"""Admin Panel → Data Migration: snapshot this app's data, or load another app's.

The mechanism and its trade-offs are in `services/data_migration.py`. This module
is the HTTP edge: who may do it (global admins of the env involved), which
connection each part goes through, and the one guard a replace needs that a merge
doesn't — not deleting the importer's own admin access.

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
from database import _schema_for, get_db_connection, log_user_action
from middleware.auth import get_db_client
from routes.roles import _get_current_username, _permissions_disabled, get_user_entitlements, require_global_admin
from services import data_migration as dm
from services import settings_store

router = APIRouter()
logger = logging.getLogger(__name__)

ENVS = ("dev", "test", "prod")

#: Largest snapshot accepted, compressed or not. Held in memory while it is
#: parsed, so this is a memory bound as much as an upload one.
MAX_MB = int(os.environ.get("MIGRATION_MAX_MB", "512"))


def _check_env(env: str) -> str:
    env = (env or "").strip().lower()
    if env not in ENVS:
        raise HTTPException(status_code=400, detail=f"env must be one of {', '.join(ENVS)}")
    return env


def _groups(raw: Optional[str]) -> List[str]:
    if raw is None or not raw.strip():
        return [g["key"] for g in dm.GROUPS if g["default"]]
    picked = [g.strip() for g in raw.split(",") if g.strip()]
    unknown = [g for g in picked if g not in dm.GROUP_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown group(s): {', '.join(unknown)}")
    return picked


def _source(env: str) -> Dict[str, Any]:
    """Where a snapshot came from, recorded in the file for whoever imports it."""
    return {
        "app_environment": get_app_environment() or "local",
        "env": env,
        "schema": _schema_for(env) or "public",
        "instance": os.environ.get("LAKEBASE_INSTANCE_NAME", ""),
        "settings_env": settings_store.settings_env(),
    }


def _partition(specs: List[dm.TableSpec], env: str) -> Dict[str, List[dm.TableSpec]]:
    """Which env's schema each table is read from or written to.

    Settings are deployment-global and live in `APP_SETTINGS_ENV`'s schema whatever
    env the rest of the data is in (see `settings_store`), so `app_settings` goes
    wherever that is — otherwise an import would write settings into a schema
    nothing reads them from.
    """
    settings_env = settings_store.settings_env()
    out: Dict[str, List[dm.TableSpec]] = {}
    for spec in specs:
        target = settings_env if spec.group == "settings" else env
        out.setdefault(target, []).append(spec)
    return out


@router.get("/groups")
def list_groups(env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    env = _check_env(env)
    require_global_admin(w, env)
    return {"groups": dm.GROUPS, "modes": list(dm.MODES), "this_app": _source(env)}


@router.get("/summary")
def summary(env: str = "dev", w: WorkspaceClient = Depends(get_db_client)):
    """What an export of `env` would contain, table by table."""
    env = _check_env(env)
    require_global_admin(w, env)
    tables: List[Dict[str, Any]] = []
    for target, specs in _partition(dm.TABLES, env).items():
        conn = get_db_connection(target)
        try:
            tables.extend(dm.summarize(conn.cursor(), [s.group for s in specs]))
        finally:
            conn.close()
    order = {s.name: i for i, s in enumerate(dm.TABLES)}
    tables.sort(key=lambda t: order.get(t["table"], 99))
    return {"env": env, "tables": tables, "this_app": _source(env)}


@router.get("/export")
def export_snapshot(env: str = "dev", groups: Optional[str] = None,
                    w: WorkspaceClient = Depends(get_db_client)):
    env = _check_env(env)
    require_global_admin(w, env)
    picked = _groups(groups)
    username = _get_current_username(w)

    tables: Dict[str, Any] = {}
    for target, specs in _partition(dm.tables_for(picked), env).items():
        conn = get_db_connection(target)
        try:
            tables.update(dm.export_tables(conn.cursor(), specs))
            conn.rollback()  # read-only; end the transaction before the pool takes it back
        finally:
            conn.close()

    source = _source(env)
    document = dm.snapshot_document(tables, groups=picked, source=source, exported_by=username)
    body = gzip.compress(json.dumps(document, separators=(",", ":"), default=str).encode("utf-8"))
    counts = {name: len(t["rows"]) for name, t in tables.items()}
    logger.warning("Data snapshot exported by %s: env=%s groups=%s rows=%s",
                   username, env, ",".join(picked), counts)
    _audit(env, username, "export_snapshot",
           f"Exported a data snapshot of {env} ({', '.join(picked)}).", {"rows": counts, "source": source})

    stamp = document["exported_at"][:10]
    filename = f"command-center-{source['app_environment']}-{env}-{stamp}.json.gz"
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


def _still_admin(cur, w: WorkspaceClient) -> bool:
    """Whether the importer would still be a global admin, read inside the import.

    Replacing role mappings replaces the target's access control with the
    source's. If the source's doesn't include the person importing, they finish
    the import locked out of the Admin Panel they did it from, and with checks on
    nobody may be left who can fix it. Checked against the uncommitted rows, so a
    replace that would do that is rolled back instead.
    """
    if _permissions_disabled() or os.environ.get("DEV_MODE", "").lower() == "true":
        return True
    names = list(get_user_entitlements(w)) + [_get_current_username(w)]
    cur.execute(
        "SELECT 1 FROM role_mappings WHERE external_role = ANY(%s) "
        "AND LOWER(domain) IN ('global', 'all', 'app') AND permission_level = 'admin' LIMIT 1",
        (names,),
    )
    return cur.fetchone() is not None


@router.post("/import")
def import_snapshot(
    file: UploadFile = File(...),
    env: str = Form("dev"),
    mode: str = Form("merge"),
    groups: Optional[str] = Form(None),
    dry_run: bool = Form(True),
    w: WorkspaceClient = Depends(get_db_client),
):
    """Load a snapshot into this app. `dry_run` (the default) previews it.

    A preview runs the real import and rolls it back, so the counts it reports are
    what an import would do, not a guess at it.
    """
    env = _check_env(env)
    require_global_admin(w, env)
    if mode not in dm.MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(dm.MODES)}")
    snapshot = _read_snapshot(file)
    picked = _groups(groups)
    username = _get_current_username(w)
    ignored = sorted(t for t in snapshot["tables"] if t not in dm.SPECS)

    report: List[Dict[str, Any]] = []
    connections = []
    try:
        # One unpooled connection per schema touched, each holding its transaction
        # open until every part has succeeded, so a failure in the settings schema
        # also undoes the main import. (Two schemas cannot share one transaction on
        # the legacy layout, where each env is its own database; this is as close
        # as that layout allows.)
        for target, specs in _partition(dm.tables_for(picked), env).items():
            conn = get_db_connection(target, pooled=False)
            connections.append(conn)
            cur = conn.cursor()
            report.extend(dm.import_tables(cur, snapshot["tables"], specs, mode))
            if target == env and mode == "replace" and "access" in picked and not _still_admin(cur, w):
                raise HTTPException(status_code=409, detail=(
                    "This import would replace the role mappings with ones that don't make you a "
                    "global admin, locking you out of this page. Add your group as a global admin "
                    "in the source app and export again, or import with Merge."
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
        logger.exception("Data snapshot import failed (env=%s mode=%s)", env, mode)
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
        # Settings are cached for a few seconds per worker; this worker at least
        # should show the imported ones at once.
        settings_store.invalidate()
        logger.warning("Data snapshot imported by %s: env=%s mode=%s groups=%s totals=%s source=%s",
                       username, env, mode, ",".join(picked), totals, snapshot.get("source"))
        _audit(env, username, "import_snapshot",
               f"Imported a data snapshot into {env} ({mode}; {', '.join(picked)}).",
               {"totals": totals, "source": snapshot.get("source"),
                "exported_at": snapshot.get("exported_at"), "exported_by": snapshot.get("exported_by")})

    return {
        "dry_run": dry_run,
        "env": env,
        "mode": mode,
        "groups": picked,
        "tables": report,
        "totals": totals,
        "ignored_tables": ignored,
        "snapshot": {k: snapshot.get(k) for k in ("exported_at", "exported_by", "source", "groups")},
    }


def _audit(env: str, username: str, action: str, explanation: str, context: Dict[str, Any]) -> None:
    """Put the migration in Action Logs, next to every other consequential act.

    Moving a deployment's data is exactly the kind of thing the audit trail is
    for. Best effort: a failed log line must not undo a migration that succeeded.
    """
    try:
        log_user_action(
            widget_id="data-migration", widget_name="Data migration", explanation=explanation,
            context=json.dumps(context, default=str), action_name=action, username=username, env=env,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record %s in action_logs: %s", action, exc)
