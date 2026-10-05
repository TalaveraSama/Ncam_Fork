"""
NCam-NG Panel :: avisos de caducidad de líneas.

Envía recordatorios cuando una línea está a punto de expirar, por dos canales
independientes y sin dependencias externas:

* **email**     -> ``smtplib`` (STARTTLS opcional).
* **telegram**  -> Bot API por HTTPS con ``urllib``.

El módulo es *testeable*: el envío real está aislado en :func:`send_email` y
:func:`send_telegram`, de forma que las pruebas pueden sustituirlos.

Reglas
------
* Cada línea avisa con ``notify_days`` días de antelación (0 = ``notify.days_before``).
* Destino: ``lines.notify_email`` / ``lines.notify_telegram``; si están vacíos se
  usa el email del propietario y el chat por defecto del panel.
* Antiduplicado: no se envía más de un aviso por línea y canal en 20 horas, y
  nunca dos veces con los mismos días restantes.
* Todo intento queda registrado en ``notification_log`` (enviado, fallido o
  omitido), y los envíos se auditan.
"""

from __future__ import annotations

import json
import math
import smtplib
import sqlite3
import ssl
import urllib.error
import urllib.request
from datetime import timedelta
from email.message import EmailMessage
from typing import Any, Optional

from . import db as database
from .config import settings
from .services import parse_dt, utcnow

