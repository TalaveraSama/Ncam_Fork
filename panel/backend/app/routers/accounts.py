"""NCam-NG Panel :: cuentas (super admin gestiona resellers, reseller sus usuarios)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .. import db as database
from ..models import AccountCreate, AccountUpdate, CreditRequest, TransferRequest
from ..security import AuthContext, client_ip, current_user, get_db, require_super_admin
from ..services import (
    apply_credits,
    audit,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    rotate_api_key,
    row_to_dict,
    transfer_credits,
    update_account,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _public(row: sqlite3.Row) -> dict:
    data = row_to_dict(row, skip=("password_hash", "api_key_hash")) or {}
    data["has_api_key"] = bool(row["api_key_prefix"])
    return data


@router.get("")
def accounts_index(
    search: Optional[str] = Query(default=None, max_length=64),
    role: Optional[str] = Query(default=None),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"items": list_accounts(conn, ctx, search=search, role=role)}


@router.get("/me")
def accounts_me(ctx: AuthContext = Depends(current_user)):
    return _public(ctx.user)


@router.post("", status_code=status.HTTP_201_CREATED)
def accounts_create(
    payload: AccountCreate,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    user = create_account(conn, ctx, payload.model_dump())
    audit(conn, ctx, "account.create.done", "user", int(user["id"]), {"username": user["username"]}, client_ip(request))
    return _public(user)


@router.get("/transactions")
def accounts_transactions(
    limit: int = Query(default=100, ge=1, le=500),
    user_id: Optional[int] = Query(default=None),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Movimientos de créditos visibles para el usuario autenticado."""
    sql = (
        "SELECT t.*, u.username AS user_username, a.username AS actor_username"
        " FROM transactions t"
        " JOIN users u ON u.id = t.user_id"
        " LEFT JOIN users a ON a.id = t.actor_id"
    )
    params: list = []
    if not ctx.is_super_admin:
        sql += " WHERE t.user_id = ? OR t.user_id IN (SELECT id FROM users WHERE parent_id = ?)"
        params.extend([ctx.id, ctx.id])
    else:
        sql += " WHERE 1 = 1"
    if user_id:
        sql += " AND t.user_id = ?"
        params.append(user_id)
    sql += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(limit)

    rows = database.query(conn, sql, params)
    return {"items": [row_to_dict(row) for row in rows]}


@router.get("/{account_id}")
def accounts_show(
    account_id: int, ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
):
    return _public(get_account(conn, ctx, account_id))


@router.patch("/{account_id}")
def accounts_update(
    account_id: int,
    payload: AccountUpdate,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    user = update_account(conn, ctx, account_id, payload.model_dump(exclude_none=True))
    audit(conn, ctx, "account.update.done", "user", account_id, {}, client_ip(request))
    return _public(user)


@router.delete("/{account_id}")
def accounts_delete(
    account_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    delete_account(conn, ctx, account_id)
    audit(conn, ctx, "account.delete.done", "user", account_id, {}, client_ip(request))
    return {"detail": "Cuenta eliminada"}


@router.post("/{account_id}/credits")
def accounts_add_credits(
    account_id: int,
    payload: CreditRequest,
    request: Request,
    ctx: AuthContext = Depends(require_super_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Emisión de créditos: exclusivo del super administrador."""
    user = get_account(conn, ctx, account_id)
    balance = apply_credits(
        conn,
        account_id,
        payload.amount,
        "topup",
        payload.description or f"Recarga autorizada por {ctx.username}",
        ctx,
    )
    audit(conn, ctx, "credits.topup", "user", account_id, {"amount": payload.amount}, client_ip(request))
    return {"user": user["username"], "credits": balance}


@router.post("/{account_id}/transfer")
def accounts_transfer(
    account_id: int,
    payload: TransferRequest,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """El reseller pasa créditos a uno de sus usuarios (el super admin, a cualquiera)."""
    if not (ctx.is_super_admin or ctx.is_reseller):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para transferir créditos"
        )

    source_id = account_id if ctx.is_super_admin else ctx.id
    result = transfer_credits(conn, ctx, payload.target_id, payload.amount, payload.description)
    audit(
        conn,
        ctx,
        "credits.transfer.done",
        "user",
        payload.target_id,
        {"from": source_id, "amount": payload.amount},
        client_ip(request),
    )
    return result


@router.post("/{account_id}/api-key")
def accounts_api_key(
    account_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Genera/rota la API key de una cuenta. Solo se muestra una vez."""
    raw, prefix = rotate_api_key(conn, ctx, account_id)
    audit(conn, ctx, "account.api_key.rotate", "user", account_id, {"prefix": prefix}, client_ip(request))
    return {
        "api_key": raw,
        "prefix": prefix,
        "warning": "Guarde esta clave: no se volverá a mostrar",
    }
