"""NCPanel :: avisos de caducidad (email / Telegram)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from .. import notifications
from ..models import NotificationRunRequest, NotificationTestRequest
from ..security import ROLE_USER, AuthContext, client_ip, current_user, get_db, require_super_admin
from ..services import audit, row_to_dict

router = APIRouter(tags=["notifications"])


@router.get("/notifications/expiring")
def expiring(
    days: int = Query(default=0, ge=0, le=365),
    include_expired: bool = Query(default=False),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Líneas a punto de caducar visibles para el usuario autenticado.

    ``days = 0`` usa el valor global (``notify.days_before``).
    """
    conf = notifications.notification_settings(conn)
    window = days or conf["days_before"]
    items = notifications.expiring_lines(conn, ctx, days=window, include_expired=include_expired)
    return {
        "items": [row_to_dict(item) for item in items],
        "days_before": window,
        "channels": {
            "email": conf["email_enabled"],
            "telegram": conf["telegram_enabled"],
        },
        "enabled": conf["enabled"],
    }


@router.post("/notifications/run")
def run_now(
    payload: NotificationRunRequest,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Envía los avisos pendientes (o simula el envío con ``dry_run``)."""
    if ctx.role == ROLE_USER:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para enviar avisos")

    report = notifications.run_notifications(
        conn,
        ctx,
        days=payload.days,
        dry_run=payload.dry_run,
        channels=payload.channels,
        force=payload.force,
    )
    if not payload.dry_run:
        audit(conn, ctx, "notification.run", "notifications", None, {
            "sent": len(report["sent"]),
            "failed": len(report["failed"]),
            "skipped": len(report["skipped"]),
            "days": report["days_before"],
        }, client_ip(request))
    return report


@router.get("/notifications/log")
def history(
    limit: int = Query(default=100, ge=1, le=500),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"items": notifications.notification_history(conn, ctx, limit)}


@router.get("/notifications/config")
def config(ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Resumen de la configuración activa (sin secretos)."""
    conf = notifications.notification_settings(conn)
    return {
        "enabled": conf["enabled"],
        "days_before": conf["days_before"],
        "interval_seconds": conf["interval_seconds"],
        "email": {
            "enabled": conf["email_enabled"],
            "host": conf["smtp"]["host"],
            "port": conf["smtp"]["port"],
            "from": conf["smtp"]["from"],
            "starttls": conf["smtp"]["starttls"],
            "ready": bool(conf["email_enabled"] and conf["smtp"]["host"]),
        },
        "telegram": {
            "enabled": conf["telegram_enabled"],
            "chat_id": conf["telegram"]["chat_id"],
            "ready": bool(conf["telegram_enabled"] and conf["telegram"]["bot_token"]),
        },
    }


@router.post("/notifications/test")
def send_test(
    payload: NotificationTestRequest,
    request: Request,
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Envía un mensaje de prueba por el canal indicado (solo super admin)."""
    conf = notifications.notification_settings(conn)
    subject = f"[{conf['panel_name']}] Mensaje de prueba"
    body = "Aviso de prueba enviado desde el panel NCam-NG. La configuración funciona."

    target = (payload.target or "").strip()
    if payload.channel == "email":
        target = target or conf["smtp"]["from"]
        notifications.send_email(conf, target, subject, body)
    else:
        target = target or conf["telegram"]["chat_id"]
        notifications.send_telegram(conf, target, f"{subject}\n\n{body}")

    audit(conn, ctx, "notification.test", "notifications", None, {"channel": payload.channel}, client_ip(request))
    return {"ok": True, "channel": payload.channel, "target": target}
