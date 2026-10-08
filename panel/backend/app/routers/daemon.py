"""NCPanel :: control del daemon NCam (estado y reinicio, solo super admin)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from .. import db as database
from .. import ncam
from ..security import AuthContext, client_ip, current_user, get_db, require_super_admin
from ..services import audit

router = APIRouter(prefix="/daemon", tags=["daemon"])


@router.get("/status")
def daemon_status(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Estado del daemon: alcance, versión y tiempo en marcha."""
    del ctx  # cualquier usuario autenticado puede ver el estado agregado
    status = ncam.fetch_status(conn)
    stats = ncam.fetch_cache_stats(conn) if status.get("reachable") else {"reachable": False}
    return {
        "reachable": bool(status.get("reachable")),
        "version": status.get("version"),
        "revision": status.get("revision"),
        "uptime": status.get("uptime"),
        "totals": status.get("totals", {}),
        "cache_engine": stats.get("engine") if stats.get("reachable") else None,
        "error": status.get("error") or stats.get("error"),
    }


@router.post("/restart")
def daemon_restart(
    request: Request,
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Ordena al daemon reiniciarse (solo super admin).

    El proceso sale y systemd lo levanta de nuevo en unos segundos; durante
    ese hueco los clientes se desconectan. Si NCam se arrancó a mano (sin
    systemd), sale y no vuelve solo.
    """
    with database.without_transaction(conn):
        result = ncam.restart_daemon(conn)
    audit(conn, ctx, "daemon.restart", "daemon", None, {"ok": result["ok"]}, client_ip(request))
    return result
