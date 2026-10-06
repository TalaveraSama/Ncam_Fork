"""NCPanel :: estadísticas agregadas."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from .. import db as database
from .. import ncam
from ..security import AuthContext, current_user, get_db
from ..services import overview, row_to_dict, timeseries

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
def stats_overview(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    data = overview(conn, ctx)
    data["ncam"] = ncam.fetch_status(conn)
    data["cache"] = {
        "hit_ratio": timeseries(conn, "cache.hit_ratio", hours=1, limit=1)[-1:] or [],
        "snapshots_24h": len(timeseries(conn, "cache.hit_ratio", hours=24, limit=1000)),
    }
    return data


@router.get("/expiring")
def stats_expiring(
    days: int = Query(default=7, ge=1, le=90),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Líneas que caducan pronto (para avisar a los clientes)."""
    sql = (
        "SELECT l.*, u.username AS owner_username FROM lines l JOIN users u ON u.id = l.owner_id"
        " WHERE l.expires_at IS NOT NULL AND l.expires_at <= datetime('now', ?)"
    )
    params: list = [f"+{days} days"]
    if not ctx.is_super_admin:
        sql += " AND (l.owner_id = ? OR l.owner_id IN (SELECT id FROM users WHERE parent_id = ?))"
        params.extend([ctx.id, ctx.id])
    sql += " ORDER BY l.expires_at ASC LIMIT 200"
    rows = database.query(conn, sql, params)
    return {
        "days": days,
        "items": [{**(row_to_dict(row) or {}), "password": None} for row in rows],
    }


@router.get("/timeseries")
def stats_timeseries(
    metric: str = Query(default="cache.hit_ratio", max_length=64),
    hours: int = Query(default=24, ge=1, le=720),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    del ctx
    return {"metric": metric, "items": timeseries(conn, metric, hours=hours)}
