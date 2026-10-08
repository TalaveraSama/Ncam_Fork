"""
NCPanel :: capa de acceso a datos (SQLite, sin dependencias externas).

Se usa el módulo sqlite3 de la biblioteca estándar con una única conexión por
petición. El esquema se crea/actualiza de forma idempotente al arrancar.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .config import settings


SCHEMA_VERSION = 5

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_info (
    version     INTEGER NOT NULL,
    updated_at  TEXT    NOT NULL
);

-- Cuentas: super_admin (dueño del panel), reseller (revendedor) y user (cliente)
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL CHECK (role IN ('super_admin', 'reseller', 'user')),
    email           TEXT,
    parent_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    credits         INTEGER NOT NULL DEFAULT 0,
    max_lines       INTEGER NOT NULL DEFAULT 0,          -- 0 = sin límite
    status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    api_key_hash    TEXT,
    api_key_prefix  TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    last_login_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_parent ON users(parent_id);
CREATE INDEX IF NOT EXISTS idx_users_role   ON users(role);

-- Líneas IPTV/CAM que se exportan a NCam como cuentas [account]
CREATE TABLE IF NOT EXISTS lines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name              TEXT    NOT NULL,
    protocol          TEXT    NOT NULL DEFAULT 'cccam'
                      CHECK (protocol IN ('cccam', 'newcamd', 'camd35', 'cacheex')),
    username          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password          TEXT    NOT NULL,
    group_name        TEXT    NOT NULL DEFAULT '1',
    caid_allow        TEXT,
    max_connections   INTEGER NOT NULL DEFAULT 1,
    cccmaxhops        INTEGER NOT NULL DEFAULT 1,        -- saltos CCcam que ve el cliente
    expires_at        TEXT,
    status            TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    cacheex_mode      INTEGER NOT NULL DEFAULT 0,
    cacheex_maxhop    INTEGER NOT NULL DEFAULT 0,
    cacheex_disable   INTEGER NOT NULL DEFAULT 0,
    notify_email      TEXT,                              -- destino de los avisos (si vacío: email del propietario)
    notify_telegram   TEXT,                              -- chat_id de Telegram (si vacío: chat por defecto del panel)
    notify_days       INTEGER NOT NULL DEFAULT 0,        -- días de antelación propios (0 = usar el global)
    ecm_total         INTEGER NOT NULL DEFAULT 0,        -- último contador de ECM leído del daemon
    ecm_billed        INTEGER NOT NULL DEFAULT 0,        -- ECM ya facturadas al propietario
    notes             TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    created_by        INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_lines_owner  ON lines(owner_id);
CREATE INDEX IF NOT EXISTS idx_lines_status ON lines(status);

-- Peers de caché (cacheex) administrados desde el panel
CREATE TABLE IF NOT EXISTS cache_servers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    host            TEXT    NOT NULL,
    port            INTEGER NOT NULL,
    protocol        TEXT    NOT NULL DEFAULT 'cccam'
                    CHECK (protocol IN ('cccam', 'camd35', 'newcamd', 'csp')),
    username        TEXT,
    password        TEXT,
    node_id         TEXT,
    priority        INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_check_at   TEXT,
    last_check_ok   INTEGER,
    last_check_ms   INTEGER,
    last_check_error TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache_servers_owner ON cache_servers(owner_id);

-- Libro mayor de créditos
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    amount        INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN ('topup', 'debit', 'refund', 'adjust')),
    description   TEXT,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id, created_at);

-- Registro de auditoría (todas las acciones sensibles)
CREATE TABLE IF NOT EXISTS audit_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_username TEXT,
    action         TEXT    NOT NULL,
    target_type    TEXT,
    target_id      INTEGER,
    details        TEXT,
    ip             TEXT,
    created_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_actor   ON audit_logs(actor_id);

-- Ajustes globales del panel (incluye los del motor de caché de NCam)
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL
);

-- Histórico de métricas para los gráficos del panel
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'ncam',
    metric      TEXT NOT NULL,
    value       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_metric ON usage_snapshots(metric, captured_at);

-- Intentos de login (antifuerza bruta + auditoría)
CREATE TABLE IF NOT EXISTS login_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    ip         TEXT,
    success    INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(username, created_at);

-- Consumo de ECM por línea y su facturación
CREATE TABLE IF NOT EXISTS ecm_usage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id      INTEGER REFERENCES lines(id) ON DELETE CASCADE,
    owner_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    measured_at  TEXT    NOT NULL,
    ecm_ok       INTEGER NOT NULL,          -- contador acumulado en el daemon
    ecm_delta    INTEGER NOT NULL,          -- ECM nuevas desde la medición anterior
    ecm_billed   INTEGER NOT NULL DEFAULT 0,-- ECM incluidas en bloques facturados
    blocks       INTEGER NOT NULL DEFAULT 0,
    credits      INTEGER NOT NULL DEFAULT 0,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS idx_ecm_usage_line ON ecm_usage(line_id, measured_at);
CREATE INDEX IF NOT EXISTS idx_ecm_usage_date ON ecm_usage(measured_at);

-- Avisos de caducidad enviados (email/telegram), evita duplicados
CREATE TABLE IF NOT EXISTS notification_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id    INTEGER REFERENCES lines(id) ON DELETE CASCADE,
    owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    channel    TEXT    NOT NULL CHECK (channel IN ('email', 'telegram')),
    target     TEXT,
    days_left  INTEGER NOT NULL,
    expires_at TEXT,
    status     TEXT    NOT NULL CHECK (status IN ('sent', 'failed', 'skipped')),
    error      TEXT,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_line ON notification_log(line_id, channel, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_date ON notification_log(created_at);

-- Refresh tokens revocables
CREATE TABLE IF NOT EXISTS refresh_tokens (
    jti        TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    """Timestamp ISO-8601 en UTC (segundos de precisión)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_write_lock = threading.Lock()


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def session(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Contexto transaccional: hace commit al salir, rollback si hay error."""
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


@contextmanager
def without_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Cierra temporalmente la transacción para operaciones lentas (red).

    Algunas peticiones leen de la base de datos, tardan segundos en la red
    (sondeo TCP de un peer, SMTP, ...) y después escriben. Si la transacción
    de lectura se mantiene abierta durante la red, dos peticiones a la vez
    chocan al escribir (``database is locked`` -> HTTP 500). Con este contexto
    la lectura se confirma, la red corre sin transacción y al salir se abre
    una transacción nueva y corta para la escritura.
    """
    conn.execute("COMMIT")
    try:
        yield conn
    finally:
        conn.execute("BEGIN")


# Nombre del panel. Se guarda en los ajustes (panel.name) y lo usan los avisos
# y el frontend; al renombrar el producto se conserva por compatibilidad la
# variable de entorno NCAM_PANEL_NAME y el ajuste panel.name de siempre.
PANEL_DEFAULT_NAME = "NCPanel"
PANEL_OLD_DEFAULT_NAME = "NCam-NG Panel"


def init_db(db_path: Optional[Path] = None) -> None:
    """Crea el esquema si no existe y aplica migraciones sencillas."""
    with _write_lock:
        conn = connect(db_path)
        try:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_info (version, updated_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utcnow()),
                )
            elif int(row["version"]) != SCHEMA_VERSION:
                _migrate(conn, int(row["version"]))
                conn.execute(
                    "UPDATE schema_info SET version = ?, updated_at = ?",
                    (SCHEMA_VERSION, utcnow()),
                )
            _ensure_default_settings(conn)
            _rename_panel_if_default(conn)
        finally:
            conn.close()


