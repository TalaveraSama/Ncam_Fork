#!/usr/bin/env python3
"""
NCPanel :: simulador del WebIf de NCam (solo para desarrollo).

Sirve el mismo contrato JSON que expone el daemon:

    GET /ncamapi.json?part=cachestats   -> estadísticas del motor de caché v2
    GET /ncamapi.json?part=status       -> cabecera/totales del daemon
    GET /ncamapi.json?part=userstats    -> contadores de ECM por cuenta (facturación)

Sirve para probar el panel sin compilar NCam y para desarrollar el frontend.

Las cuentas simuladas se toman de ``--users`` (o del fichero ``--users-file``, un
JSON con la lista de nombres). Cada contador crece con el tiempo de forma
determinista, de modo que la facturación por consumo se puede probar de verdad.

    python3 panel/tools/mock_ncam_webif.py --port 8181 --users demo_linea,otra_linea
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class MockState:
    def __init__(self) -> None:
        self.started = time.time()
        self.hits = 41230
        self.misses = 8170
        self.entries = 137
        self.cw_entries = 168
        self.cw_new = 15420
        self.cw_upd = 25810
        self.evicted_ttl = 9820
        self.evicted_lru = 0
        self.cwc_rejected = 3
        # control desde el panel (imitan al daemon de verdad)
        self.readers: dict = {}        # label -> params del último Add/Save
        self.applied_users: dict = {}  # user -> params del último Save
        self.cache_section: dict = {}  # sección [cache] aplicada
        self.restarts = 0              # veces que se pidió action=restart
        self.hot_entries = [
            {"caid": "0100", "prid": "000000", "srvid": "0001", "hits": 8421, "from_csp": 0, "from_cacheex": 1, "from_localcards": 0},
            {"caid": "0500", "prid": "000000", "srvid": "0A2B", "hits": 5310, "from_csp": 0, "from_cacheex": 1, "from_localcards": 0},
            {"caid": "0B00", "prid": "0000A1", "srvid": "1F40", "hits": 2987, "from_csp": 1, "from_cacheex": 0, "from_localcards": 0},
            {"caid": "0D00", "prid": "000000", "srvid": "03E8", "hits": 1455, "from_csp": 0, "from_cacheex": 0, "from_localcards": 1},
            {"caid": "1810", "prid": "000000", "srvid": "2AF8", "hits": 812, "from_csp": 0, "from_cacheex": 1, "from_localcards": 1},
        ]

    def ecm_counter(self, username: str) -> int:
        """Contador de ECM acumulado y creciente para cada cuenta simulada."""
        base = int(hashlib.md5(username.encode()).hexdigest()[:4], 16) % 5000
        # ~1 ECM/s desde el arranque del simulador
        return base + int((time.time() - self.started) * 1.0)

    def tick(self) -> None:
        # pequeñas variaciones para que los gráficos se muevan
        self.hits += random.randint(5, 40)
        self.misses += random.randint(0, 8)
        self.entries = max(1, self.entries + random.choice([-1, 0, 1]))
        self.cw_entries += random.choice([0, 1])
        self.cw_new += random.choice([0, 1])
        self.cw_upd += random.randint(1, 3)

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return round(self.hits * 100.0 / total, 2) if total else 0.0


STATE = MockState()
MOCK_USERS: list[str] = ["demo_linea"]


def cachestats_payload() -> dict:
    STATE.tick()
    uptime = int(time.time() - STATE.started)
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)

    return {
        "ncam": {
            "version": "1.9-NG",
            "revision": "mock-cachestats",
            "build": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uptime": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "runtime": uptime,
            "cachestats": {
                "engine": "NCam-NG cache engine (mock)",
                "max_entries": "0",
                "max_time": "15",
                "entries": str(STATE.entries),
                "cw_entries": str(STATE.cw_entries),
                "mem_bytes": str(STATE.entries * 512 + STATE.cw_entries * 320),
                "lookups": str(STATE.hits + STATE.misses),
                "hits": str(STATE.hits),
                "misses": str(STATE.misses),
                "hit_ratio": f"{STATE.hit_ratio:.2f}",
                "cw_new": str(STATE.cw_new),
                "cw_upd": str(STATE.cw_upd),
                "cwc_rejected": str(STATE.cwc_rejected),
                "evicted_ttl": str(STATE.evicted_ttl),
                "evicted_lru": str(STATE.evicted_lru),
                "cw_cache": {
                    "entries": "42",
                    "mem_bytes": "20480",
                    "localgenerated": "7",
                },
                "hot_entries": STATE.hot_entries,
            },
        }
    }


def userstats_payload(only: str | None = None) -> dict:
    """Mismo contrato que ``part=userstats`` del daemon, con ``cwok`` por cuenta."""
    users = [only] if only else MOCK_USERS
    now = datetime.now(timezone.utc)
    entries = []
    for username in users:
        counter = STATE.ecm_counter(username)
        entries.append({
            "user": {
                "usermd5": "id_" + hashlib.md5(username.encode()).hexdigest(),
                "status": "online" if counter % 2 else "offline",
                "classname": "online",
                "expdate": (now.replace(year=now.year + 1)).strftime("%Y-%m-%d"),
                "groups": "1",
                "stats": {
                    "cwok": str(counter),
                    "cwnok": str(counter // 50),
                    "cwcache": str(counter // 3),
                    "cwtimeout": "0",
                    "cwignore": "0",
                    "cwtun": "0",
                    "emmok": "0",
                    "emmnok": "0",
                    "cwrate": "1.00",
                },
            }
        })
    return {"ncam": {
        "version": "Unofficial",
        "revision": "mock-userstats",
        "build": now.strftime("%d-%m-%Y"),
        "starttime": now.isoformat(),
        "uptime": str(int(time.time() - STATE.started)),
        "users": entries,
    }}


def status_payload() -> dict:
    uptime = int(time.time() - STATE.started)
    return {
        "ncam": {
            "version": "1.9-NG",
            "revision": "mock-status",
            "build": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uptime": str(uptime),
            "runtime": uptime,
            "sysinfo": {
                "mem_cur_total": str(512 * 1024),
                "mem_cur_free": str(int(180 * 1024 + 512 * math.sin(time.time() / 30))),
                "ncam_rsssize": str(38 * 1024),
                "cpu_load_0": f"{0.4 + 0.1 * math.sin(time.time() / 45):.2f}",
            },
            "totals": {
                "total_users": "12",
                "total_active": "9",
                "total_connected": "7",
                "total_online": "6",
                "total_cwok": str(STATE.hits),
                "total_cwnok": str(STATE.misses),
                "total_cwtout": "412",
                "total_cwcache": str(STATE.hits),
            },
            "status": {"ucs": "7", "rcs": "4"},
        }
    }


def readerlist_payload() -> dict:
    """Mismo contrato que ``part=readerlist`` del daemon (solo lo que usa el panel)."""
    return {"ncam": {"readers": [{"label": label} for label in STATE.readers]}}


class Handler(BaseHTTPRequestHandler):
    server_version = "MockNcamWebIf/1.0"

    def _send(self, body: bytes, content_type: str = "text/javascript") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text: str) -> None:
        self._send(f"<html><body>{text}</body></html>".encode(), "text/html")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        first = {key: values[0] for key, values in params.items() if values}

        if parsed.path == "/ncamapi.json":
            part = first.get("part", "status")
            if part == "cachestats":
                payload = cachestats_payload()
            elif part == "userstats":
                payload = userstats_payload(first.get("user"))
            elif part == "readerlist":
                payload = readerlist_payload()
            else:
                payload = status_payload()
            self._send(json.dumps(payload, indent=1).encode())
            return

        # --- control desde el panel (mismos marcadores que el daemon) ---
        if parsed.path == "/shutdown.html" and first.get("action") == "restart":
            STATE.restarts += 1
            self._send_html("NCam is restarting now")
            return

        if parsed.path == "/user_edit.html" and first.get("action") == "Save":
            user = first.get("user", "")
            created = user not in STATE.applied_users
            STATE.applied_users[user] = first
            if created:
                # como el daemon: crea con valores por defecto y aplica en la misma llamada
                self._send_html("New user has been added with default settings User Account updated and saved")
            else:
                self._send_html("User Account updated and saved")
            return

        if parsed.path == "/readerconfig.html" and first.get("action") == "Add":
            label = first.get("label", "")
            STATE.readers[label] = dict(first)
            self._send_html("New Reader has been added with default settings")
            return

        if parsed.path == "/readerconfig.html" and first.get("action") == "Save":
            label = first.get("reader") or first.get("label", "")
            if label not in STATE.readers:
                self._send_html("")  # como el daemon: sin reader no hay nada que guardar
                return
            STATE.readers[label] = dict(first)
            self._send_html("Reader config updated and saved")
            return

        if parsed.path == "/config.html" and first.get("part") == "cache" and first.get("action") == "execute":
            STATE.cache_section = {k: v for k, v in first.items() if k not in {"part", "action"}}
            self._send_html("Configuration was saved.")
            return

        self.send_error(404, "ruta no simulada")

    def log_message(self, fmt: str, *args) -> None:  # silenciar accesos
        pass


def start_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Crea el simulador (para las pruebas: puerto 0 = efímero)."""
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador del WebIf de NCam")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8181)
    parser.add_argument("--users", default="demo_linea",
                        help="nombres de cuenta separados por comas para part=userstats")
    parser.add_argument("--users-file", default=None,
                        help="fichero JSON con una lista de nombres de cuenta")
    args = parser.parse_args()

    global MOCK_USERS
    if args.users_file:
        with open(args.users_file, encoding="utf-8") as handle:
            MOCK_USERS = [str(name) for name in json.load(handle)]
    else:
        MOCK_USERS = [name.strip() for name in args.users.split(",") if name.strip()] or ["demo_linea"]

    server = start_server(args.host, args.port)
    print(f"Simulador del WebIf de NCam escuchando en http://{args.host}:{args.port}")
    print("Endpoints: /ncamapi.json?part=cachestats | part=status | part=userstats | part=readerlist")
    print("Control: shutdown.html, user_edit.html, readerconfig.html, config.html")
    print(f"Cuentas simuladas: {', '.join(MOCK_USERS)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
