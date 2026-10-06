"""NCPanel :: esquemas de entrada/salida de la API (Pydantic)."""

from __future__ import annotations

import re

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


def _check_email(value: Optional[str]) -> Optional[str]:
    """Validación ligera de emails, sin dependencias externas."""
    if value in (None, ""):
        return None
    value = value.strip()
    if not EMAIL_RE.match(value):
        raise ValueError("Email con formato inválido")
    return value


Role = Literal["super_admin", "reseller", "user"]
LineProtocol = Literal["cccam", "newcamd", "camd35", "cacheex"]
CacheProtocol = Literal["cccam", "camd35", "newcamd", "csp"]


# ---------------------------------------------------------------------------
# autenticación
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


# ---------------------------------------------------------------------------
# cuentas (super admin / reseller / usuario final)
# ---------------------------------------------------------------------------
class AccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=256)
    role: Role = "user"
    email: Optional[str] = Field(default=None, max_length=128)
    parent_id: Optional[int] = None
    credits: int = Field(default=0, ge=0, le=10_000_000)
    max_lines: int = Field(default=0, ge=0, le=1_000_000)
    notes: Optional[str] = Field(default=None, max_length=1000)


class AccountUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=256)
    email: Optional[str] = Field(default=None, max_length=128)
    credits: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    max_lines: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    status: Optional[Literal["active", "suspended"]] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class CreditRequest(BaseModel):
    amount: int = Field(gt=0, le=10_000_000)
    description: Optional[str] = Field(default=None, max_length=255)


class TransferRequest(BaseModel):
    target_id: int
    amount: int = Field(gt=0, le=10_000_000)
    description: Optional[str] = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# líneas
# ---------------------------------------------------------------------------
class LineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    protocol: LineProtocol = "cccam"
    username: Optional[str] = Field(default=None, max_length=64)
    password: Optional[str] = Field(default=None, min_length=4, max_length=64)
    group_name: str = Field(default="1", max_length=64)
    caid_allow: Optional[str] = Field(default=None, max_length=128)
    max_connections: int = Field(default=1, ge=1, le=64)
    days: int = Field(default=30, ge=1, le=3650)
    owner_id: Optional[int] = None
    cacheex_mode: int = Field(default=0, ge=0, le=3)
    cacheex_maxhop: int = Field(default=0, ge=0, le=10)
    cacheex_disable: int = Field(default=0, ge=0, le=1)
    notify_email: Optional[str] = Field(default=None, max_length=200)
    notify_telegram: Optional[str] = Field(default=None, max_length=64)
    notify_days: int = Field(default=0, ge=0, le=365)
    notes: Optional[str] = Field(default=None, max_length=1000)

    _email_format = field_validator("notify_email")(classmethod(lambda cls, value: _check_email(value)))

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise ValueError("El usuario solo admite letras, números, punto, guion y guion bajo")
        return value


class LineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    protocol: Optional[LineProtocol] = None
    group_name: Optional[str] = Field(default=None, max_length=64)
    caid_allow: Optional[str] = Field(default=None, max_length=128)
    max_connections: Optional[int] = Field(default=None, ge=1, le=64)
    status: Optional[Literal["active", "suspended"]] = None
    cacheex_mode: Optional[int] = Field(default=None, ge=0, le=3)
    cacheex_maxhop: Optional[int] = Field(default=None, ge=0, le=10)
    cacheex_disable: Optional[int] = Field(default=None, ge=0, le=1)
    notify_email: Optional[str] = Field(default=None, max_length=200)
    notify_telegram: Optional[str] = Field(default=None, max_length=64)
    notify_days: Optional[int] = Field(default=None, ge=0, le=365)
    notes: Optional[str] = Field(default=None, max_length=1000)

    _email_format = field_validator("notify_email")(classmethod(lambda cls, value: _check_email(value)))


class LineRenew(BaseModel):
    days: int = Field(default=30, ge=1, le=3650)


# ---------------------------------------------------------------------------
# peers de caché
# ---------------------------------------------------------------------------
class CacheServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    protocol: CacheProtocol = "cccam"
    username: Optional[str] = Field(default=None, max_length=64)
    password: Optional[str] = Field(default=None, max_length=128)
    node_id: Optional[str] = Field(default=None, max_length=32)
    priority: int = Field(default=0, ge=0, le=100)
    enabled: bool = True
    owner_id: Optional[int] = None


class CacheServerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    host: Optional[str] = Field(default=None, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    protocol: Optional[CacheProtocol] = None
    username: Optional[str] = Field(default=None, max_length=64)
    password: Optional[str] = Field(default=None, max_length=128)
    node_id: Optional[str] = Field(default=None, max_length=32)
    priority: Optional[int] = Field(default=None, ge=0, le=100)
    enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# ajustes
# ---------------------------------------------------------------------------
class SettingsUpdate(BaseModel):
    values: dict[str, str]

    @field_validator("values")
    @classmethod
    def _limit(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 64:
            raise ValueError("Demasiados ajustes en una sola petición")
        return value


# ---------------------------------------------------------------------------
# avisos de caducidad
# ---------------------------------------------------------------------------
class NotificationRunRequest(BaseModel):
    days: Optional[int] = Field(default=None, ge=1, le=365)
    dry_run: bool = False
    force: bool = False
    channels: Optional[list[Literal["email", "telegram"]]] = None

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, value):
        if value is not None and not value:
            raise ValueError("Indique al menos un canal")
        return value


class NotificationTestRequest(BaseModel):
    channel: Literal["email", "telegram"]
    target: Optional[str] = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# facturación por consumo de ECM
# ---------------------------------------------------------------------------
class BillingRunRequest(BaseModel):
    dry_run: bool = False
    owner_id: Optional[int] = Field(default=None, ge=1)
    line_id: Optional[int] = Field(default=None, ge=1)