DEDUPE_HOURS = 20
TELEGRAM_TIMEOUT = 10
SMTP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# ajustes
# ---------------------------------------------------------------------------
def _as_bool(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on", "si", "sí")


def notification_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    """Ajustes de notificaciones ya normalizados."""
    raw = database.get_settings(conn)
    return {
        "enabled": _as_bool(raw.get("notify.enabled", "0")),
        "days_before": _as_int(raw.get("notify.days_before"), 3),
        "email_enabled": _as_bool(raw.get("notify.channel.email", "0")),
        "telegram_enabled": _as_bool(raw.get("notify.channel.telegram", "0")),
        "interval_seconds": max(60, _as_int(raw.get("notify.interval_seconds"), 3600)),
        "smtp": {
            "host": (raw.get("notify.smtp.host") or "").strip(),
            "port": _as_int(raw.get("notify.smtp.port"), 587),
            "user": (raw.get("notify.smtp.user") or "").strip(),
            "password": raw.get("notify.smtp.password") or "",
            "from": (raw.get("notify.smtp.from") or raw.get("notify.smtp.user") or "").strip(),
            "starttls": _as_bool(raw.get("notify.smtp.starttls", "1")),
        },
        "telegram": {
            "bot_token": (raw.get("notify.telegram.bot_token") or "").strip(),
            "chat_id": (raw.get("notify.telegram.chat_id") or "").strip(),
        },
        "panel_name": raw.get("panel.name") or settings.panel_name,
    }


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# líneas por caducar
# ---------------------------------------------------------------------------
def expiring_lines(
    conn: sqlite3.Connection,
    ctx: Any = None,
    days: Optional[int] = None,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Líneas activas a menos de ``days`` días de expirar, ordenadas por fecha.

    ``ctx`` limita el resultado a lo que ese usuario puede ver (un reseller solo
    ve sus líneas y las de sus usuarios).
    """
    limit_days = _as_int(days, notification_settings(conn)["days_before"])
    limit_days = max(1, min(limit_days, 365))
    now = utcnow()
    threshold = (now + timedelta(days=limit_days)).replace(microsecond=0).isoformat()

    sql = (
        "SELECT l.*, u.username AS owner_username, u.email AS owner_email, u.parent_id AS owner_parent_id"
        " FROM lines l JOIN users u ON u.id = l.owner_id"
        " WHERE l.status = 'active' AND l.expires_at IS NOT NULL AND l.expires_at <= ?"
    )
    params: list[Any] = [threshold]
    if not include_expired:
        sql += " AND l.expires_at > ?"
        params.append(now.replace(microsecond=0).isoformat())
    if ctx is not None and not getattr(ctx, "is_super_admin", False):
        sql += " AND (l.owner_id = ? OR u.parent_id = ?)"
        params.extend([ctx.id, ctx.id])
    sql += " ORDER BY l.expires_at ASC"

    result: list[dict[str, Any]] = []
    for row in database.query(conn, sql, params):
        data = dict(row)
        expires = parse_dt(data.get("expires_at"))
        data["days_left"] = max(0, math.ceil((expires - now).total_seconds() / 86400)) if expires else 0
        data["notify_days"] = int(data.get("notify_days") or 0) or limit_days
        result.append(data)
    return result


def _threshold_for(line: dict[str, Any], default_days: int) -> int:
    raw = int(line.get("notify_days") or 0)
    return raw if raw > 0 else default_days


def _targets(line: dict[str, Any], conf: dict[str, Any]) -> dict[str, str]:
    return {
        "email": (line.get("notify_email") or line.get("owner_email") or "").strip(),
        "telegram": (line.get("notify_telegram") or conf["telegram"]["chat_id"] or "").strip(),
    }


def _already_notified(
    conn: sqlite3.Connection, line_id: int, channel: str, days_left: int
) -> Optional[str]:
    """Motivo por el que no se debe reenviar, o ``None`` si toca enviar."""
    since = (utcnow() - timedelta(hours=DEDUPE_HOURS)).replace(microsecond=0).isoformat()
    recent = database.query_one(
        conn,
        "SELECT * FROM notification_log WHERE line_id = ? AND channel = ? AND created_at >= ?"
        " ORDER BY created_at DESC LIMIT 1",
        (line_id, channel, since),
    )
    if not recent:
        return None
    if recent["status"] == "failed":
        return None  # se reintenta en la siguiente pasada
    if int(recent["days_left"]) == int(days_left):
        return f"ya avisado con {days_left} días restantes el {recent['created_at']}"
    return f"ya se envió un aviso en las últimas {DEDUPE_HOURS} h"


# ---------------------------------------------------------------------------
# plantillas
# ---------------------------------------------------------------------------
def build_message(line: dict[str, Any], days_left: int, panel_name: str) -> tuple[str, str]:
    unit = "día" if days_left == 1 else "días"
    subject = f"[{panel_name}] La línea '{line['name']}' caduca en {days_left} {unit}"
    body = (
        f"Panel: {panel_name}\n"
        f"Línea: {line['name']} ({line['protocol']}, usuario {line['username']})\n"
        f"Propietario: {line.get('owner_username') or '-'}\n"
        f"Fecha de caducidad: {line['expires_at']}\n"
        f"Días restantes: {days_left}\n\n"
        "Renueve la línea desde el panel para evitar la interrupción del servicio.\n"
    )
    return subject, body


# ---------------------------------------------------------------------------
# canales
# ---------------------------------------------------------------------------
def send_email(conf: dict[str, Any], target: str, subject: str, body: str) -> None:
    """Envía un correo. Lanza excepción si algo falla (la captura el llamador)."""
    smtp_conf = conf["smtp"]
    if not smtp_conf["host"]:
        raise RuntimeError("sin servidor SMTP configurado (notify.smtp.host)")
    if not target:
        raise RuntimeError("sin destinatario")
    sender = smtp_conf["from"] or smtp_conf["user"] or "ncam-panel@localhost"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = target
    message.set_content(body)

    with smtplib.SMTP(smtp_conf["host"], smtp_conf["port"], timeout=SMTP_TIMEOUT) as server:
        if smtp_conf["starttls"]:
            server.starttls(context=ssl.create_default_context())
        if smtp_conf["user"]:
            server.login(smtp_conf["user"], smtp_conf["password"])
        server.send_message(message)


def send_telegram(conf: dict[str, Any], target: str, text: str) -> None:
    """Envía un mensaje por la Bot API de Telegram."""
    token = conf["telegram"]["bot_token"]
    if not token:
        raise RuntimeError("sin token de bot configurado (notify.telegram.bot_token)")
    if not target:
        raise RuntimeError("sin chat_id")
    payload = json.dumps({"chat_id": target, "text": text, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TELEGRAM_TIMEOUT) as response:
        if response.status >= 300:
            raise RuntimeError(f"Telegram respondió HTTP {response.status}")


def _record(
    conn: sqlite3.Connection,
    line: dict[str, Any],
    channel: str,
    target: str,
    days_left: int,
    status: str,
    error: Optional[str] = None,
) -> None:
    database.insert(
        conn,
        "notification_log",
        {
            "line_id": line.get("id"),
            "owner_id": line.get("owner_id"),
            "channel": channel,
            "target": target or None,
            "days_left": int(days_left),
            "expires_at": line.get("expires_at"),
            "status": status,
            "error": error,
            "created_at": database.utcnow(),
        },
    )


# ---------------------------------------------------------------------------
# ejecución
# ---------------------------------------------------------------------------
def run_notifications(
    conn: sqlite3.Connection,
    ctx: Any = None,
    days: Optional[int] = None,
    dry_run: bool = False,
    channels: Optional[list[str]] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Recorre las líneas por caducar y envía los avisos pendientes.

    ``force`` ignora las reglas antiduplicado (útil para probar desde el panel).
    """
    conf = notification_settings(conn)
    selected = [c for c in (channels or ["email", "telegram"]) if c in ("email", "telegram")]
    if not selected:
        selected = ["email"]

    lines = expiring_lines(conn, ctx, days=days)
    report: dict[str, Any] = {
        "checked_lines": len(lines),
        "dry_run": bool(dry_run),
        "channels": selected,
        "sent": [],
        "failed": [],
        "skipped": [],
        "days_before": _as_int(days, conf["days_before"]),
    }

    for line in lines:
        days_left = int(line["days_left"])
        if days_left > _threshold_for(line, report["days_before"]):
            report["skipped"].append({"line_id": line["id"], "reason": "todavía no toca avisar"})
            continue

        targets = _targets(line, conf)
        subject, body = build_message(line, days_left, conf["panel_name"])

        for channel in selected:
            target = targets.get(channel) or ""
            if channel == "email" and not conf["email_enabled"]:
                report["skipped"].append({"line_id": line["id"], "channel": channel, "reason": "canal email desactivado"})
                continue
            if channel == "telegram" and not conf["telegram_enabled"]:
                report["skipped"].append({"line_id": line["id"], "channel": channel, "reason": "canal telegram desactivado"})
                continue
            if not target:
                report["skipped"].append({"line_id": line["id"], "channel": channel, "reason": "sin destino configurado"})
                if not dry_run:
                    _record(conn, line, channel, "", days_left, "skipped", "sin destino configurado")
                continue
            if not force:
                reason = _already_notified(conn, int(line["id"]), channel, days_left)
                if reason:
                    report["skipped"].append({"line_id": line["id"], "channel": channel, "reason": reason})
                    continue

            if dry_run:
                report["sent"].append(
                    {"line_id": line["id"], "channel": channel, "target": target, "days_left": days_left, "dry_run": True}
                )
                continue

            try:
                if channel == "email":
                    send_email(conf, target, subject, body)
                else:
                    send_telegram(conf, target, f"{subject}\n\n{body}")
                _record(conn, line, channel, target, days_left, "sent")
                report["sent"].append(
                    {"line_id": line["id"], "channel": channel, "target": target, "days_left": days_left}
                )
            except (OSError, smtplib.SMTPException, urllib.error.URLError, RuntimeError, ValueError) as exc:
                message = str(exc)[:300]
                _record(conn, line, channel, target, days_left, "failed", message)
                report["failed"].append({"line_id": line["id"], "channel": channel, "error": message})

    return report


def notification_history(conn: sqlite3.Connection, ctx: Any = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    sql = (
        "SELECT n.*, l.name AS line_name, l.username AS line_username, u.username AS owner_username"
        " FROM notification_log n LEFT JOIN lines l ON l.id = n.line_id"
        " LEFT JOIN users u ON u.id = n.owner_id WHERE 1 = 1"
    )
    params: list[Any] = []
    if ctx is not None and not getattr(ctx, "is_super_admin", False):
        sql += " AND (n.owner_id = ? OR n.owner_id IN (SELECT id FROM users WHERE parent_id = ?))"
        params.extend([ctx.id, ctx.id])
    sql += " ORDER BY n.created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in database.query(conn, sql, params)]
