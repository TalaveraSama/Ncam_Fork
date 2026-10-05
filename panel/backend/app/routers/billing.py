"""NCam-NG Panel :: consumo de ECM y su facturación."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .. import billing
from ..models import BillingRunRequest
from ..security import ROLE_USER, AuthContext, client_ip, current_user, get_db, require_super_admin
from ..services import audit

router = APIRouter(tags=["billing"])


@router.get("/billing/ecm")
def usage(
    owner_id: Optional[int] = Query(default=None),
    line_id: Optional[int] = Query(default=None),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Consumo y saldo pendiente por línea (según el rol)."""
    if owner_id is not None and not ctx.is_super_admin and owner_id != ctx.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puede consultar sus cuentas")
    return billing.usage_report(conn, ctx, owner_id=owner_id, line_id=line_id)


@router.get("/billing/ecm/history")
def history(
    line_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"items": billing.usage_history(conn, ctx, line_id=line_id, limit=limit)}


@router.post("/billing/ecm/run")
def run(
    payload: BillingRunRequest,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Mide el consumo en el daemon y factura los bloques completos pendientes.

    ``dry_run`` calcula el importe sin tocar créditos ni contadores.
    """
    if ctx.role == ROLE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para facturar consumo")

    if payload.owner_id is not None and not ctx.is_super_admin and payload.owner_id != ctx.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo puede facturar sus cuentas")

    report = billing.run_billing(
        conn,
        ctx=None if payload.dry_run else ctx,
        dry_run=payload.dry_run,
        owner_id=payload.owner_id,
        line_id=payload.line_id,
    )
    if not payload.dry_run:
        audit(conn, ctx, "billing.ecm.run", "billing", None, {
            "credits": report["billed_credits"],
            "blocks": report["billed_blocks"],
        }, client_ip(request))
    return report


@router.post("/billing/ecm/refresh")
def refresh(
    owner_id: Optional[int] = Query(default=None),
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Solo mide (no factura): útil para comprobar la integración con el daemon."""
    return billing.refresh_usage(conn, owner_id=owner_id)
