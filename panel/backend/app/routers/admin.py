"""NCam-NG Panel :: ajustes globales, auditoría y metadatos (super admin)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from .. import db as database
from ..config import settings
from ..models import SettingsUpdate
from ..security import AuthContext, ROLE_RESELLER, ROLE_SUPER_ADMIN, ROLE_USER, client_ip, current_user, get_db, require_super_admin
from ..services import audit, purge_snapshots, row_to_dict

router = APIRouter(tags=["admin"])

# ajustes que el panel permite modificar; el resto son internos
EDITABLE_SETTINGS = {
    "panel.name",
    "panel.public_host",
    "panel.port.cccam",
    "panel.port.newcamd",
    "panel.port.camd35",
    "panel.port.cacheex",
    "panel.ncam_webif_url",
    "panel.ncam_webif_user",
    "panel.ncam_webif_password",
    "ncam.cache.max_time",
    "ncam.cache.max_entries",
    "ncam.cache.cacheex_enable",
    "ncam.cache.panel_poll",
    "billing.line_cost",
    "billing.renew_cost",
    "billing.currency",
    # avisos de caducidad
    "notify.enabled",
    "notify.days_before",
    "notify.channel.email",
    "notify.channel.telegram",
    "notify.interval_seconds",
    "notify.smtp.host",
    "notify.smtp.port",
    "notify.smtp.user",
    "notify.smtp.password",
    "notify.smtp.from",
    "notify.smtp.starttls",
    "notify.telegram.bot_token",
    "notify.telegram.chat_id",
    # facturación por consumo de ECM
    "billing.ecm.enabled",
    "billing.ecm.price",
    "billing.ecm.block",
    "billing.ecm.interval_seconds",
    "billing.ecm.suspend_on_debt",
}

SECRET_SETTINGS = {"panel.ncam_webif_password", "notify.smtp.password", "notify.telegram.bot_token"}


@router.get("/meta")
def meta(ctx: AuthContext = Depends(current_user)):
    """Información para que el frontend sepa qué puede mostrar."""
    del ctx
    return {
        "panel_version": settings.version,
        "roles": [ROLE_SUPER_ADMIN, ROLE_RESELLER, ROLE_USER],
        "protocols": ["cccam", "newcamd", "camd35", "cacheex"],
        "cache_protocols": ["cccam", "camd35", "newcamd", "csp"],
        "export_formats": ["ncam", "cccam", "newcamd", "camd35", "json"],
        "features": [
            "roles:super_admin/reseller/user",
            "credits:ledger",
            "cache:engine-stats",
            "cache:peers",
            "cache:config-generator",
            "audit:logs",
            "auth:jwt+api-key",
            "notify:expiry-email",
            "notify:expiry-telegram",
            "billing:ecm-usage",
        ],
    }


@router.get("/settings")
def settings_index(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    values = database.get_settings(conn)
    if not ctx.is_super_admin:
        values = {key: value for key, value in values.items() if key not in SECRET_SETTINGS and not key.startswith("ncam.")}
    else:
        values = {key: ("***" if key in SECRET_SETTINGS and value else value) for key, value in values.items()}
    return {"items": values, "editable": sorted(EDITABLE_SETTINGS)}


@router.patch("/settings")
def settings_update(
    payload: SettingsUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    applied: dict[str, str] = {}
    rejected: list[str] = []
    for key, value in payload.values.items():
        if key not in EDITABLE_SETTINGS:
            rejected.append(key)
            continue
        database.set_setting(conn, key, str(value))
        applied[key] = str(value)

    audit(conn, ctx, "settings.update", "settings", None, {"applied": applied, "rejected": rejected}, client_ip(request))
    return {"applied": applied, "rejected": rejected}


@router.get("/audit-logs")
def audit_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    action: Optional[str] = Query(default=None, max_length=64),
    actor_id: Optional[int] = Query(default=None),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    sql = (
        "SELECT a.*, u.role AS actor_role FROM audit_logs a"
        " LEFT JOIN users u ON u.id = a.actor_id WHERE 1 = 1"
    )
    params: list = []
    if not ctx.is_super_admin:
        # un reseller ve sus acciones y las de sus usuarios
        sql += " AND (a.actor_id = ? OR a.actor_id IN (SELECT id FROM users WHERE parent_id = ?))"
        params.extend([ctx.id, ctx.id])
    if action:
        sql += " AND a.action LIKE ?"
        params.append(f"{action}%")
    if actor_id:
        sql += " AND a.actor_id = ?"
        params.append(actor_id)
    sql += " ORDER BY a.created_at DESC LIMIT ?"
    params.append(limit)

    rows = database.query(conn, sql, params)
    return {"items": [row_to_dict(row) for row in rows]}


@router.post("/maintenance/purge")
def maintenance_purge(
    days: int = Query(default=30, ge=1, le=365),
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Purga el histórico de métricas y los intentos de login antiguos."""
    removed = purge_snapshots(conn, days)
    cur = database.execute(
        conn, "DELETE FROM login_attempts WHERE created_at < datetime('now', ?)", (f"-{days} days",)
    )
    audit(conn, ctx, "maintenance.purge", "system", None, {"days": days, "removed": removed})
    return {"snapshots_removed": removed, "login_attempts_removed": cur.rowcount or 0}
