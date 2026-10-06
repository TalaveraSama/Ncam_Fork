"""
NCPanel :: facturación por consumo real de ECM.

El daemon NCam publica en ``/ncamapi.json?part=userstats`` el contador acumulado
de ECM servidas por cada cuenta (``cwok``). Cada línea del panel corresponde a
una cuenta del daemon, así que el consumo se puede medir y facturar:

1. :func:`refresh_usage` lee los contadores del daemon y guarda el avance de
   cada línea (``lines.ecm_total``) junto con el delta medido en ``ecm_usage``.
2. :func:`bill_usage` convierte los bloques completos pendientes
   (``ecm_total - ecm_billed``) en créditos y los descuenta del propietario,
   anotándolo en el libro mayor (``transactions``).
3. Si el propietario no tiene saldo, los bloques quedan pendientes (nunca se
   factura por adelantado) y, opcionalmente, la línea se suspende.

Los contadores del daemon se reinician cuando el daemon se reinicia: en ese caso
el delta se considera 0 y el contador se reajusta, sin cobrar de más.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from . import db as database
from . import ncam
from .services import audit, billing_value

CHANNEL = "ecm"


# ---------------------------------------------------------------------------
# ajustes
# ---------------------------------------------------------------------------
def _as_bool(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on", "si", "sí")


def billing_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    raw = database.get_settings(conn)
    block = max(1, billing_value(conn, "billing.ecm.block", 1000))
    price = max(0, billing_value(conn, "billing.ecm.price", 10))
    interval = max(60, billing_value(conn, "billing.ecm.interval_seconds", 900))
    return {
        "enabled": _as_bool(raw.get("billing.ecm.enabled", "0")),
        "block": block,
        "price": price,
        "interval_seconds": interval,
        "suspend_on_debt": _as_bool(raw.get("billing.ecm.suspend_on_debt", "0")),
        "currency": raw.get("billing.currency") or "créditos",
    }


# ---------------------------------------------------------------------------
# medición
# ---------------------------------------------------------------------------
def refresh_usage(conn: sqlite3.Connection, owner_id: Optional[int] = None) -> dict[str, Any]:
    """Lee los contadores de ECM del daemon y actualiza el consumo de las líneas."""
    stats = ncam.fetch_user_stats(conn)
    if not stats.get("reachable"):
        return {"reachable": False, "error": stats.get("error"), "updated": 0, "measured": []}

    counters: dict[str, dict[str, Any]] = stats.get("users") or {}
    measured: list[dict[str, Any]] = []
    now = database.utcnow()

    for line in database.query(conn, "SELECT * FROM lines WHERE status != 'suspended'"):
        if owner_id is not None and int(line["owner_id"]) != int(owner_id):
            continue
        block = counters.get(ncam.user_md5(line["username"]))
        if not block:
            # la línea aún no existe en el daemon (no exportada / no recargada)
            continue

        previous = int(line["ecm_total"] or 0)
        current = int(block["ecm_ok"])
        # el contador del daemon se reinicia al reiniciarlo: no inventar consumo
        delta = current - previous if current >= previous else 0

        values: dict[str, Any] = {"ecm_total": current, "updated_at": now}
        if delta:
            values["ecm_billed"] = int(line["ecm_billed"] or 0)
        database.update(conn, "lines", int(line["id"]), values)

        if delta or previous != current:
            database.insert(
                conn,
                "ecm_usage",
                {
                    "line_id": int(line["id"]),
                    "owner_id": int(line["owner_id"]),
                    "measured_at": now,
                    "ecm_ok": current,
                    "ecm_delta": delta,
                    "note": "reinicio del daemon" if current < previous else None,
                },
            )

        measured.append({"line_id": int(line["id"]), "username": line["username"], "ecm_ok": current, "ecm_delta": delta})

    return {
        "reachable": True,
        "updated": len(measured),
        "measured": measured,
        "version": stats.get("version"),
        "revision": stats.get("revision"),
    }


# ---------------------------------------------------------------------------
# facturación
# ---------------------------------------------------------------------------
def _pending_blocks(conn: sqlite3.Connection, line: sqlite3.Row) -> int:
    conf = billing_settings(conn)
    pending = max(0, int(line["ecm_total"] or 0) - int(line["ecm_billed"] or 0))
    return pending // conf["block"]


def bill_usage(
    conn: sqlite3.Connection,
    ctx: Any = None,
    owner_id: Optional[int] = None,
    line_id: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Convierte los bloques de ECM pendientes en créditos y los cobra.

    Nunca factura por adelantado: solo bloques completos ya servidos. Si el
    propietario no tiene saldo suficiente, los bloques quedan pendientes para la
    siguiente pasada (y la línea se suspende si así está configurado).
    """
    conf = billing_settings(conn)
    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "block": conf["block"],
        "price": conf["price"],
        "currency": conf["currency"],
        "lines": [],
        "billed_credits": 0,
        "billed_blocks": 0,
        "skipped": [],
    }

    sql = "SELECT l.*, u.credits AS owner_credits, u.username AS owner_username FROM lines l JOIN users u ON u.id = l.owner_id WHERE l.status != 'suspended'"
    params: list[Any] = []
    if owner_id is not None:
        sql += " AND l.owner_id = ?"
        params.append(owner_id)
    if line_id is not None:
        sql += " AND l.id = ?"
        params.append(line_id)

    for line in database.query(conn, sql, params):
        blocks = _pending_blocks(conn, line)
        if not blocks:
            continue

        pending_ecm = int(line["ecm_total"] or 0) - int(line["ecm_billed"] or 0)
        owner = database.query_one(conn, "SELECT * FROM users WHERE id = ?", (int(line["owner_id"]),))
        if owner is None:
            continue

        # el super administrador no se factura a sí mismo
        if owner["role"] == "super_admin":
            report["skipped"].append(
                {"line_id": int(line["id"]), "reason": "propietario super admin (sin facturación)"}
            )
            continue

        credits_total = blocks * conf["price"]
        affordable = int(owner["credits"]) // conf["price"] if conf["price"] else blocks
        billable = min(blocks, affordable)
        unbilled = blocks - billable

        entry = {
            "line_id": int(line["id"]),
            "line": line["name"],
            "owner": owner["username"],
            "blocks": billable,
            "pending_blocks": unbilled,
            "ecm": billable * conf["block"],
            "pending_ecm": unbilled * conf["block"] + (pending_ecm % conf["block"]),
            "credits": billable * conf["price"],
            "dry_run": bool(dry_run),
        }
        report["lines"].append(entry)

        if unbilled:
            report["skipped"].append(
                {
                    "line_id": int(line["id"]),
                    "reason": f"saldo insuficiente: {unbilled} bloque(s) quedan pendientes",
                }
            )

        if dry_run:
            continue

        if not billable:
            if conf["suspend_on_debt"]:
                database.update(conn, "lines", int(line["id"]), {"status": "suspended"})
                report["skipped"].append(
                    {"line_id": int(line["id"]), "reason": "línea suspendida por consumo impagado"}
                )
            continue

        if conf["price"] > 0:
            database.update(
                conn,
                "users",
                int(owner["id"]),
                {
                    "credits": int(owner["credits"]) - entry["credits"],
                    "updated_at": database.utcnow(),
                },
            )
            database.insert(
                conn,
                "transactions",
                {
                    "user_id": int(owner["id"]),
                    "actor_id": ctx.id if ctx else None,
                    "amount": -entry["credits"],
                    "balance_after": int(owner["credits"]) - entry["credits"],
                    "kind": "debit",
                    "description": f"Consumo de {entry['ecm']} ECM de la línea {line['name']}",
                    "created_at": database.utcnow(),
                },
            )

        database.update(
            conn,
            "lines",
            int(line["id"]),
            {"ecm_billed": int(line["ecm_billed"] or 0) + entry["ecm"], "updated_at": database.utcnow()},
        )
        database.execute(
            conn,
            "UPDATE ecm_usage SET blocks = ?, credits = ? WHERE id = ("
            " SELECT id FROM ecm_usage WHERE line_id = ? ORDER BY id DESC LIMIT 1)",
            (entry["blocks"], entry["credits"], int(line["id"])),
        )

        if unbilled and conf["suspend_on_debt"]:
            database.update(conn, "lines", int(line["id"]), {"status": "suspended"})
            report["skipped"].append(
                {"line_id": int(line["id"]), "reason": "línea suspendida por consumo impagado"}
            )

        report["billed_credits"] += entry["credits"]
        report["billed_blocks"] += entry["blocks"]

    if not dry_run and ctx is not None and (report["billed_credits"] or report["skipped"]):
        audit(
            conn,
            ctx,
            "billing.ecm.run",
            "billing",
            None,
            {
                "credits": report["billed_credits"],
                "blocks": report["billed_blocks"],
                "lines": len(report["lines"]),
            },
        )

    return report


