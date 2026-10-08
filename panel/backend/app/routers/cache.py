"""NCPanel :: motor de caché (estadísticas de NCam + peers cacheex)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status

from .. import db as database
from .. import ncam
from ..models import CacheServerCreate, CacheServerUpdate
from ..security import AuthContext, client_ip, current_user, get_db, require_super_admin
from ..services import (
    audit,
    create_cache_server,
    delete_cache_server,
    get_cache_server,
    list_cache_servers,
    record_cache_server_apply,
    record_snapshot,
    row_to_dict,
    timeseries,
    update_cache_server,
)

router = APIRouter(prefix="/cache", tags=["cache"])


@router.get("/stats")
def cache_stats(
    live: bool = Query(default=True),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Estado del motor de caché de NCam + último histórico guardado."""
    stats = ncam.fetch_cache_stats(conn) if live else {"reachable": False, "error": "consultas en vivo desactivadas"}
    status_info = ncam.fetch_status(conn) if live else {"reachable": False}

    if stats.get("reachable"):
        history = timeseries(conn, "cache.hit_ratio", hours=24, limit=240)
        stats["history"] = history
    else:
        stats["history"] = timeseries(conn, "cache.hit_ratio", hours=24, limit=240)

    if ctx.is_super_admin:
        peers = database.query(
            conn,
            "SELECT COUNT(*) AS total, SUM(CASE WHEN last_check_ok = 1 THEN 1 ELSE 0 END) AS online"
            " FROM cache_servers",
        )
    else:
        peers = database.query(
            conn,
            "SELECT COUNT(*) AS total, SUM(CASE WHEN last_check_ok = 1 THEN 1 ELSE 0 END) AS online"
            " FROM cache_servers WHERE owner_id = ?",
            (ctx.id,),
        )
    stats["peers"] = {
        "total": int(peers[0]["total"] or 0),
        "online": int(peers[0]["online"] or 0),
    }
    stats["daemon"] = status_info
    return stats


@router.post("/stats/snapshot")
def cache_snapshot(
    ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
):
    """Guarda una muestra de las métricas actuales (para los gráficos del panel)."""
    stats = ncam.fetch_cache_stats(conn)
    if not stats.get("reachable"):
        return {"saved": 0, "detail": stats.get("error")}

    metrics = {
        "cache.hit_ratio": stats["hit_ratio"],
        "cache.entries": stats["entries"],
        "cache.lookups": stats["lookups"],
        "cache.hits": stats["hits"],
        "cache.misses": stats["misses"],
        "cache.mem_bytes": stats["mem_bytes"],
    }
    saved = record_snapshot(conn, metrics, source=f"panel:{ctx.username}")
    audit(conn, ctx, "cache.snapshot", "cache", None, {"metrics": len(metrics)})
    return {"saved": saved, "metrics": metrics}