def _rename_panel_if_default(conn: sqlite3.Connection) -> None:
    """Renombra el panel en las instalaciones que aún tienen el nombre antiguo.

    Solo se cambia cuando el ajuste conserva el valor por defecto: si alguien lo
    personalizó (``panel.name``), se respeta.
    """
    row = conn.execute("SELECT value FROM settings WHERE key = 'panel.name'").fetchone()
    if row is not None and row["value"] == PANEL_OLD_DEFAULT_NAME:
        conn.execute(
            "UPDATE settings SET value = ? WHERE key = 'panel.name'",
            (PANEL_DEFAULT_NAME,),
        )


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Migraciones incrementales sobre bases de datos ya existentes."""
    line_columns = {row["name"] for row in conn.execute("PRAGMA table_info(lines)")}
    if from_version < 3:
        for column, ddl in (
            ("notify_email", "ALTER TABLE lines ADD COLUMN notify_email TEXT"),
            ("notify_telegram", "ALTER TABLE lines ADD COLUMN notify_telegram TEXT"),
            ("notify_days", "ALTER TABLE lines ADD COLUMN notify_days INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in line_columns:
                conn.execute(ddl)
    if from_version < 4:
        for column, ddl in (
            ("ecm_total", "ALTER TABLE lines ADD COLUMN ecm_total INTEGER NOT NULL DEFAULT 0"),
            ("ecm_billed", "ALTER TABLE lines ADD COLUMN ecm_billed INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in line_columns:
                conn.execute(ddl)
    if from_version < 5:
        # saltos CCcam que ve el cliente: hasta ahora el panel los deducía de
        # "conexiones máximas"; con el valor por defecto (1) el comportamiento
        # de las líneas ya creadas no cambia
        if "cccmaxhops" not in line_columns:
            conn.execute("ALTER TABLE lines ADD COLUMN cccmaxhops INTEGER NOT NULL DEFAULT 1")


DEFAULT_SETTINGS = {
    # motor de caché de NCam -> se exporta a ncam.conf [cache]
    "ncam.cache.max_time": "15",
    "ncam.cache.max_entries": "0",
    "ncam.cache.cacheex_enable": "1",
    "ncam.cache.panel_poll": "1",
    # reglas de negocio
    "billing.line_cost": str(settings.line_cost_credits),
    "billing.renew_cost": str(settings.renew_cost_credits),
    "billing.currency": "créditos",
    "panel.name": PANEL_DEFAULT_NAME,
    "panel.ncam_webif_url": settings.ncam_webif_url,
    "panel.ncam_webif_user": settings.ncam_webif_user,
    "panel.ncam_webif_password": settings.ncam_webif_password,
    # avisos de caducidad (email / telegram)
    "notify.enabled": "0",
    "notify.days_before": "3",
    "notify.channel.email": "0",
    "notify.channel.telegram": "0",
    "notify.interval_seconds": "3600",
    "notify.smtp.host": "",
    "notify.smtp.port": "587",
    "notify.smtp.user": "",
    "notify.smtp.password": "",
    "notify.smtp.from": "",
    "notify.smtp.starttls": "1",
    "notify.telegram.bot_token": "",
    "notify.telegram.chat_id": "",
    # facturación por consumo de ECM
    "billing.ecm.enabled": "0",
    "billing.ecm.price": "10",          # créditos por bloque
    "billing.ecm.block": "1000",        # ECM por bloque
    "billing.ecm.interval_seconds": "900",
    "billing.ecm.suspend_on_debt": "0",
    # datos publicados a los clientes finales
    "panel.public_host": "TU_SERVIDOR",
    "panel.port.cccam": "12000",
    "panel.port.newcamd": "50000",
    "panel.port.camd35": "33333",
    "panel.port.cacheex": "8181",
}


def _ensure_default_settings(conn: sqlite3.Connection) -> None:
    now = utcnow()
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO NOTHING",
            (key, value, now),
        )


# ---------------------------------------------------------------------------
# helpers de consulta usados por los servicios
# ---------------------------------------------------------------------------
def query(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)).fetchall())


def query_one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchone()


def execute(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return conn.execute(sql, tuple(params))


def insert(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> int:
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())
    )
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, table: str, row_id: int, values: dict[str, Any]) -> None:
    if not values:
        return
    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?", (*values.values(), row_id)
    )


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = query_one(conn, "SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, utcnow()),
    )


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in query(conn, "SELECT key, value FROM settings")}