def run_billing(
    conn: sqlite3.Connection,
    ctx: Any = None,
    dry_run: bool = False,
    owner_id: Optional[int] = None,
    line_id: Optional[int] = None,
) -> dict[str, Any]:
    """Mide el consumo del daemon y factura los bloques completos pendientes."""
    measurement = refresh_usage(conn, owner_id=owner_id)
    billing = bill_usage(conn, ctx=ctx, owner_id=owner_id, line_id=line_id, dry_run=dry_run)
    return {"measurement": measurement, **billing}


# ---------------------------------------------------------------------------
# informes
# ---------------------------------------------------------------------------
def usage_report(
    conn: sqlite3.Connection, ctx: Any, owner_id: Optional[int] = None, line_id: Optional[int] = None
) -> dict[str, Any]:
    """Estado de consumo por línea (visible según el rol del usuario)."""
    conf = billing_settings(conn)
    sql = (
        "SELECT l.id, l.name, l.username, l.protocol, l.status, l.ecm_total, l.ecm_billed,"
        " l.owner_id, u.username AS owner_username FROM lines l JOIN users u ON u.id = l.owner_id"
        " WHERE 1 = 1"
    )
    params: list[Any] = []
    if ctx is not None and not getattr(ctx, "is_super_admin", False):
        sql += " AND (l.owner_id = ? OR u.parent_id = ?)"
        params.extend([ctx.id, ctx.id])
    if owner_id is not None:
        sql += " AND l.owner_id = ?"
        params.append(owner_id)
    if line_id is not None:
        sql += " AND l.id = ?"
        params.append(line_id)
    sql += " ORDER BY (l.ecm_total - l.ecm_billed) DESC, l.name"

    items = []
    for row in database.query(conn, sql, params):
        total = int(row["ecm_total"] or 0)
        billed = int(row["ecm_billed"] or 0)
        pending = max(0, total - billed)
        items.append(
            {
                "line_id": int(row["id"]),
                "line": row["name"],
                "username": row["username"],
                "protocol": row["protocol"],
                "status": row["status"],
                "owner_id": int(row["owner_id"]),
                "owner": row["owner_username"],
                "ecm_total": total,
                "ecm_billed": billed,
                "ecm_pending": pending,
                "blocks_pending": pending // conf["block"],
                "credits_pending": (pending // conf["block"]) * conf["price"],
            }
        )

    return {
        "items": items,
        "settings": conf,
        "currency": conf["currency"],
        "billed_credits_total": sum(item["credits_pending"] for item in items),
    }


def usage_history(
    conn: sqlite3.Connection, ctx: Any, line_id: Optional[int] = None, limit: int = 200
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    sql = (
        "SELECT e.*, l.name AS line_name, l.username AS line_username, u.username AS owner_username"
        " FROM ecm_usage e LEFT JOIN lines l ON l.id = e.line_id"
        " LEFT JOIN users u ON u.id = e.owner_id WHERE 1 = 1"
    )
    params: list[Any] = []
    if ctx is not None and not getattr(ctx, "is_super_admin", False):
        sql += " AND (e.owner_id = ? OR e.owner_id IN (SELECT id FROM users WHERE parent_id = ?))"
        params.extend([ctx.id, ctx.id])
    if line_id is not None:
        sql += " AND e.line_id = ?"
        params.append(line_id)
    sql += " ORDER BY e.id DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in database.query(conn, sql, params)]
