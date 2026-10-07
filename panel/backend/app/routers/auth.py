"""NCPanel :: rutas de autenticación y sesión."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import db as database
from ..config import settings
from ..models import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse
from ..security import (
    AuthContext,
    check_password_policy,
    client_ip,
    create_token,
    current_user,
    decode_token,
    get_db,
    hash_password,
    register_login_attempt,
    assert_not_locked,
    verify_password,
)
from ..services import audit, row_to_dict

router = APIRouter(prefix="/auth", tags=["auth"])


def _public_user(row: sqlite3.Row) -> dict:
    data = row_to_dict(row, skip=("password_hash", "api_key_hash")) or {}
    data["has_api_key"] = bool(row["api_key_prefix"])
    data["api_key_prefix"] = row["api_key_prefix"]
    return data


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    ip = client_ip(request)
    assert_not_locked(payload.username, ip)

    user = database.query_one(
        conn, "SELECT * FROM users WHERE username = ?", (payload.username.strip(),)
    )
    if not user or not verify_password(payload.password, str(user["password_hash"])):
        register_login_attempt(conn, payload.username, ip, False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos")
    if user["status"] != "active":
        register_login_attempt(conn, payload.username, ip, False)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta suspendida")

    register_login_attempt(conn, payload.username, ip, True)
    database.update(conn, "users", int(user["id"]), {"last_login_at": database.utcnow()})

    access = create_token(int(user["id"]), str(user["role"]), "access")
    refresh = create_token(int(user["id"]), str(user["role"]), "refresh")

    expires_at = datetime.now(timezone.utc).replace(microsecond=0)
    # el jti real se extrae del token para poder revocarlo
    refresh_payload = decode_token(refresh, expected_type="refresh")
    database.execute(
        conn,
        "INSERT INTO refresh_tokens (jti, user_id, expires_at, revoked, created_at) VALUES (?, ?, ?, 0, ?)",
        (
            refresh_payload["jti"],
            int(user["id"]),
            datetime.fromtimestamp(int(refresh_payload["exp"]), tz=timezone.utc).isoformat(),
            database.utcnow(),
        ),
    )
    audit(conn, None, "auth.login", "user", int(user["id"]), {"username": user["username"]}, ip)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl,
        user=_public_user(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshRequest, conn: sqlite3.Connection = Depends(get_db)):
    claims = decode_token(payload.refresh_token, expected_type="refresh")
    stored = database.query_one(
        conn, "SELECT * FROM refresh_tokens WHERE jti = ?", (claims["jti"],)
    )
    if not stored or int(stored["revoked"]) == 1:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revocado")

    user = database.query_one(conn, "SELECT * FROM users WHERE id = ?", (int(claims["sub"]),))
    if not user or user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cuenta no válida")

    # rotación: se revoca el token usado y se emite uno nuevo
    conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE jti = ?", (claims["jti"],))

    access = create_token(int(user["id"]), str(user["role"]), "access")
    new_refresh = create_token(int(user["id"]), str(user["role"]), "refresh")
    new_claims = decode_token(new_refresh, expected_type="refresh")
    database.execute(
        conn,
        "INSERT INTO refresh_tokens (jti, user_id, expires_at, revoked, created_at) VALUES (?, ?, ?, 0, ?)",
        (
            new_claims["jti"],
            int(user["id"]),
            datetime.fromtimestamp(int(new_claims["exp"]), tz=timezone.utc).isoformat(),
            database.utcnow(),
        ),
    )
    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=settings.access_token_ttl,
        user=_public_user(user),
    )


@router.post("/logout")
def logout(payload: RefreshRequest, ctx: AuthContext = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE jti = ?", (claims["jti"],))
    except HTTPException:
        pass  # un token inválido ya está "revocado"
    audit(conn, ctx, "auth.logout", "user", ctx.id, {})
    return {"detail": "Sesión cerrada"}


@router.get("/me")
def me(ctx: AuthContext = Depends(current_user)):
    return _public_user(ctx.user)


@router.post("/password")
def change_password(
    payload: ChangePasswordRequest,
    ctx: AuthContext = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    if not verify_password(payload.old_password, str(ctx.user["password_hash"])):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no coincide")
    check_password_policy(payload.new_password)
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La nueva contraseña debe ser distinta")

    database.update(
        conn,
        "users",
        ctx.id,
        {"password_hash": hash_password(payload.new_password), "updated_at": database.utcnow()},
    )
    # se invalidan todas las sesiones abiertas
    conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?", (ctx.id,))
    audit(conn, ctx, "auth.password_change", "user", ctx.id, {})
    return {"detail": "Contraseña actualizada. Vuelva a iniciar sesión."}
