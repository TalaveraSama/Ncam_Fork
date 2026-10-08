"""
NCPanel :: integración con el daemon NCam.

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
import re
import socket
import sqlite3
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
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


def _origen_del_panel(base_url: str) -> str:
    """Dirección desde la que el panel se conecta al WebIf.

    Sirve para el aviso de HTTP 403: el daemon solo atiende a las IPs (o dominios)
    de ``httpallowed``/``httpdyndns`` y esas IPs son las de *quien se conecta*, así
    que la que hay que permitir es la del panel (``127.0.0.1`` si va en la misma
    máquina que el daemon).
    """
    host = urlsplit(base_url).hostname or ""
    if not host or host.lower() in {"localhost", "127.0.0.1", "::1"}:
        return "127.0.0.1"
    return host


def _parse_digest_challenge(header: str) -> dict[str, str]:
    """Extrae los parámetros de una cabecera ``WWW-Authenticate: Digest ...``."""
    if not header or not header.lower().startswith("digest"):
        return {}
    challenge: dict[str, str] = {}
    for part in header[len("Digest"):].split(","):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        challenge[key.strip().lower()] = value.strip().strip('"')
    return challenge


def _digest_authorization(
    username: str, password: str, method: str, uri: str, challenge: dict[str, str]
) -> str:
    """Calcula la cabecera de autenticación Digest (MD5) que espera el WebIf de NCam.

    El daemon aplica RFC 2617 con ``qop="auth"`` y realm propio (``Forbidden``).
    """
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    opaque = challenge.get("opaque", "")
    qop = (challenge.get("qop") or "auth").split(",")[0].strip() or "auth"
    algorithm = (challenge.get("algorithm") or "MD5").upper()

    def _md5(data: str) -> str:
        return hashlib.md5(data.encode("utf-8")).hexdigest()

    cnonce = hashlib.md5(f"{time.time()}{nonce}{username}".encode()).hexdigest()[:16]
    nc = "00000001"
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    if qop in ("auth", "auth-int"):
        response = _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        response = _md5(f"{ha1}:{nonce}:{ha2}")

    parts = [f'username="{username}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"']
    if algorithm:
        parts.append(f"algorithm={algorithm}")
    if qop:
        parts += [f"qop={qop}", f"nc={nc}", f'cnonce="{cnonce}"']
    if opaque:
        parts.append(f'opaque="{opaque}"')
    parts.append(f'response="{response}"')
    return "Digest " + ", ".join(parts)


def _fetch_text(path: str, params: dict[str, str], timeout: Optional[float] = None,
                credentials: Optional[tuple[str, str]] = None,
                base_url: Optional[str] = None) -> str:
    """GET al WebIf con autenticación (Basic y reto Digest MD5).

    Devuelve el cuerpo como texto; las lecturas JSON (func:`_get_json`) y las
    páginas HTML de control (guardar reader/cuenta, reiniciar) comparten este
    transporte. Lanza :class:`NcamUnavailable` con el motivo legible.
    """
    base = (base_url or _webif_url()).rstrip("/")
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params.items())
    url = f"{base}{path}?{query}" if query else f"{base}{path}"
    request_uri = f"{path}?{query}" if query else path

    def _fetch(authorization: Optional[str] = None) -> str:
        request = Request(url, headers={"Accept": "*/*", "User-Agent": "NCam-NG-Panel"})
        if authorization:
            request.add_header("Authorization", authorization)
        with urlopen(request, timeout=timeout or settings.ncam_timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    try:
        if credentials and credentials[0]:
            # el WebIf de NCam usa Digest MD5 (y Basic como alternativa en otras
            # versiones): se prueba Basic y, si lo rechaza, se responde al reto
            token = base64.b64encode(f"{credentials[0]}:{credentials[1]}".encode()).decode()
            try:
                return _fetch(f"Basic {token}")
            except HTTPError as exc:
                challenge_header = exc.headers.get("WWW-Authenticate", "") if exc.headers else ""
                if exc.code != 401 or not credentials[1]:
                    raise
                challenge = _parse_digest_challenge(challenge_header)
                if not challenge:
                    raise
                digest = _digest_authorization(
                    credentials[0], credentials[1], "GET", request_uri, challenge
                )
                return _fetch(digest)
        return _fetch()
    except HTTPError as exc:
        if exc.code == 401:
            raise NcamUnavailable(
                "NCam WebIf rechazó las credenciales (revise usuario/contraseña del WebIf)"
            ) from exc
        if exc.code == 403:
            # el único 403 del WebIf es la comprobación de origen: la IP de quien
            # se conecta no está en httpallowed ni la resuelve httpdyndns
            origen = _origen_del_panel(base)
            raise NcamUnavailable(
                "El WebIf de NCam denegó el acceso (HTTP 403): la dirección desde la que se "
                f"conecta el panel ({origen}) no está en httpallowed/httpdyndns del daemon. "
                f"Añádela con:  sudo ncam-ng-ctl webif add {origen}"
            ) from exc
        raise NcamUnavailable(f"NCam WebIf respondió HTTP {exc.code}") from exc
    except (URLError, socket.timeout, OSError) as exc:
        raise NcamUnavailable(f"No se pudo contactar el WebIf de NCam ({exc})") from exc


def _get_json(path: str, params: dict[str, str], timeout: Optional[float] = None,
              credentials: Optional[tuple[str, str]] = None,
              base_url: Optional[str] = None) -> dict[str, Any]:
    body = _fetch_text(path, params, timeout=timeout, credentials=credentials, base_url=base_url)
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


def record_cache_server_check(
    conn: sqlite3.Connection,
    server_id: int,
    ok: bool,
    elapsed_ms: Optional[int],
    error: Optional[str],
) -> dict[str, Any]:
    """Guarda en la fila del peer el resultado de un sondeo TCP previo.

    Está separado de :func:`probe_tcp` a propósito: el sondeo tarda hasta
    segundos y debe ejecutarse fuera de la transacción de la petición (ver
    ``db.without_transaction``); si no, dos «Probar» a la vez chocan con
    ``database is locked`` y terminan en HTTP 500.
    """
    database.execute(
        conn,
        "UPDATE cache_servers SET last_check_at = ?, last_check_ok = ?, last_check_ms = ?,"
        " last_check_error = ? WHERE id = ?",
        (database.utcnow(), 1 if ok else 0, elapsed_ms, error, server_id),
    )
    return {"ok": ok, "latency_ms": elapsed_ms, "error": error}


# ---------------------------------------------------------------------------
# generadores de configuración
# ---------------------------------------------------------------------------
# CAID en formato NCam: ``1801``, con máscara ``1801&FFFF`` o con cmap
# ``1801:01``; varios separados por comas (``1801,1861,0B00``).
CAID_PATTERN = re.compile(r"^[0-9A-F]{1,4}(&[0-9A-F]{1,4})?(:[0-9A-F]{1,2})?$")


def _pad_caid(token: str) -> str:
    """Deja el CAID con 4 dígitos (``b00`` -> ``0B00``) conservando máscara/cmap."""
    for separator in ("&", ":"):
        if separator in token:
            head, _, tail = token.partition(separator)
            return f"{head.zfill(4)}{separator}{tail}"
    return token.zfill(4)


def normalize_caids(value: Optional[str]) -> str:
    """Normaliza la lista de CAIDs permitidos de una línea.

    Acepta lo mismo que NCam (``1801``, ``1801,1861,0B00``, ``1801&FFFF``,
    ``1861:01``), quita espacios, pasa a mayúsculas y valida el formato.
    Devuelve ``""`` cuando no hay restricción. Lanza ``ValueError`` con el
    detalle si algún valor no es válido.
    """
    if not value:
        return ""
    caids: list[str] = []
    for raw in str(value).replace(";", ",").split(","):
        token = raw.strip().upper()
        if not token:
            continue
        if not CAID_PATTERN.match(token):
            raise ValueError(
                f"CAID no válido: '{raw.strip()}'. Usa 4 dígitos hexadecimales "
                "(p. ej. 1801) separados por comas: 1801,1861,0B00"
            )
        token = _pad_caid(token)
        if token not in caids:
            caids.append(token)
    return ",".join(caids)


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
    # permiso por CAID: sin valor, el usuario ve todos los CAID de su grupo
    caids = normalize_caids(data.get("caid_allow"))
    if caids:
        entries.append(("caid", caids))
    if int(data.get("cacheex_mode") or 0) > 0:
        entries.append(("cacheex", str(data["cacheex_mode"])))
        if int(data.get("cacheex_maxhop") or 0) > 0:
            entries.append(("cacheex_maxhop", str(data["cacheex_maxhop"])))
    # ``cacheex_disable`` no existe como clave del daemon (se ignora en
    # silencio), así que no se emite: el interruptor queda guardado en el
    # panel como dato informativo.
    # conexiones simultáneas que admite la cuenta (1 = solo una)
    connections = int(data.get("max_connections") or 1)
    if connections != 1:
        entries.append(("max_connections", str(connections)))
    # saltos CCcam: cuántos saltos puede ver el cliente (0 = solo tus tarjetas
    # directas, valores mayores = tarjetas más lejanas y revendedores)
    hops = data.get("cccmaxhops")
    if hops is not None and int(hops) >= 0:
        entries.append(("cccmaxhops", str(int(hops))))

    header = f"# Línea '{data.get('name')}' ({data.get('protocol')}) - NCPanel"
    body = "\n".join(f"{key:<16} = {value}" for key, value in entries)
    return f"{header}\n[account]\n{body}\n"


def render_cache_peer_config(server: sqlite3.Row | dict[str, Any], username: Optional[str] = None) -> str:
    """Bloque ``[reader]`` para conectar con un peer de caché remoto."""
    data = dict(server)
    protocol = str(data.get("protocol") or "cccam")
    label = str(data.get("name") or "cacheex_peer").replace(" ", "_")
    lines = [
        f"# Peer de caché '{data.get('name')}' - NCPanel",
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
    # OJO con los nombres: el daemon solo entiende ``cacheex`` / ``cacheex_maxhop``
    # (``cachex*`` no existe y se ignora en silencio). La prioridad es solo un
    # orden interno del panel: no hay clave ``priority`` en ncam.server.
    lines.extend(
        [
            "group           = 1",
            "cacheex         = 3",
            "cacheex_maxhop  = 2",
            f"enable          = {1 if int(data.get('enabled', 1)) else 0}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_cache_section(conn: sqlite3.Connection) -> str:
    """Sección ``[cache]`` recomendada, alimentada por los ajustes del panel."""
    max_time = database.get_setting(conn, "ncam.cache.max_time", "15")
    max_entries = database.get_setting(conn, "ncam.cache.max_entries", "0")
    cacheex = database.get_setting(conn, "ncam.cache.cacheex_enable", "1")
    cacheex_on = str(cacheex) in {"1", "true", "yes"}
    lines = [
        "# Motor de caché v2 - generado por NCPanel",
        "# La caché se consulta siempre antes de pedir a los lectores.",
        "[cache]",
        "# milisegundos de espera al servir desde caché (0 = al instante;",
        "# 120 si tienes tarjeta local y ves ciclos de CW)",
        "delay             = 0",
        f"max_time          = {max_time}",
        f"max_entries       = {max_entries}",
        "# memoria de aciertos de cacheex (0 = desactivada)",
        "max_hit_time      = 15",
        f"cacheexenablestats = {1 if cacheex_on else 0}",
    ]
    if cacheex_on:
        lines.extend(
            [
                "# intercambio de caché con otros servidores",
                "cacheex_dropdiffs = 0",
                "cacheex_localgenerated_only = 0",
                "cw_cache_size    = 8192",
                "cw_cache_memory  = 8",
                "ecm_cache_size   = 8192",
                "ecm_cache_memory = 8",
            ]
        )
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
            f"# línea '{data.get('name')}' (NCPanel)"
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


# ---------------------------------------------------------------------------
# control del daemon (aplicar peers/líneas/ajustes y reiniciar)
#
# El WebIf del daemon expone el control por GET autenticado (el mismo Digest
# de las lecturas): ``user_edit.html`` / ``readerconfig.html`` / ``config.html``
# aplican en memoria y persisten en ncam.user/ncam.server/ncam.conf, y
# ``shutdown.html`` reinicia. Como las respuestas son páginas HTML, el éxito
# se detecta por los mensajes que emite el propio daemon.
# ---------------------------------------------------------------------------
USER_SAVED_MARKERS = (
    "User Account updated and saved",
    "New user has been added with default settings",
    "New user has been added with cloned settings",
)
USER_CREATED_MARKERS = (
    "New user has been added with default settings",
    "New user has been added with cloned settings",
)
READER_SAVED_MARKER = "Reader config updated and saved"
READER_ADDED_MARKER = "New Reader has been added with default settings"
CONFIG_SAVED_MARKER = "Configuration was saved."


def _control_params(conn: Optional[sqlite3.Connection]) -> tuple[tuple[str, str], str]:
    """Credenciales y URL efectiva del WebIf para las acciones de control."""
    return _credentials(conn), _webif_url(conn)


def fetch_reader_labels(conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """Etiquetas de los readers que conoce el daemon (``part=readerlist``)."""
    try:
        payload = _get_json(
            "/ncamapi.json",
            {"part": "readerlist"},
            credentials=_credentials(conn),
            base_url=_webif_url(conn),
        )
    except NcamUnavailable as exc:
        return {"reachable": False, "error": str(exc), "labels": []}
    readers = ((payload or {}).get("ncam") or {}).get("readers") or []
    return {"reachable": True, "labels": [str(item.get("label", "")) for item in readers if isinstance(item, dict)]}


def peer_reader_label(server: sqlite3.Row | dict[str, Any]) -> str:
    """Etiqueta del reader en el daemon para un peer del panel."""
    return str(dict(server).get("name") or "cacheex_peer").replace(" ", "_")


def peer_to_reader_params(server: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
    """Traduce un peer del panel a parámetros del reader del daemon.

    Usa exactamente las claves de ``ncam-config-reader.c`` (``cacheex``, no
    ``cachex``) y omite ``node_id`` cuando no es una lista de CAIDs válida.
    """
    data = dict(server)
    protocol = str(data.get("protocol") or "cccam")
    params = {
        "label": peer_reader_label(data),
        "protocol": protocol,
        "device": f"{data.get('host')},{data.get('port')}",
        "group": "1",
        "cacheex": "3",
        "cacheex_maxhop": "2",
        "enable": "1" if int(data.get("enabled", 1)) else "0",
    }
    if data.get("username"):
        params["user"] = str(data["username"])
    if data.get("password"):
        params["password"] = str(data["password"])
    if data.get("node_id"):
        try:
            caids = normalize_caids(str(data["node_id"]))
        except ValueError:
            caids = ""
        if caids:
            params["caid"] = caids
    return params


def line_to_account_params(line: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
    """Traduce una línea del panel a parámetros de cuenta del daemon.

    Espejo de :func:`render_account_config` con las claves de
    ``ncam-config-account.c``. Las líneas suspendidas o caducadas se aplican
    con ``disabled=1`` (las nuevas del WebIf nacen desactivadas, así que las
    activas llevan ``disabled=0`` explícito).
    """
    from datetime import datetime, timezone

    data = dict(line)
    params = {
        "user": str(data["username"]),
        "pwd": str(data["password"]),
        "group": str(data.get("group_name") or "1"),
        "uniq": "1",
        "sleep": "0",
        "monlevel": "1",
        "au": "1",
    }
    caids = normalize_caids(data.get("caid_allow"))
    if caids:
        params["caid"] = caids
    if int(data.get("cacheex_mode") or 0) > 0:
        params["cacheex"] = str(data["cacheex_mode"])
        if int(data.get("cacheex_maxhop") or 0) > 0:
            params["cacheex_maxhop"] = str(data["cacheex_maxhop"])
    connections = int(data.get("max_connections") or 1)
    if connections != 1:
        params["max_connections"] = str(connections)
    hops = data.get("cccmaxhops")
    if hops is not None and int(hops) >= 0:
        params["cccmaxhops"] = str(int(hops))
    if data.get("expires_at"):
        try:
            expires = datetime.fromisoformat(str(data["expires_at"]))
            params["expdate"] = expires.strftime("%Y-%m-%d")
        except ValueError:
            pass
    disabled = str(data.get("status") or "") == "suspended"
    if not disabled and data.get("expires_at"):
        try:
            expires = datetime.fromisoformat(str(data["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            disabled = expires < datetime.now(timezone.utc)
        except ValueError:
            pass
    params["disabled"] = "1" if disabled else "0"
    return params


def apply_account(
    conn: Optional[sqlite3.Connection], username: str, params: dict[str, str]
) -> dict[str, Any]:
    """Crea o actualiza una cuenta en el daemon (``user_edit.html``)."""
    credentials, base_url = _control_params(conn)
    try:
        body = _fetch_text(
            "/user_edit.html",
            {"action": "Save", "user": username, **params},
            credentials=credentials,
            base_url=base_url,
        )
    except NcamUnavailable as exc:
        return {"ok": False, "message": str(exc), "created": False}
    if "Write Config failed!" in body:
        return {"ok": False, "message": "El daemon no pudo escribir ncam.user (¿permiso denegado?)", "created": False}
    if any(marker in body for marker in USER_SAVED_MARKERS):
        created = any(marker in body for marker in USER_CREATED_MARKERS)
        return {
            "ok": True,
            "created": created,
            "message": f"Cuenta '{username}' {'creada' if created else 'actualizada'} en NCam",
        }
    return {"ok": False, "message": "El daemon no confirmó el guardado de la cuenta", "created": False}


def apply_reader(
    conn: Optional[sqlite3.Connection], label: str, params: dict[str, str]
) -> dict[str, Any]:
    """Crea o actualiza un reader en el daemon (``readerconfig.html``).

    Si la etiqueta no existe se da de alta primero (``action=Add``) y después
    se guardan todos los parámetros (``action=Save``), que además reinicia el
    reader y persiste ncam.server.
    """
    credentials, base_url = _control_params(conn)
    try:
        known = fetch_reader_labels(conn)
        if not known.get("reachable"):
            return {"ok": False, "message": str(known.get("error", "daemon inalcanzable")), "created": False}
        created = False
        if label not in known.get("labels", []):
            added = _fetch_text(
                "/readerconfig.html",
                {"action": "Add", "label": label, "protocol": params.get("protocol", "cccam")},
                credentials=credentials,
                base_url=base_url,
            )
            if READER_ADDED_MARKER not in added:
                return {"ok": False, "message": f"El daemon no creó el reader '{label}'", "created": False}
            created = True
        body = _fetch_text(
            "/readerconfig.html",
            {"action": "Save", "reader": label, **params},
            credentials=credentials,
            base_url=base_url,
        )
    except NcamUnavailable as exc:
        return {"ok": False, "message": str(exc), "created": False}
    if "Write Config failed!" in body:
        return {"ok": False, "message": "El daemon no pudo escribir ncam.server (¿permiso denegado?)", "created": created}
    if READER_SAVED_MARKER in body:
        return {
            "ok": True,
            "created": created,
            "message": f"Reader '{label}' {'creado' if created else 'actualizado'} en NCam",
        }
    return {"ok": False, "message": f"El daemon no confirmó el guardado del reader '{label}'", "created": created}


def apply_cache_section(
    conn: Optional[sqlite3.Connection], max_time: int, max_entries: int, cacheex_enable: bool
) -> dict[str, Any]:
    """Aplica la sección ``[cache]`` en el daemon (``config.html``)."""
    credentials, base_url = _control_params(conn)
    try:
        body = _fetch_text(
            "/config.html",
            {
                "part": "cache",
                "action": "execute",
                "max_time": str(max_time),
                "max_entries": str(max_entries),
                "cacheexenablestats": "1" if cacheex_enable else "0",
            },
            credentials=credentials,
            base_url=base_url,
        )
    except NcamUnavailable as exc:
        return {"ok": False, "message": str(exc)}
    if "readonly mode" in body:
        return {"ok": False, "message": "El WebIf está en modo solo lectura (httpreadonly=1)"}
    if "Failed to write config file" in body:
        return {"ok": False, "message": "El daemon no pudo escribir ncam.conf (¿permiso denegado?)"}
    if CONFIG_SAVED_MARKER in body:
        return {"ok": True, "message": "Sección [cache] aplicada en NCam"}
    return {"ok": False, "message": "El daemon no confirmó el guardado de [cache]"}


def restart_daemon(conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    """Ordena al daemon reiniciarse (``shutdown.html``).

    El proceso sale con código 99 y systemd (``Restart=on-failure``) lo
    levanta de nuevo en unos segundos. Si el daemon se arrancó a mano, sale
    y no vuelve solo: la pantalla lo advierte.
    """
    credentials, base_url = _control_params(conn)
    try:
        _fetch_text(
            "/shutdown.html", {"action": "restart"}, credentials=credentials, base_url=base_url
        )
    except NcamUnavailable as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "Reinicio ordenado: NCam vuelve en unos segundos"}
