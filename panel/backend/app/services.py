"""
NCPanel :: lógica de negocio.

Reglas implementadas aquí:

* **super_admin**  -> control total, crea resellers, emite créditos, ajustes
  globales, auditoría completa.
* **reseller**     -> gestiona únicamente sus propias líneas y sus usuarios
  finales, con un saldo de créditos que se descuenta al crear/renovar líneas.
* **user**         -> solo lectura sobre sus propias líneas.

Todas las acciones sensibles generan una entrada en ``audit_logs`` y los
movimientos de créditos en ``transactions`` (libro mayor con saldo resultante).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status

from . import db as database
from .config import settings
from .security import AuthContext, ROLE_RESELLER, ROLE_SUPER_ADMIN, ROLE_USER, check_password_policy, hash_password


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def row_to_dict(row: Optional[sqlite3.Row], skip: Iterable[str] = ()) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    skip = set(skip)
    return {key: row[key] for key in row.keys() if key not in skip}


def line_effective_status(line: sqlite3.Row | dict[str, Any]) -> str:
    """Devuelve active|expired|suspended|inactive según fechas y estado."""
    data = dict(line)
    if data.get("status") == "suspended":
        return "suspended"
    expires = parse_dt(data.get("expires_at"))
    if expires and expires < utcnow():
        return "expired"
    if expires and (expires - utcnow()) < timedelta(days=3):
        return "expiring"
    return "active"


def audit(
    conn: sqlite3.Connection,
    ctx: Optional[AuthContext],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[Any] = None,
    ip: Optional[str] = None,
) -> None:
    database.execute(
        conn,
        "INSERT INTO audit_logs (actor_id, actor_username, action, target_type, target_id, details, ip, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ctx.id if ctx else None,
            ctx.username if ctx else "system",
            action,
            target_type,
            target_id,
            json.dumps(details, ensure_ascii=False) if details is not None else None,
            ip,
            database.utcnow(),
        ),
    )


# ---------------------------------------------------------------------------
# créditos
# ---------------------------------------------------------------------------
def _locked_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = database.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada")
    return row


def apply_credits(
    conn: sqlite3.Connection,
    user_id: int,
    amount: int,
    kind: str,
    description: Optional[str],
    actor: Optional[AuthContext],
) -> int:
    """Aplica un movimiento de créditos y devuelve el saldo resultante."""
    user = _locked_user(conn, user_id)
    balance = int(user["credits"]) + int(amount)
    if balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Créditos insuficientes: saldo {user['credits']}, requerido {abs(int(amount))}",
        )

    database.update(conn, "users", user_id, {"credits": balance, "updated_at": database.utcnow()})
    database.insert(
        conn,
        "transactions",
        {
            "user_id": user_id,
            "actor_id": actor.id if actor else None,
            "amount": int(amount),
            "balance_after": balance,
            "kind": kind,
            "description": description,
            "created_at": database.utcnow(),
        },
    )
    return balance


def billing_value(conn: sqlite3.Connection, key: str, fallback: int) -> int:
    raw = database.get_setting(conn, key, str(fallback))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def charge_for_lines(
    conn: sqlite3.Connection,
    ctx: AuthContext,
    owner: sqlite3.Row,
    lines: int,
    concept: str,
    unit_cost_key: str = "billing.line_cost",
) -> int:
    """Descuenta del propietario el coste de crear/renovar líneas.

    El super administrador no paga (créditos ilimitados a efectos del panel).
    """
    if ctx.is_super_admin and int(owner["id"]) != ctx.id:
        return 0
    if owner["role"] == ROLE_SUPER_ADMIN and ctx.is_super_admin:
        return 0

    cost = billing_value(conn, unit_cost_key, settings.line_cost_credits) * max(lines, 1)
    if cost <= 0:
        return 0
    return apply_credits(conn, int(owner["id"]), -cost, "debit", concept, ctx)


# ---------------------------------------------------------------------------
# cuentas
# ---------------------------------------------------------------------------
def visible_user_ids(conn: sqlite3.Connection, ctx: AuthContext) -> Optional[list[int]]:
    """IDs de cuentas visibles para el usuario autenticado (None = todas)."""
    if ctx.is_super_admin:
        return None
    ids = [ctx.id]
    rows = database.query(conn, "SELECT id FROM users WHERE parent_id = ?", (ctx.id,))
    ids.extend(int(row["id"]) for row in rows)
    return ids


def list_accounts(
    conn: sqlite3.Connection,
    ctx: AuthContext,
    search: Optional[str] = None,
    role: Optional[str] = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM users WHERE 1 = 1"
    params: list[Any] = []

    if not ctx.is_super_admin:
        sql += " AND (id = ? OR parent_id = ?)"
        params.extend([ctx.id, ctx.id])
    if role:
        sql += " AND role = ?"
        params.append(role)
    if search:
        sql += " AND (username LIKE ? OR email LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    sql += " ORDER BY CASE role WHEN 'super_admin' THEN 0 WHEN 'reseller' THEN 1 ELSE 2 END, username"
    rows = database.query(conn, sql, params)

    result: list[dict[str, Any]] = []
    for row in rows:
        item = row_to_dict(row, skip=("password_hash", "api_key_hash"))
        item["lines_count"] = int(
            database.query_one(conn, "SELECT COUNT(*) AS c FROM lines WHERE owner_id = ?", (row["id"],))["c"]
        )
        result.append(item)
    return result


def get_account(conn: sqlite3.Connection, ctx: AuthContext, account_id: int) -> sqlite3.Row:
    user = _locked_user(conn, account_id)
    if not ctx.is_super_admin and int(user["id"]) != ctx.id and int(user["parent_id"] or 0) != ctx.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos sobre esta cuenta")
    return user


def create_account(conn: sqlite3.Connection, ctx: AuthContext, payload: dict[str, Any]) -> sqlite3.Row:
    role = payload.get("role") or ROLE_USER

    if role == ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No se pueden crear super administradores")
    if ctx.is_reseller and role != ROLE_USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Un revendedor solo puede crear usuarios finales",
        )
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para crear cuentas")

    username = payload["username"].strip()
    if database.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese usuario ya existe")

    password = payload["password"]
    check_password_policy(password)

    parent_id = ctx.id if ctx.is_reseller else payload.get("parent_id")
    if parent_id is not None:
        parent = _locked_user(conn, int(parent_id))
        if ctx.is_reseller and int(parent["id"]) != ctx.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El padre debe ser usted mismo")
        parent_id = int(parent["id"])

    initial_credits = int(payload.get("credits") or 0)
    if ctx.is_reseller and initial_credits > 0:
        # el reseller adelanta créditos de su propio saldo al nuevo usuario
        apply_credits(conn, ctx.id, -initial_credits, "debit", f"Créditos iniciales para {username}", ctx)

    now = database.utcnow()
    user_id = database.insert(
        conn,
        "users",
        {
            "username": username,
            "password_hash": hash_password(password),
            "role": role,
            "email": payload.get("email"),
            "parent_id": parent_id,
            "credits": initial_credits,
            "max_lines": int(payload.get("max_lines") or 0),
            "status": "active",
            "notes": payload.get("notes"),
            "created_at": now,
            "updated_at": now,
        },
    )
    audit(conn, ctx, "account.create", "user", user_id, {"username": username, "role": role})
    return _locked_user(conn, user_id)


def update_account(conn: sqlite3.Connection, ctx: AuthContext, account_id: int, payload: dict[str, Any]) -> sqlite3.Row:
    user = get_account(conn, ctx, account_id)
    if user["role"] == ROLE_SUPER_ADMIN and not ctx.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")

    values: dict[str, Any] = {"updated_at": database.utcnow()}
    changes: dict[str, Any] = {}

    if payload.get("password"):
        check_password_policy(payload["password"])
        values["password_hash"] = hash_password(payload["password"])
        changes["password"] = "changed"

    for field in ("email", "notes"):
        if field in payload and payload[field] is not None:
            values[field] = payload[field]
            changes[field] = payload[field]

    if payload.get("status"):
        if payload["status"] == "suspended" and int(user["id"]) == ctx.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puede suspenderse a sí mismo")
        values["status"] = payload["status"]
        changes["status"] = payload["status"]

    # solo el super administrador puede fijar créditos directamente o límites
    if ctx.is_super_admin:
        if payload.get("credits") is not None and int(payload["credits"]) != int(user["credits"]):
            delta = int(payload["credits"]) - int(user["credits"])
            apply_credits(conn, int(user["id"]), delta, "adjust", "Ajuste manual", ctx)
            changes["credits"] = payload["credits"]
        if payload.get("max_lines") is not None:
            values["max_lines"] = int(payload["max_lines"])
            changes["max_lines"] = payload["max_lines"]

    database.update(conn, "users", account_id, values)
    audit(conn, ctx, "account.update", "user", account_id, changes)
    return _locked_user(conn, account_id)


def delete_account(conn: sqlite3.Connection, ctx: AuthContext, account_id: int) -> None:
    user = get_account(conn, ctx, account_id)
    if int(user["id"]) == ctx.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puede eliminar su propia cuenta")
    if not ctx.is_super_admin and user["role"] != ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el super admin elimina revendedores")

    database.execute(conn, "DELETE FROM users WHERE id = ?", (account_id,))
    audit(conn, ctx, "account.delete", "user", account_id, {"username": user["username"]})


def transfer_credits(
    conn: sqlite3.Connection, ctx: AuthContext, target_id: int, amount: int, description: Optional[str]
) -> dict[str, int]:
    """Un reseller (o el super admin) pasa créditos a una cuenta hija."""
    target = _locked_user(conn, target_id)
    ctx_row = _locked_user(conn, ctx.id)

    if not ctx.is_super_admin and int(target["parent_id"] or 0) != ctx.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puede transferir a sus usuarios")

    source_balance = apply_credits(
        conn, ctx.id, -int(amount), "debit", description or f"Transferencia a {target['username']}", ctx
    )
    target_balance = apply_credits(
        conn, target_id, int(amount), "topup", description or f"Transferencia de {ctx_row['username']}", ctx
    )
    audit(conn, ctx, "credits.transfer", "user", target_id, {"amount": amount})
    return {"source_balance": source_balance, "target_balance": target_balance}


def rotate_api_key(conn: sqlite3.Connection, ctx: AuthContext, account_id: int) -> tuple[str, str]:
    from .security import generate_api_key  # import local para evitar ciclos

    user = get_account(conn, ctx, account_id)
    if not ctx.is_super_admin and int(user["id"]) != ctx.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")

    raw, key_hash, prefix = generate_api_key()
    database.update(
        conn,
        "users",
        int(user["id"]),
        {"api_key_hash": key_hash, "api_key_prefix": prefix, "updated_at": database.utcnow()},
    )
    audit(conn, ctx, "account.api_key", "user", int(user["id"]), {"prefix": prefix})
    return raw, prefix


# ---------------------------------------------------------------------------
# líneas
# ---------------------------------------------------------------------------
def list_lines(
    conn: sqlite3.Connection,
    ctx: AuthContext,
    owner_id: Optional[int] = None,
    protocol: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT l.*, u.username AS owner_username, u.role AS owner_role"
        " FROM lines l JOIN users u ON u.id = l.owner_id WHERE 1 = 1"
    )
    params: list[Any] = []

    if ctx.is_super_admin:
        if owner_id:
            sql += " AND l.owner_id = ?"
            params.append(owner_id)
    elif ctx.is_reseller:
        sql += " AND (l.owner_id = ? OR l.owner_id IN (SELECT id FROM users WHERE parent_id = ?))"
        params.extend([ctx.id, ctx.id])
    else:
        sql += " AND l.owner_id = ?"
        params.append(ctx.id)

    if protocol:
        sql += " AND l.protocol = ?"
        params.append(protocol)
    if search:
        sql += " AND (l.name LIKE ? OR l.username LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    sql += " ORDER BY l.created_at DESC"
    rows = database.query(conn, sql, params)
    result = []
    for row in rows:
        item = row_to_dict(row, skip=("password",)) or {}
        item["password"] = None  # nunca se expone en los listados
        item["effective_status"] = line_effective_status(row)
        result.append(item)
    return result


def get_line(conn: sqlite3.Connection, ctx: AuthContext, line_id: int) -> sqlite3.Row:
    line = database.query_one(conn, "SELECT * FROM lines WHERE id = ?", (line_id,))
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Línea no encontrada")
    if not ctx.is_super_admin:
        owner = _locked_user(conn, int(line["owner_id"]))
        if int(line["owner_id"]) != ctx.id and int(owner["parent_id"] or 0) != ctx.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos sobre esta línea")
    return line


def generate_line_credentials(protocol: str, base: Optional[str] = None) -> tuple[str, str]:
    import secrets
    import string

    alphabet = string.ascii_lowercase + string.digits
    password_alphabet = string.ascii_letters + string.digits
    user = base or "".join(secrets.choice(alphabet) for _ in range(10))
    pwd = "".join(secrets.choice(password_alphabet) for _ in range(12))
    return user, pwd


def create_line(conn: sqlite3.Connection, ctx: AuthContext, payload: dict[str, Any]) -> sqlite3.Row:
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para crear líneas")

    owner_id = int(payload.get("owner_id") or ctx.id)
    owner = _locked_user(conn, owner_id)

    if not ctx.is_super_admin:
        if owner_id != ctx.id and int(owner["parent_id"] or 0) != ctx.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El propietario debe ser su usuario")

    if int(owner["max_lines"]) and owner_id != ctx.id:
        current = int(
            database.query_one(conn, "SELECT COUNT(*) AS c FROM lines WHERE owner_id = ?", (owner_id,))["c"]
        )
        if current >= int(owner["max_lines"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El usuario alcanzó su límite de {owner['max_lines']} líneas",
            )

    username, generated_pwd = generate_line_credentials(payload["protocol"], payload.get("username"))
    if database.query_one(conn, "SELECT id FROM lines WHERE username = ?", (username,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ese usuario de línea ya existe")

    days = int(payload.get("days") or settings.default_line_days)
    expires_at = (utcnow() + timedelta(days=days)).replace(microsecond=0).isoformat()
    now = database.utcnow()

    line_id = database.insert(
        conn,
        "lines",
        {
            "owner_id": owner_id,
            "name": payload["name"].strip(),
            "protocol": payload["protocol"],
            "username": username,
            "password": payload.get("password") or generated_pwd,
            "group_name": str(payload.get("group_name") or settings.default_group),
            "caid_allow": payload.get("caid_allow"),
            "max_connections": int(payload.get("max_connections") or 1),
            "expires_at": expires_at,
            "status": "active",
            "cacheex_mode": int(payload.get("cacheex_mode") or 0),
            "cacheex_maxhop": int(payload.get("cacheex_maxhop") or 0),
            "cacheex_disable": int(payload.get("cacheex_disable") or 0),
            "notify_email": payload.get("notify_email"),
            "notify_telegram": payload.get("notify_telegram"),
            "notify_days": int(payload.get("notify_days") or 0),
            "notes": payload.get("notes"),
            "created_at": now,
            "updated_at": now,
            "created_by": ctx.id,
        },
    )

    charge_for_lines(conn, ctx, owner, 1, f"Alta de línea {payload['name']}")
    audit(conn, ctx, "line.create", "line", line_id, {"name": payload["name"], "owner": owner["username"]})
    return get_line(conn, ctx, line_id)


def update_line(conn: sqlite3.Connection, ctx: AuthContext, line_id: int, payload: dict[str, Any]) -> sqlite3.Row:
    line = get_line(conn, ctx, line_id)
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para modificar líneas")

    allowed = (
        "name",
        "protocol",
        "group_name",
        "caid_allow",
        "max_connections",
        "status",
        "cacheex_mode",
        "cacheex_maxhop",
        "cacheex_disable",
        "notify_email",
        "notify_telegram",
        "notify_days",
        "notes",
    )
    values = {key: payload[key] for key in allowed if key in payload and payload[key] is not None}
    if not values:
        return line

    values["updated_at"] = database.utcnow()
    database.update(conn, "lines", line_id, values)
    audit(conn, ctx, "line.update", "line", line_id, values)
    return get_line(conn, ctx, line_id)


def delete_line(conn: sqlite3.Connection, ctx: AuthContext, line_id: int) -> None:
    line = get_line(conn, ctx, line_id)
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para eliminar líneas")
    database.execute(conn, "DELETE FROM lines WHERE id = ?", (line_id,))
    audit(conn, ctx, "line.delete", "line", line_id, {"name": line["name"], "username": line["username"]})


def renew_line(conn: sqlite3.Connection, ctx: AuthContext, line_id: int, days: int) -> sqlite3.Row:
    line = get_line(conn, ctx, line_id)
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para renovar líneas")

    owner = _locked_user(conn, int(line["owner_id"]))
    current_expiry = parse_dt(line["expires_at"])
    base = current_expiry if current_expiry and current_expiry > utcnow() else utcnow()
    new_expiry = (base + timedelta(days=days)).replace(microsecond=0).isoformat()

    charge_for_lines(conn, ctx, owner, 1, f"Renovación de línea {line['name']} (+{days} días)", "billing.renew_cost")
    database.update(
        conn,
        "lines",
        line_id,
        {"expires_at": new_expiry, "status": "active", "updated_at": database.utcnow()},
    )
    audit(conn, ctx, "line.renew", "line", line_id, {"days": days, "expires_at": new_expiry})
    return get_line(conn, ctx, line_id)


def reset_line_password(conn: sqlite3.Connection, ctx: AuthContext, line_id: int) -> tuple[sqlite3.Row, str]:
    line = get_line(conn, ctx, line_id)
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    _, new_password = generate_line_credentials(str(line["protocol"]))
    database.update(
        conn, "lines", line_id, {"password": new_password, "updated_at": database.utcnow()}
    )
    audit(conn, ctx, "line.password_reset", "line", line_id, {})
    return get_line(conn, ctx, line_id), new_password


def reveal_line_password(conn: sqlite3.Connection, ctx: AuthContext, line_id: int) -> str:
    line = get_line(conn, ctx, line_id)
    audit(conn, ctx, "line.password_reveal", "line", line_id, {})
    return str(line["password"])


# ---------------------------------------------------------------------------
# peers de caché
# ---------------------------------------------------------------------------
def list_cache_servers(conn: sqlite3.Connection, ctx: AuthContext) -> list[dict[str, Any]]:
    if ctx.is_super_admin:
        rows = database.query(
            conn,
            "SELECT c.*, u.username AS owner_username FROM cache_servers c"
            " JOIN users u ON u.id = c.owner_id ORDER BY c.priority DESC, c.name",
        )
    else:
        rows = database.query(
            conn,
            "SELECT c.*, u.username AS owner_username FROM cache_servers c"
            " JOIN users u ON u.id = c.owner_id WHERE c.owner_id = ? ORDER BY c.priority DESC, c.name",
            (ctx.id,),
        )
    return [row_to_dict(row, skip=("password",)) or {} for row in rows]


def get_cache_server(conn: sqlite3.Connection, ctx: AuthContext, server_id: int) -> sqlite3.Row:
    row = database.query_one(conn, "SELECT * FROM cache_servers WHERE id = ?", (server_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer de caché no encontrado")
    if not ctx.owns(int(row["owner_id"])):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos sobre este peer")
    return row


def create_cache_server(conn: sqlite3.Connection, ctx: AuthContext, payload: dict[str, Any]) -> sqlite3.Row:
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    owner_id = int(payload.get("owner_id") or ctx.id)
    if not ctx.owns(owner_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Propietario no válido")

    now = database.utcnow()
    server_id = database.insert(
        conn,
        "cache_servers",
        {
            "owner_id": owner_id,
            "name": payload["name"],
            "host": payload["host"],
            "port": int(payload["port"]),
            "protocol": payload.get("protocol") or "cccam",
            "username": payload.get("username"),
            "password": payload.get("password"),
            "node_id": payload.get("node_id"),
            "priority": int(payload.get("priority") or 0),
            "enabled": 1 if payload.get("enabled", True) else 0,
            "created_at": now,
            "updated_at": now,
        },
    )
    audit(conn, ctx, "cache_server.create", "cache_server", server_id, {"name": payload["name"]})
    return get_cache_server(conn, ctx, server_id)


def update_cache_server(
    conn: sqlite3.Connection, ctx: AuthContext, server_id: int, payload: dict[str, Any]
) -> sqlite3.Row:
    get_cache_server(conn, ctx, server_id)
    allowed = ("name", "host", "port", "protocol", "username", "password", "node_id", "priority", "enabled")
    values: dict[str, Any] = {}
    for key in allowed:
        if key in payload and payload[key] is not None:
            values[key] = 1 if (key == "enabled" and payload[key]) else payload[key]
    if not values:
        return get_cache_server(conn, ctx, server_id)
    values["updated_at"] = database.utcnow()
    database.update(conn, "cache_servers", server_id, values)
    audit(conn, ctx, "cache_server.update", "cache_server", server_id, {k: v for k, v in values.items() if k != "password"})
    return get_cache_server(conn, ctx, server_id)


def delete_cache_server(conn: sqlite3.Connection, ctx: AuthContext, server_id: int) -> None:
    get_cache_server(conn, ctx, server_id)
    database.execute(conn, "DELETE FROM cache_servers WHERE id = ?", (server_id,))
    audit(conn, ctx, "cache_server.delete", "cache_server", server_id, {})


# ---------------------------------------------------------------------------
# métricas
# ---------------------------------------------------------------------------
def overview(conn: sqlite3.Connection, ctx: AuthContext) -> dict[str, Any]:
    if ctx.is_super_admin:
        scope = ""
        params: tuple[Any, ...] = ()
    else:
        scope = " WHERE owner_id = ?"
        params = (ctx.id,)

    total_lines = int(database.query_one(conn, f"SELECT COUNT(*) AS c FROM lines{scope}", params)["c"])
    active_lines = int(
        database.query_one(
            conn,
            f"SELECT COUNT(*) AS c FROM lines{scope} {'AND' if scope else 'WHERE'} status = 'active'",
            params,
        )["c"]
    )
    expired = 0
    expiring = 0
    for row in database.query(conn, f"SELECT * FROM lines{scope}", params):
        state = line_effective_status(row)
        if state == "expired":
            expired += 1
        elif state == "expiring":
            expiring += 1

    if ctx.is_super_admin:
        accounts_row = database.query_one(
            conn,
            "SELECT"
            " SUM(CASE WHEN role = 'reseller' THEN 1 ELSE 0 END) AS resellers,"
            " SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS users,"
            " SUM(CASE WHEN status = 'suspended' THEN 1 ELSE 0 END) AS suspended,"
            " SUM(credits) AS credits"
            " FROM users",
        )
        own = database.query_one(conn, "SELECT credits FROM users WHERE id = ?", (ctx.id,))
    else:
        accounts_row = database.query_one(
            conn,
            "SELECT 0 AS resellers, COUNT(*) AS users,"
            " SUM(CASE WHEN status = 'suspended' THEN 1 ELSE 0 END) AS suspended,"
            " SUM(credits) AS credits FROM users WHERE parent_id = ?",
            (ctx.id,),
        )
        own = database.query_one(conn, "SELECT credits FROM users WHERE id = ?", (ctx.id,))

    peers = database.query_one(
        conn,
        "SELECT COUNT(*) AS c, SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled FROM cache_servers"
        + ("" if ctx.is_super_admin else " WHERE owner_id = ?"),
        () if ctx.is_super_admin else (ctx.id,),
    )

    return {
        "lines": {
            "total": total_lines,
            "active": active_lines,
            "expired": expired,
            "expiring_soon": expiring,
        },
        "accounts": {
            "resellers": int(accounts_row["resellers"] or 0),
            "users": int(accounts_row["users"] or 0),
            "suspended": int(accounts_row["suspended"] or 0),
            "credits_total": int(accounts_row["credits"] or 0),
        },
        "credits": int(own["credits"] if own else 0),
        "cache_servers": {
            "total": int(peers["c"] or 0),
            "enabled": int(peers["enabled"] or 0),
        },
    }


def record_snapshot(
    conn: sqlite3.Connection, metrics: dict[str, float], source: str = "ncam"
) -> int:
    now = database.utcnow()
    count = 0
    for metric, value in metrics.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        database.execute(
            conn,
            "INSERT INTO usage_snapshots (captured_at, source, metric, value) VALUES (?, ?, ?, ?)",
            (now, source, metric, numeric),
        )
        count += 1
    return count


def timeseries(conn: sqlite3.Connection, metric: str, hours: int = 24, limit: int = 500) -> list[dict[str, Any]]:
    since = (utcnow() - timedelta(hours=max(1, min(hours, 24 * 30)))).replace(microsecond=0).isoformat()
    rows = database.query(
        conn,
        "SELECT captured_at, value FROM usage_snapshots"
        " WHERE metric = ? AND captured_at >= ? ORDER BY captured_at LIMIT ?",
        (metric, since, limit),
    )
    return [{"at": row["captured_at"], "value": row["value"]} for row in rows]


def purge_snapshots(conn: sqlite3.Connection, days: int = 30) -> int:
    cutoff = (utcnow() - timedelta(days=max(1, days))).replace(microsecond=0).isoformat()
    cur = database.execute(conn, "DELETE FROM usage_snapshots WHERE captured_at < ?", (cutoff,))
    return cur.rowcount or 0
