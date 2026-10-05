"""NCam-NG Panel :: líneas (cuentas que se exportan a NCam)."""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from .. import db as database
from .. import ncam
from ..models import LineCreate, LineRenew, LineUpdate
from ..security import AuthContext, client_ip, current_user, get_db
from ..services import (
    audit,
    create_line,
    delete_line,
    get_line,
    line_effective_status,
    list_lines,
    renew_line,
    reset_line_password,
    reveal_line_password,
    row_to_dict,
    update_line,
)

router = APIRouter(prefix="/lines", tags=["lines"])

SUPPORTED_EXPORTS = ("ncam", "cccam", "newcamd", "camd35", "json")


def _public(line: sqlite3.Row, include_secrets: bool = False) -> dict:
    data = row_to_dict(line) or {}
    data["effective_status"] = line_effective_status(line)
    if not include_secrets:
        data.pop("password", None)
    return data


@router.get("")
def lines_index(
    owner_id: Optional[int] = Query(default=None),
    protocol: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=64),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    return {"items": list_lines(conn, ctx, owner_id=owner_id, protocol=protocol, search=search)}


@router.post("", status_code=status.HTTP_201_CREATED)
def lines_create(
    payload: LineCreate,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    line = create_line(conn, ctx, payload.model_dump())
    audit(conn, ctx, "line.create.done", "line", int(line["id"]), {"name": line["name"]}, client_ip(request))
    return _public(line, include_secrets=True)


@router.get("/{line_id}")
def lines_show(line_id: int, ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return _public(get_line(conn, ctx, line_id))


@router.patch("/{line_id}")
def lines_update(
    line_id: int,
    payload: LineUpdate,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    line = update_line(conn, ctx, line_id, payload.model_dump(exclude_none=True))
    audit(conn, ctx, "line.update.done", "line", line_id, {}, client_ip(request))
    return _public(line)


@router.delete("/{line_id}")
def lines_delete(
    line_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    delete_line(conn, ctx, line_id)
    audit(conn, ctx, "line.delete.done", "line", line_id, {}, client_ip(request))
    return {"detail": "Línea eliminada"}


@router.post("/{line_id}/renew")
def lines_renew(
    line_id: int,
    payload: LineRenew,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    line = renew_line(conn, ctx, line_id, payload.days)
    audit(conn, ctx, "line.renew.done", "line", line_id, {"days": payload.days}, client_ip(request))
    return _public(line)


@router.post("/{line_id}/reset-password")
def lines_reset_password(
    line_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    line, new_password = reset_line_password(conn, ctx, line_id)
    audit(conn, ctx, "line.password_reset.done", "line", line_id, {}, client_ip(request))
    return {"line": _public(line), "password": new_password}


@router.get("/{line_id}/password")
def lines_reveal_password(
    line_id: int,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Muestra la contraseña (queda registrado en la auditoría)."""
    password = reveal_line_password(conn, ctx, line_id)
    audit(conn, ctx, "line.password_reveal.done", "line", line_id, {}, client_ip(request))
    return {"password": password}


@router.get("/{line_id}/export")
def lines_export(
    line_id: int,
    fmt: str = Query(default="ncam", alias="format"),
    download: bool = Query(default=False),
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Exporta la línea lista para pegar en el cliente o en ncam.user."""
    if fmt not in SUPPORTED_EXPORTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Formatos soportados: {', '.join(SUPPORTED_EXPORTS)}",
        )
    line = get_line(conn, ctx, line_id)
    content = ncam.export_line(line, fmt, conn=conn)
    audit(conn, ctx, "line.export", "line", line_id, {"format": fmt})

    media = "application/json" if fmt == "json" else "text/plain"
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{line["username"]}.{fmt}.txt"'
    return Response(content=content, media_type=media, headers=headers)
