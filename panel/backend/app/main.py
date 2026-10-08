"""
NCPanel :: aplicación FastAPI.

* sirve la API REST bajo ``/api/v1``
* sirve el frontend SPA (``panel/frontend``) en ``/``
* incluye un programador opcional que guarda muestras periódicas de las
  estadísticas del motor de caché de NCam para los gráficos del panel.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as database
from . import ncam
from . import billing
from . import notifications
from .services import record_snapshot
from .config import FRONTEND_DIR, settings
from .routers import accounts, admin, auth, billing as billing_router, cache, daemon, lines, notifications as notifications_router, stats


log = logging.getLogger("ncam.panel")


async def _cache_sampler(stop_event: asyncio.Event) -> None:
    """Guarda una muestra de métricas de caché cada N segundos."""
    if not settings.ncam_poll_enabled:
        return
    # deja terminar init_db() antes de escribir la primera muestra
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=5)
        return
    except asyncio.TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(_collect_snapshot)
        except Exception as exc:  # nunca debe tumbar el panel
            log.warning("no se pudo guardar la muestra de caché: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.ncam_poll_interval)
        except asyncio.TimeoutError:
            continue


async def _expiry_notifier(stop_event: asyncio.Event) -> None:
    """Revisa periódicamente las líneas por caducar y envía los avisos configurados.

    Nunca debe tumbar el panel: cualquier error se registra y se espera al
    siguiente ciclo.
    """
    if not settings.notify_enabled:
        return
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=10)
        return
    except asyncio.TimeoutError:
        pass
    while not stop_event.is_set():
        interval = 3600
        try:
            interval = await asyncio.to_thread(_notify_once)
        except Exception as exc:
            log.warning("no se pudieron enviar los avisos de caducidad: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def _notify_once() -> int:
    """Ejecuta una pasada de avisos y devuelve el intervalo hasta la siguiente."""
    with database.session() as conn:
        conf = notifications.notification_settings(conn)
        if conf["enabled"] and (conf["email_enabled"] or conf["telegram_enabled"]):
            report = notifications.run_notifications(conn)
            if report["sent"] or report["failed"]:
                log.info(
                    "avisos de caducidad: %s enviados, %s fallidos, %s omitidos",
                    len(report["sent"]),
                    len(report["failed"]),
                    len(report["skipped"]),
                )
        return conf["interval_seconds"]


async def _ecm_biller(stop_event: asyncio.Event) -> None:
    """Mide el consumo de ECM y factura los bloques completos pendientes.

    Solo actúa si ``billing.ecm.enabled`` está activo (por defecto: apagado, el
    panel no cobra nada sin que se le pida).
    """
    while not stop_event.is_set():
        interval = 900
        try:
            interval = await asyncio.to_thread(_bill_once)
        except Exception as exc:
            log.warning("no se pudo facturar el consumo de ECM: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def _bill_once() -> int:
    with database.session() as conn:
        conf = billing.billing_settings(conn)
        if not conf["enabled"]:
            return conf["interval_seconds"]
        report = billing.run_billing(conn)
        if report["billed_blocks"]:
            log.info(
                "consumo de ECM facturado: %s bloques, %s %s en %s líneas",
                report["billed_blocks"],
                report["billed_credits"],
                report["currency"],
                len(report["lines"]),
            )
        return conf["interval_seconds"]


def _poll_enabled(conn) -> bool:
    """Muestreo automático del histórico (ajuste ``ncam.cache.panel_poll``).

    El interruptor maestro es ``NCAM_PANEL_CACHE_POLL`` del ``.env`` (si está a 0
    el planificador ni arranca); este ajuste permite apagarlo o encenderlo desde
    la pantalla *Ajustes* sin reiniciar el servicio.
    """
    value = str(database.get_setting(conn, "ncam.cache.panel_poll", "1")).strip().lower()
    return value in {"1", "true", "yes", "on", "si", "sí"}


def _collect_snapshot() -> None:
    with database.session() as conn:
        if not _poll_enabled(conn):
            return
        stats = ncam.fetch_cache_stats(conn)
        if not stats.get("reachable"):
            return
        status = ncam.fetch_status(conn)
        metrics: dict[str, Any] = {
            "cache.hit_ratio": stats["hit_ratio"],
            "cache.entries": stats["entries"],
            "cache.lookups": stats["lookups"],
            "cache.hits": stats["hits"],
            "cache.misses": stats["misses"],
            "cache.mem_bytes": stats["mem_bytes"],
        }
        if status.get("reachable"):
            totals = status.get("totals", {})
            metrics.update(
                {
                    "ncam.users_connected": totals.get("connected", 0),
                    "ncam.ecm_ok": totals.get("ecm_ok", 0),
                    "ncam.ecm_nok": totals.get("ecm_nok", 0),
                    "ncam.ecm_from_cache": totals.get("from_cache", 0),
                }
            )
        record_snapshot(conn, metrics, source="panel-poller")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    stop_event = asyncio.Event()
    task: asyncio.Task | None = None
    notifier: asyncio.Task | None = None
    if settings.ncam_poll_enabled:
        task = asyncio.create_task(_cache_sampler(stop_event))
    if settings.notify_enabled:
        notifier = asyncio.create_task(_expiry_notifier(stop_event))
    biller = asyncio.create_task(_ecm_biller(stop_event))
    log.info(
        "%s %s listo en http://%s:%s (NCam WebIf: %s)",
        settings.panel_name,
        settings.version,
        settings.host,
        settings.port,
        settings.ncam_webif_url,
    )
    try:
        yield
    finally:
        stop_event.set()
        for pending in (task, notifier, biller):
            if not pending:
                continue
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(
    title="NCPanel",
    description=(
        "NCPanel: panel de gestión para NCam-NG con roles de super administrador y "
        "revendedor, control de líneas, créditos, peers de caché y métricas del motor "
        "de caché."
    ),
    version=settings.version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(accounts.router, prefix=API_PREFIX)
app.include_router(lines.router, prefix=API_PREFIX)
app.include_router(cache.router, prefix=API_PREFIX)
app.include_router(daemon.router, prefix=API_PREFIX)
app.include_router(stats.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(notifications_router.router, prefix=API_PREFIX)
app.include_router(billing_router.router, prefix=API_PREFIX)


@app.get(f"{API_PREFIX}/health", tags=["meta"])
def health():
    """Sonda de vida: el panel responde y el daemon NCam (si está) también."""
    db_ok = True
    webif_url = settings.ncam_webif_url
    ncam_state: dict[str, Any] = {"reachable": False}
    try:
        with database.session() as conn:
            conn.execute("SELECT 1")
            # la URL efectiva puede venir de los ajustes del panel
            webif_url = ncam._webif_url(conn)
            ncam_state = ncam.fetch_cache_stats(conn)
    except Exception as exc:  # pragma: no cover - solo en fallos de disco
        log.warning("health: no se pudo consultar el daemon: %s", exc)
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "panel_version": settings.version,
        "database": "ok" if db_ok else "error",
        "ncam_reachable": bool(ncam_state.get("reachable")),
        "ncam_url": webif_url,
    }


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):  # pragma: no cover
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# frontend
# ---------------------------------------------------------------------------
_frontend_dir = Path(FRONTEND_DIR)
if (_frontend_dir / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir / "static")), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_file = _frontend_dir / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return JSONResponse(
        status_code=503,
        content={"detail": "El frontend no está instalado en panel/frontend/index.html"},
    )
