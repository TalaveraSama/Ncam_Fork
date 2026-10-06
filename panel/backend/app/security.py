"""
NCPanel :: seguridad.

Incluye hash de contraseñas (PBKDF2-SHA256), emisión/validación de JWT HS256
implementada sobre la biblioteca estándar, claves de API para los resellers y
las dependencias de autorización por roles (RBAC) usadas por la API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from .config import settings
from . import db as database

PBKDF2_ITERATIONS = 260_000
PBKDF2_ALGORITHM = "sha256"

ROLE_SUPER_ADMIN = "super_admin"
ROLE_RESELLER = "reseller"
ROLE_USER = "user"
ALL_ROLES = (ROLE_SUPER_ADMIN, ROLE_RESELLER, ROLE_USER)


# ---------------------------------------------------------------------------
# contraseñas
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Genera ``pbkdf2_sha256$iteraciones$salt$hash`` para la contraseña dada."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_{}${}${}${}".format(
        PBKDF2_ALGORITHM,
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$")
        algorithm = algorithm.replace("pbkdf2_", "")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(algorithm, password.encode(), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def check_password_policy(password: str) -> None:
    """Valida la contraseña mínima exigida por el panel."""
    if len(password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La contraseña debe tener al menos {settings.password_min_length} caracteres",
        )


# ---------------------------------------------------------------------------
# claves de API (integración de los resellers con sus propios sistemas)
# ---------------------------------------------------------------------------
def generate_api_key() -> tuple[str, str, str]:
    """Devuelve (clave_en_claro, hash, prefijo)."""
    raw = "ng_" + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw), raw[:11]


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# JWT HS256 (stdlib)
# ---------------------------------------------------------------------------
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(
    subject: int | str,
    role: str,
    token_type: str = "access",
    ttl: Optional[int] = None,
    jti: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    now = int(time.time())
    if ttl is None:
        ttl = settings.access_token_ttl if token_type == "access" else settings.refresh_token_ttl
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "typ": token_type,
        "iat": now,
        "exp": now + int(ttl),
        "jti": jti or uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)

    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(settings.secret_key.encode(), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


def decode_token(token: str, expected_type: Optional[str] = None) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token malformado")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_signature = hmac.new(
        settings.secret_key.encode(), signing_input, hashlib.sha256
    ).digest()
    try:
        provided_signature = _b64url_decode(signature_b64)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token malformado")

    if not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma del token inválida")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token malformado")

    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expirado")
    if expected_type and payload.get("typ") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tipo de token incorrecto")
    return payload


# ---------------------------------------------------------------------------
# dependencias
# ---------------------------------------------------------------------------
def get_db() -> Iterator[sqlite3.Connection]:
    """Conexión con transacción abierta: commit al terminar, rollback si falla.

    Así las operaciones que tocan varias tablas (créditos + auditoría, por
    ejemplo) son atómicas.
    """
    conn = database.connect()
    conn.execute("BEGIN")
    try:
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


@dataclass
class AuthContext:
    user: sqlite3.Row
    method: str  # "jwt" | "api_key"

    @property
    def id(self) -> int:
        return int(self.user["id"])

    @property
    def role(self) -> str:
        return str(self.user["role"])

    @property
    def username(self) -> str:
        return str(self.user["username"])

    @property
    def is_super_admin(self) -> bool:
        return self.role == ROLE_SUPER_ADMIN

    @property
    def is_reseller(self) -> bool:
        return self.role == ROLE_RESELLER

    def owns(self, owner_id: Optional[int]) -> bool:
        """¿El usuario autenticado puede gestionar recursos de owner_id?"""
        if self.is_super_admin:
            return True
        return owner_id is not None and int(owner_id) == self.id


def _load_user(conn: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _reject_suspended(user: sqlite3.Row) -> None:
    if user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta suspendida")


def authenticate(
    conn: sqlite3.Connection,
    authorization: Optional[str] = None,
    api_key: Optional[str] = None,
) -> AuthContext:
    """Autentica por Bearer JWT o por cabecera X-API-Key."""
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_token(authorization.split(" ", 1)[1].strip(), expected_type="access")
        user = _load_user(conn, int(payload["sub"]))
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inexistente")
        _reject_suspended(user)
        if user["role"] != payload.get("role"):
            # el rol cambió después de emitir el token -> forzar re-login
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token obsoleto")
        return AuthContext(user=user, method="jwt")

    if api_key:
        key_hash = hash_api_key(api_key.strip())
        user = conn.execute(
            "SELECT * FROM users WHERE api_key_hash = ? AND api_key_hash IS NOT NULL", (key_hash,)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida")
        _reject_suspended(user)
        return AuthContext(user=user, method="api_key")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    conn: sqlite3.Connection = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> AuthContext:
    return authenticate(conn, authorization=authorization, api_key=x_api_key)


def require_super_admin(ctx: AuthContext = Depends(current_user)) -> AuthContext:
    if not ctx.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el super administrador puede realizar esta acción",
        )
    return ctx


def require_manager(ctx: AuthContext = Depends(current_user)) -> AuthContext:
    """super_admin o reseller (los usuarios finales son de solo lectura)."""
    if ctx.role not in (ROLE_SUPER_ADMIN, ROLE_RESELLER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador o revendedor",
        )
    return ctx


# ---------------------------------------------------------------------------
# antifuerza bruta sobre el login
# ---------------------------------------------------------------------------
_failed_attempts: dict[str, list[float]] = {}


def _throttle_key(username: str, ip: Optional[str]) -> str:
    return f"{username.lower()}|{ip or '-'}"


def register_login_attempt(conn: sqlite3.Connection, username: str, ip: Optional[str], success: bool) -> None:
    conn.execute(
        "INSERT INTO login_attempts (username, ip, success, created_at) VALUES (?, ?, ?, ?)",
        (username, ip, 1 if success else 0, database.utcnow()),
    )
    key = _throttle_key(username, ip)
    if success:
        _failed_attempts.pop(key, None)
    else:
        _failed_attempts.setdefault(key, []).append(time.time())


def assert_not_locked(username: str, ip: Optional[str]) -> None:
    key = _throttle_key(username, ip)
    window_start = time.time() - settings.login_lockout_seconds
    attempts = [ts for ts in _failed_attempts.get(key, []) if ts >= window_start]
    _failed_attempts[key] = attempts
    if len(attempts) >= settings.max_login_attempts:
        retry_in = int(settings.login_lockout_seconds - (time.time() - attempts[0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Reintente en {max(retry_in, 1)} segundos",
        )


def client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