@router.get("/stats/history")
def cache_history(
    metric: str = Query(default="cache.hit_ratio", max_length=64),
    hours: int = Query(default=24, ge=1, le=720),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    del ctx  # cualquier usuario autenticado puede ver el histórico agregado
    return {"metric": metric, "items": timeseries(conn, metric, hours=hours)}


@router.get("/stats/reset")
def cache_stats_reset_note(ctx: AuthContext = Depends(current_user)):
    """Recordatorio: el reinicio de contadores se hace contra el WebIf de NCam."""
    del ctx
    return {
        "detail": "Para reiniciar los contadores del daemon use"
                  " GET /ncamapi.json?part=cachestats&action=reset (requiere permisos de escritura en el WebIf)"
    }


@router.get("/config")
def cache_config(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Bloques de configuración listos para ncam.conf / ncam.user / ncam.server."""
    owner_id = None if ctx.is_super_admin else ctx.id
    blocks = ncam.render_full_config(conn, owner_id)
    audit(conn, ctx, "cache.config_export", "cache", None, {})
    return {"blocks": blocks, "settings": database.get_settings(conn)}


@router.get("/config/download")
def cache_config_download(
    file: str = Query(default="ncam.conf", pattern=r"^(ncam\.conf|ncam\.user|ncam\.server)$"),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    owner_id = None if ctx.is_super_admin else ctx.id
    blocks = ncam.render_full_config(conn, owner_id)
    content = blocks.get(file, "")
    audit(conn, ctx, "cache.config_download", "cache", None, {"file": file})
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{file}"'},
    )


# ---------------------------------------------------------------------------
# peers de caché
# ---------------------------------------------------------------------------
@router.get("/servers")
def servers_index(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return {"items": list_cache_servers(conn, ctx)}


@router.post("/servers", status_code=status.HTTP_201_CREATED)
def servers_create(
    payload: CacheServerCreate,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    server = create_cache_server(conn, ctx, payload.model_dump())
    audit(
        conn,
        ctx,
        "cache_server.create.done",
        "cache_server",
        int(server["id"]),
        {"name": server["name"]},
        client_ip(request),
    )
    return row_to_dict(server, skip=("password",))


@router.get("/servers/{server_id}")
def servers_show(
    server_id: int, ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
):
    return row_to_dict(get_cache_server(conn, ctx, server_id), skip=("password",))


@router.patch("/servers/{server_id}")
def servers_update(
    server_id: int,
    payload: CacheServerUpdate,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    server = update_cache_server(conn, ctx, server_id, payload.model_dump(exclude_none=True))
    audit(conn, ctx, "cache_server.update.done", "cache_server", server_id, {}, client_ip(request))
    return row_to_dict(server, skip=("password",))


@router.delete("/servers/{server_id}")
def servers_delete(
    server_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    delete_cache_server(conn, ctx, server_id)
    audit(conn, ctx, "cache_server.delete.done", "cache_server", server_id, {}, client_ip(request))
    return {"detail": "Peer eliminado"}


@router.post("/servers/{server_id}/test")
def servers_test(
    server_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Prueba de conectividad TCP real contra el peer."""
    server = get_cache_server(conn, ctx, server_id)
    host, port = str(server["host"]), int(server["port"])
    # El sondeo tarda hasta segundos: corre fuera de la transacción de la
    # petición para que dos «Probar» a la vez no choquen con «database is
    # locked» (HTTP 500). La escritura posterior es corta y se confirma con
    # la auditoría al terminar la petición.
    with database.without_transaction(conn):
        ok, elapsed, error = ncam.probe_tcp(host, port)
    result = ncam.record_cache_server_check(conn, server_id, ok, elapsed, error)
    audit(
        conn,
        ctx,
        "cache_server.test",
        "cache_server",
        server_id,
        {"ok": result["ok"], "latency_ms": result["latency_ms"]},
        client_ip(request),
    )
    return {"id": server_id, "host": host, "port": port, **result}


@router.get("/servers/{server_id}/config")
def servers_config(
    server_id: int, ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
):
    server = get_cache_server(conn, ctx, server_id)
    return {"block": ncam.render_cache_peer_config(server)}


@router.post("/servers/{server_id}/apply")
def servers_apply(
    server_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Crea o actualiza el reader en el daemon NCam (solo super admin).

    El daemon lo aplica en memoria, reinicia el reader y persiste ncam.server.
    """
    server = get_cache_server(conn, ctx, server_id)
    label = ncam.peer_reader_label(server)
    params = ncam.peer_to_reader_params(server)
    with database.without_transaction(conn):
        result = ncam.apply_reader(conn, label, params)
    record_cache_server_apply(conn, server_id, bool(result["ok"]), str(result["message"]))
    audit(
        conn,
        ctx,
        "cache_server.apply",
        "cache_server",
        server_id,
        {"ok": result["ok"], "created": result.get("created"), "label": label},
        client_ip(request),
    )
    applied = row_to_dict(get_cache_server(conn, ctx, server_id), skip=("password",))
    return {"id": server_id, "label": label, **result, "server": applied}


@router.post("/settings/apply")
def cache_settings_apply(
    request: Request,
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Aplica la sección [cache] del panel en el daemon (solo super admin)."""
    applied_settings = {
        "max_time": int(database.get_setting(conn, "ncam.cache.max_time", "15") or 15),
        "max_entries": int(database.get_setting(conn, "ncam.cache.max_entries", "0") or 0),
        "cacheex_enable": database.get_setting(conn, "ncam.cache.cacheex_enable", "1") == "1",
    }
    with database.without_transaction(conn):
        result = ncam.apply_cache_section(conn, **applied_settings)
    audit(
        conn,
        ctx,
        "cache.settings_apply",
        "cache",
        None,
        {"ok": result["ok"], **applied_settings},
        client_ip(request),
    )
    return {"applied": applied_settings, **result}


@router.get("/limits")
def cache_limits(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Límites configurados en el panel para el motor de caché de NCam."""
    del ctx
    return {
        "max_time": int(database.get_setting(conn, "ncam.cache.max_time", "15") or 15),
        "max_entries": int(database.get_setting(conn, "ncam.cache.max_entries", "0") or 0),
        "cacheex_enabled": database.get_setting(conn, "ncam.cache.cacheex_enable", "1") == "1",
    }
