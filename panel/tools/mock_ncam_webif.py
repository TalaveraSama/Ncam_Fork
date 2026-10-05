#!/usr/bin/env python3
"""
NCam-NG Panel :: simulador del WebIf de NCam (solo para desarrollo).

Sirve el mismo contrato JSON que expone el daemon:

    GET /ncamapi.json?part=cachestats   -> estadísticas del motor de caché v2
    GET /ncamapi.json?part=status       -> cabecera/totales del daemon

Sirve para probar el panel sin compilar NCam y para desarrollar el frontend.

    python3 panel/tools/mock_ncam_webif.py --port 8181
"""

from __future__ import annotations

import argparse
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
        self.hot_entries = [
            {"caid": "0100", "prid": "000000", "srvid": "0001", "hits": 8421, "from_csp": 0, "from_cacheex": 1, "from_localcards": 0},
            {"caid": "0500", "prid": "000000", "srvid": "0A2B", "hits": 5310, "from_csp": 0, "from_cacheex": 1, "from_localcards": 0},
            {"caid": "0B00", "prid": "0000A1", "srvid": "1F40", "hits": 2987, "from_csp": 1, "from_cacheex": 0, "from_localcards": 0},
            {"caid": "0D00", "prid": "000000", "srvid": "03E8", "hits": 1455, "from_csp": 0, "from_cacheex": 0, "from_localcards": 1},
            {"caid": "1810", "prid": "000000", "srvid": "2AF8", "hits": 812, "from_csp": 0, "from_cacheex": 1, "from_localcards": 1},
        ]

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


class Handler(BaseHTTPRequestHandler):
    server_version = "MockNcamWebIf/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path != "/ncamapi.json":
            self.send_error(404, "solo /ncamapi.json (simulador)")
            return

        part = (params.get("part") or ["status"])[0]
        payload = cachestats_payload() if part == "cachestats" else status_payload()
        body = json.dumps(payload, indent=1).encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # silenciar accesos
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador del WebIf de NCam")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8181)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Simulador del WebIf de NCam escuchando en http://{args.host}:{args.port}")
    print("Endpoints: /ncamapi.json?part=cachestats  |  /ncamapi.json?part=status")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
