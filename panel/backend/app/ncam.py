"""
NCam-NG Panel :: integración con el daemon NCam.

* :func:`fetch_cache_stats` lee el endpoint ``/ncamapi.json?part=cachestats``
  añadido en esta versión (motor de caché v2: contadores, hit ratio, capacidad,
  CWs más servidas).
* :func:`fetch_status` obtiene el resumen general (usuarios, lectores, ECMs).
* Los generadores de configuración producen los bloques que se pegan en
  ``ncam.conf``/``ncam.user`` para las líneas y los peers de caché.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import sqlite3
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import settings
from . import db as database


class NcamUnavailable(RuntimeError):
    """El WebIf de NCam no responde o devuelve datos inválidos."""


def _to_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip() or 0)
        except ValueError:
            return 0.0
    return 0.0


def _to_int(value: Any) -> int:
    return int(_to_number(value))


def _webif_url(conn: Optional[sqlite3.Connection] = None) -> str:
    """URL del WebIf, con posibilidad de sobrescribirla desde los ajustes."""
    url = settings.ncam_webif_url
    if conn is not None:
        url = database.get_setting(conn, "panel.ncam_webif_url", url) or url
    return url.rstrip("/")


def _get_json(path: str, params: dict[str, str], timeout: Optional[float] = None,
              credentials: Optional[tuple[str, str]] = None,
              base_url: Optional[str] = None) -> dict[str, Any]:
    base = (base_url or _webif_url()).rstrip("/")
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params.items())
    url = f"{base}{path}?{query}" if query else f"{base}{path}"

    request = Request(url, headers={"Accept": "application/json", "User-Agent": "NCam-NG-Panel"})
    if credentials and credentials[0]:
        token = base64.b64encode(f"{credentials[0]}:{credentials[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")

    try:
        with urlopen(request, timeout=timeout or settings.ncam_timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise NcamUnavailable(f"NCam WebIf respondió HTTP {exc.code}") from exc
    except (URLError, socket.timeout, OSError) as exc:
        raise NcamUnavailable(f"No se pudo contactar el WebIf de NCam ({exc})") from exc

    try:
        # el WebIf puede devolver JSONP si se pasa callback
        if body.startswith("(") or body.lstrip().startswith("("):
            body = body.strip().lstrip("(").rstrip(")")
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise NcamUnavailable("El WebIf de NCam devolvió una respuesta no válida") from exc


def _credentials(conn: Optional[sqlite3.Connection] = None) -> tuple[str, str]:
    user, password = settings.ncam_webif_user, settings.ncam_webif_password
    if conn is not None:
        user = database.get_setting(conn, "panel.ncam_webif_user", user) or user
        password = database.get_setting(conn, "panel.ncam_webif_password", password) or password
    return user, password


def fetch_cache_stats(conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """Estadísticas del motor de caché de NCam (endpoint nativo part=cachestats)."""
    try:
        payload = _get_json(
            "/ncamapi.json",
            {"part": "cachestats"},
            credentials=_credentials(conn),
            base_url=_webif_url(conn),
        )
    except NcamUnavailable as exc:
        return {"reachable": False, "error": str(exc)}

    stats = ((payload or {}).get("ncam") or {}).get("cachestats")
    if not stats:
        return {
            "reachable": False,
            "error": "NCam no reportó 'cachestats' (se requiere NCam-NG con el motor de caché v2)",
        }

    hot_entries = []
    for entry in stats.get("hot_entries", []) or []:
        hot_entries.append(
            {
                "caid": str(entry.get("caid", "")),
                "prid": str(entry.get("prid", "")),
                "srvid": str(entry.get("srvid", "")),
                "hits": _to_int(entry.get("hits")),
                "from_csp": _to_int(entry.get("from_csp")),
                "from_cacheex": _to_int(entry.get("from_cacheex")),
                "from_localcards": _to_int(entry.get("from_localcards")),
            }
        )

    cw_cache = stats.get("cw_cache") or {}
    return {
        "reachable": True,
        "engine": str(stats.get("engine", "NCam-NG cache engine")),
        "limits": {
            "max_entries": _to_int(stats.get("max_entries")),
            "max_time_seconds": _to_int(stats.get("max_time")),
        },
        "entries": _to_int(stats.get("entries")),
        "cw_entries": _to_int(stats.get("cw_entries")),
        "mem_bytes": _to_int(stats.get("mem_bytes")),
        "lookups": _to_int(stats.get("lookups")),
        "hits": _to_int(stats.get("hits")),
        "misses": _to_int(stats.get("misses")),
        "hit_ratio": _to_number(stats.get("hit_ratio")),
        "cw_new": _to_int(stats.get("cw_new")),
        "cw_upd": _to_int(stats.get("cw_upd")),
        "cwc_rejected": _to_int(stats.get("cwc_rejected")),
        "evicted_ttl": _to_int(stats.get("evicted_ttl")),
        "evicted_lru": _to_int(stats.get("evicted_lru")),
        "cw_cache": {
            "entries": _to_int(cw_cache.get("entries")),
            "mem_bytes": _to_int(cw_cache.get("mem_bytes")),
            "localgenerated": _to_int(cw_cache.get("localgenerated")),
        },
        "hot_entries": hot_entries,
    }


def fetch_status(conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """Resumen del estado del daemon (cabecera del API + totales)."""
    try:
        payload = _get_json(
            "/ncamapi.json",
            {"part": "status"},
            credentials=_credentials(conn),
            base_url=_webif_url(conn),
        )
    except NcamUnavailable as exc:
        return {"reachable": False, "error": str(exc)}

    ncam = (payload or {}).get("ncam") or {}
    totals = ncam.get("totals") or {}
    status_block = ncam.get("status") or {}

    return {
        "reachable": True,
        "version": ncam.get("version"),
        "revision": ncam.get("revision"),
        "build": ncam.get("build"),
        "uptime": ncam.get("uptime"),
        "runtime": ncam.get("runtime"),
        "sysinfo": ncam.get("sysinfo") or {},
        "totals": {
            "users": _to_int(totals.get("total_users")),
            "active": _to_int(totals.get("total_active")),
            "connected": _to_int(totals.get("total_connected")),
            "online": _to_int(totals.get("total_online")),
            "ecm_ok": _to_int(totals.get("total_cwok")),
            "ecm_nok": _to_int(totals.get("total_cwnok")),
            "ecm_timeout": _to_int(totals.get("total_cwtout")),
            "from_cache": _to_int(totals.get("total_cwcache")),
        },
        "clients_shown": _to_int(status_block.get("ucs")),
        "readers_shown": _to_int(status_block.get("rcs")),
    }


def user_md5(username: str) -> str:
    """Identificador que usa el API de NCam para cada cuenta (``id_<md5>``)."""
    return "id_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def fetch_user_stats(conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """Estadísticas por cuenta del daemon (``part=userstats``).

    Devuelve ``{"reachable": bool, "users": {username: {...}}}``. El API identifica
    cada cuenta con ``id_<md5(usuario)>``, por lo que se traduce de vuelta al
    nombre real para poder cruzar los datos con las líneas del panel.
    """
    try:
        payload = _get_json(
            "/ncamapi.json",
            {"part": "userstats"},
            credentials=_credentials(conn),
            base_url=_webif_url(conn),
        )
    except NcamUnavailable as exc:
        return {"reachable": False, "error": str(exc), "users": {}}

    ncam = (payload or {}).get("ncam") or {}
    users: dict[str, dict[str, Any]] = {}
    for entry in ncam.get("users") or []:
        block = entry.get("user") if isinstance(entry, dict) else None
        if not isinstance(block, dict):
            continue
        md5id = str(block.get("usermd5") or "")
        stats = block.get("stats") or {}
        users[md5id] = {
            "status": block.get("status"),
            "classname": block.get("classname"),
            "expdate": block.get("expdate"),
            "groups": block.get("groups"),
            "ecm_ok": _to_int(stats.get("cwok")),
            "ecm_nok": _to_int(stats.get("cwnok")),
            "ecm_from_cache": _to_int(stats.get("cwcache")),
            "ecm_timeout": _to_int(stats.get("cwtimeout")),
            "emm_ok": _to_int(stats.get("emmok")),
            "emm_nok": _to_int(stats.get("emmnok")),
        }

    return {
        "reachable": True,
        "version": ncam.get("version"),
        "revision": ncam.get("revision"),
        "users": users,
    }


def probe_tcp(host: str, port: int, timeout: float = 3.0) -> tuple[bool, Optional[int], Optional[str]]:
    """Comprueba la conectividad TCP con un peer de caché."""
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            elapsed = int((time.monotonic() - started) * 1000)
            return True, elapsed, None
    except OSError as exc:
        return False, None, str(exc)


def check_cache_server(conn: sqlite3.Connection, server_id: int, host: str, port: int) -> dict[str, Any]:
    ok, elapsed, error = probe_tcp(host, port)
    database.execute(
        conn,
        "UPDATE cache_servers SET last_check_at = ?, last_check_ok = ?, last_check_ms = ?,"
        " last_check_error = ? WHERE id = ?",
        (database.utcnow(), 1 if ok else 0, elapsed, error, server_id),
    )
    return {"ok": ok, "latency_ms": elapsed, "error": error}


# ---------------------------------------------------------------------------
# generadores de configuración
# ---------------------------------------------------------------------------
def render_account_config(line: sqlite3.Row | dict[str, Any]) -> str:
    """Bloque ``[account]`` para ncam.user (línea de cliente)."""
    data = dict(line)
    entries: list[tuple[str, str]] = [
        ("user", str(data["username"])),
        ("pwd", str(data["password"])),
        ("group", str(data.get("group_name") or "1")),
        ("uniq", "1"),
        ("sleep", "0"),
        ("monlevel", "1"),
        ("au", "1"),
    ]
    if int(data.get("cacheex_mode") or 0) > 0:
        entries.append(("cacheex", str(data["cacheex_mode"])))
        if int(data.get("cacheex_maxhop") or 0) > 0:
            entries.append(("cacheex_maxhop", str(data["cacheex_maxhop"])))
    if int(data.get("cacheex_disable") or 0):
        entries.append(("cacheex_disable", "1"))
    if int(data.get("max_connections") or 0) > 0:
        entries.append(("cccmaxhops", "1"))

    header = f"# Línea '{data.get('name')}' ({data.get('protocol')}) - panel NCam-NG"
    body = "\n".join(f"{key:<16} = {value}" for key, value in entries)
    return f"{header}\n[account]\n{body}\n"


def render_cache_peer_config(server: sqlite3.Row | dict[str, Any], username: Optional[str] = None) -> str:
    """Bloque ``[reader]`` para conectar con un peer de caché remoto."""
    data = dict(server)
    protocol = str(data.get("protocol") or "cccam")
    label = str(data.get("name") or "cacheex_peer").replace(" ", "_")
    lines = [
        f"# Peer de caché '{data.get('name')}' - panel NCam-NG",
        "[reader]",
        f"label           = {label}",
        f"protocol        = {protocol}",
        f"device          = {data.get('host')},{data.get('port')}",
    ]
    if data.get("username"):
        lines.append(f"user            = {data['username']}")
    if data.get("password"):
        lines.append(f"password        = {data['password']}")
    if data.get("node_id"):
        lines.append(f"caid            = {data['node_id']}")
    lines.extend(
        [
            "group           = 1",
            "cachex          = 3",
            "cachex_mode     = 1",
            "cachex_maxhop   = 2",
            f"priority        = {int(data.get('priority') or 0)}",
            f"enable          = {1 if int(data.get('enabled', 1)) else 0}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_cache_section(conn: sqlite3.Connection) -> str:
    """Sección ``[cache]`` recomendada, alimentada por los ajustes del panel."""
    max_time = database.get_setting(conn, "ncam.cache.max_time", "15")
    max_entries = database.get_setting(conn, "ncam.cache.max_entries", "0")
    cacheex = database.get_setting(conn, "ncam.cache.cacheex_enable", "1")
    lines = [
        "# Motor de caché - generado por el panel NCam-NG",
        "[cache]",
        "delay           = 120",
        f"max_time        = {max_time}",
        f"max_entries     = {max_entries}",
        "max_hit_time    = 15",
        "wait_time       = 0",
        "cacheexenablestats = 1",
    ]
    if str(cacheex) in {"1", "true", "yes"}:
        lines.extend(["cacheex_dropdiffs = 0", "cacheex_localgenerated_only = 0"])
    return "\n".join(lines) + "\n"


def render_full_config(conn: sqlite3.Connection, ctx_owner_id: Optional[int] = None) -> dict[str, str]:
    """Devuelve todos los bloques listos para copiar en ncam.conf/ncam.user."""
    params: tuple[Any, ...] = ()
    sql = "SELECT * FROM lines WHERE status = 'active'"
    if ctx_owner_id is not None:
        sql += " AND owner_id = ?"
        params = (ctx_owner_id,)

    accounts = [
        render_account_config(row) for row in database.query(conn, sql + " ORDER BY owner_id, name", params)
    ]

    sql_servers = "SELECT * FROM cache_servers WHERE enabled = 1"
    if ctx_owner_id is not None:
        sql_servers += " AND owner_id = ?"
    peers = [
        render_cache_peer_config(row)
        for row in database.query(conn, sql_servers + " ORDER BY priority DESC, name", params)
    ]

    return {
        "ncam.user": "\n".join(accounts),
        "ncam.server": "\n".join(peers),
        "ncam.conf": render_cache_section(conn),
    }


def export_line(
    line: sqlite3.Row | dict[str, Any], fmt: str = "ncam", conn: Optional[sqlite3.Connection] = None
) -> str:
    """Exporta una línea en el formato que espera cada tipo de cliente.

    El hostname que se publica a los clientes se toma del ajuste
    ``panel.public_host`` y los puertos de ``panel.port.<protocolo>``.
    """
    data = dict(line)
    protocol = str(data.get("protocol") or "cccam")
    username, password = str(data["username"]), str(data["password"])

    host = "TU_SERVIDOR"
    port = {"cccam": 12000, "newcamd": 50000, "camd35": 33333, "cacheex": 8181}.get(protocol, 12000)
    if conn is not None:
        host = database.get_setting(conn, "panel.public_host", host) or host
        port = int(database.get_setting(conn, f"panel.port.{protocol}", str(port)) or port)

    if fmt == "ncam":
        return render_account_config(data)
    if fmt == "cccam":
        return (
            f"C: {host} {port} {username} {password} yes\n"
            f"# línea '{data.get('name')}' (panel NCam-NG)"
        )
    if fmt == "newcamd":
        return f"N: {host} {port} {username} {password} 01 02 03 04 05 06 07 08 09 10 11 12 13 14\n"
    if fmt == "camd35":
        return f"{host} {port} {username} {password}\n"
    if fmt == "json":
        return json.dumps(
            {
                "host": host,
                "port": port,
                "protocol": protocol,
                "username": username,
                "password": password,
                "expires_at": data.get("expires_at"),
                "max_connections": data.get("max_connections"),
            },
            indent=2,
        )
    raise ValueError(f"Formato no soportado: {fmt}")
