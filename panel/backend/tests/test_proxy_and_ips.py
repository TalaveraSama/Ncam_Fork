"""NCPanel :: IP real del cliente y proxies de confianza.

El panel puede estar detrás de un proxy (Cloudflare Tunnel, nginx, Caddy…). En ese
caso la conexión llega desde `127.0.0.1` y la IP del cliente viene en
`CF-Connecting-IP` / `X-Forwarded-For`. Estas pruebas comprueban dos cosas:

1. detrás de un proxy de confianza se usa la IP real del cliente;
2. en conexiones directas **se ignoran** esas cabeceras, para que nadie pueda
   falsear la auditoría ni esquivar el bloqueo por intentos fallidos de login.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.security import _normalize_ip, client_ip

from .conftest import auth_headers


class _Client:
    def __init__(self, host: str | None) -> None:
        self.host = host


class _Request:
    """Petición mínima con lo único que usa ``client_ip``."""

    def __init__(self, peer: str | None, headers: dict | None = None) -> None:
        self.client = _Client(peer) if peer else None
        self.headers = headers or {}


@pytest.fixture()
def trusted_proxies():
    """Permite cambiar la lista de proxies de confianza en una prueba."""
    original = settings.trusted_proxies
    yield lambda *values: object.__setattr__(settings, "trusted_proxies", tuple(values))
    object.__setattr__(settings, "trusted_proxies", original)


# ---------------------------------------------------------------------------
# normalización
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("191.103.121.243", "191.103.121.243"),
        ("  10.0.0.7  ", "10.0.0.7"),
        ("203.0.113.7:5555", "203.0.113.7"),
        ("[2001:db8::1]:8181", "2001:db8::1"),
        ("fe80::1%eth0", "fe80::1"),
        ("", None),
        (None, None),
        ("no es una ip", None),
        ("999.1.1.1", None),
        ("1.2.3.4.5", None),
        ("x" * 80, None),
    ],
)
def test_normalize_ip(entrada, esperado):
    assert _normalize_ip(entrada) == esperado


# ---------------------------------------------------------------------------
# conexión directa: las cabeceras no se creen
# ---------------------------------------------------------------------------
def test_direct_connection_ignores_forwarded_headers():
    peticion = _Request(
        "203.0.113.9",
        {
            "x-forwarded-for": "8.8.8.8",
            "cf-connecting-ip": "8.8.8.8",
            "x-real-ip": "8.8.8.8",
        },
    )
    assert client_ip(peticion) == "203.0.113.9"


def test_direct_connection_without_headers():
    assert client_ip(_Request("198.51.100.4")) == "198.51.100.4"


def test_missing_client_returns_none():
    assert client_ip(_Request(None, {"x-forwarded-for": "8.8.8.8"})) is None


# ---------------------------------------------------------------------------
# detrás de un proxy de confianza
# ---------------------------------------------------------------------------
def test_cloudflare_tunnel_uses_cf_connecting_ip(trusted_proxies):
    trusted_proxies("127.0.0.1", "::1")
    peticion = _Request(
        "127.0.0.1",
        {"cf-connecting-ip": "191.103.121.243", "x-forwarded-for": "10.0.0.1, 191.103.121.243"},
    )
    assert client_ip(peticion) == "191.103.121.243"


def test_forwarded_for_takes_the_last_entry(trusted_proxies):
    """La última entrada la añade el proxy de confianza; la primera la puede escribir el cliente."""
    trusted_proxies("127.0.0.1")
    peticion = _Request("127.0.0.1", {"x-forwarded-for": "1.2.3.4, 203.0.113.50"})
    assert client_ip(peticion) == "203.0.113.50"


def test_nginx_x_real_ip(trusted_proxies):
    trusted_proxies("127.0.0.1")
    assert client_ip(_Request("127.0.0.1", {"x-real-ip": "2001:db8::5"})) == "2001:db8::5"


def test_invalid_values_ignored(trusted_proxies):
    trusted_proxies("127.0.0.1")
    peticion = _Request("127.0.0.1", {"cf-connecting-ip": "basura", "x-forwarded-for": "tampoco"})
    assert client_ip(peticion) == "127.0.0.1"


def test_cidr_range_is_trusted(trusted_proxies):
    trusted_proxies("10.0.0.0/8")
    peticion = _Request("10.1.2.3", {"cf-connecting-ip": "203.0.113.77"})
    assert client_ip(peticion) == "203.0.113.77"


def test_untrusted_proxy_is_not_believed(trusted_proxies):
    trusted_proxies("127.0.0.1")
    peticion = _Request("192.0.2.10", {"cf-connecting-ip": "8.8.8.8"})
    assert client_ip(peticion) == "192.0.2.10"


# ---------------------------------------------------------------------------
# la auditoría tampoco se deja falsear
# ---------------------------------------------------------------------------
def test_audit_ignores_spoofed_header(client, admin_token):
    """Con una conexión directa (TestClient), la IP auditada es la del socket."""
    respuesta = client.post(
        "/api/v1/lines",
        headers={**auth_headers(admin_token), "X-Forwarded-For": "8.8.8.8", "CF-Connecting-IP": "8.8.8.8"},
        json={"name": "prueba de IP", "protocol": "cccam"},
    )
    assert respuesta.status_code == 201, respuesta.text
    auditoria = client.get("/api/v1/audit-logs?limit=5", headers=auth_headers(admin_token)).json()["items"]
    entrada = next(item for item in auditoria if item["action"] == "line.create.done")
    assert entrada["ip"] and "8.8.8.8" not in entrada["ip"]


def test_login_lockout_cannot_be_bypassed_with_forwarded_header(client):
    """Rotar la cabecera X-Forwarded-For no evita el bloqueo por intentos fallidos."""
    usuario = "objetivo_xff"
    codigos = []
    for intento in range(10):
        respuesta = client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": f"203.0.113.{intento}"},   # una IP distinta cada vez
            json={"username": usuario, "password": "clave-incorrecta"},
        )
        codigos.append(respuesta.status_code)
        if respuesta.status_code == 429:
            break
    assert 429 in codigos, codigos
    assert codigos.count(401) <= 8, codigos
