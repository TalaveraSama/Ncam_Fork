"""Pruebas de la autenticación del WebIf de NCam (Digest MD5, como el daemon real)."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import ncam

REALM = "Forbidden"
USER = "webifuser"
PASSWORD = "ClaveWebIf!2026"
OPAQUE = "0123456789abcdef0123456789abcdef"
NONCE = "abcdef0123456789abcdef0123456789"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class _DigestHandler(BaseHTTPRequestHandler):
    """Servidor mínimo que exige Digest MD5 igual que module-webif-lib.c."""

    failures = 0

    def log_message(self, *args):  # silencio
        pass

    def _challenge(self, stale: bool = False) -> None:
        header = (
            f'Digest algorithm="MD5", realm="{REALM}", qop="auth", '
            f'opaque="{OPAQUE}", nonce="{NONCE}"'
        )
        if stale:
            header += ", stale=true"
        self.send_response(401)
        self.send_header("WWW-Authenticate", header)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Digest "):
            type(self).failures += 1
            self._challenge()
            return

        fields = {}
        for part in authorization[len("Digest "):].split(","):
            if "=" in part:
                key, _, value = part.partition("=")
                fields[key.strip()] = value.strip().strip('"')

        ha1 = _md5(f"{fields.get('username')}:{fields.get('realm')}:{PASSWORD}")
        ha2 = _md5(f"GET:{fields.get('uri')}")
        expected = _md5(
            f"{ha1}:{fields.get('nonce')}:{fields.get('nc')}:{fields.get('cnonce')}:"
            f"{fields.get('qop')}:{ha2}"
        )
        if (
            fields.get("username") != USER
            or fields.get("realm") != REALM
            or fields.get("response") != expected
        ):
            type(self).failures += 1
            self._challenge()
            return

        body = json.dumps({"ncam": {"cachestats": {"engine": "digest-ok"}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def digest_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DigestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _DigestHandler.failures = 0
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_digest_auth_success(digest_server):
    payload = ncam._get_json(
        "/ncamapi.json",
        {"part": "cachestats"},
        credentials=(USER, PASSWORD),
        base_url=digest_server,
    )
    assert payload["ncam"]["cachestats"]["engine"] == "digest-ok"
    # solo el primer intento (Basic) fue rechazado; el Digest se aceptó
    assert _DigestHandler.failures == 1


def test_digest_auth_wrong_password(digest_server):
    with pytest.raises(ncam.NcamUnavailable) as excinfo:
        ncam._get_json(
            "/ncamapi.json",
            {"part": "cachestats"},
            credentials=(USER, "clave-incorrecta"),
            base_url=digest_server,
        )
    assert "credenciales" in str(excinfo.value)


def test_digest_auth_without_credentials(digest_server):
    with pytest.raises(ncam.NcamUnavailable) as excinfo:
        ncam._get_json("/ncamapi.json", {"part": "status"}, base_url=digest_server)
    assert "credenciales" in str(excinfo.value)


def test_challenge_parsing():
    challenge = ncam._parse_digest_challenge(
        'Digest algorithm="MD5", realm="Forbidden", qop="auth", '
        'opaque="abc", nonce="def"'
    )
    assert challenge == {
        "algorithm": "MD5",
        "realm": "Forbidden",
        "qop": "auth",
        "opaque": "abc",
        "nonce": "def",
    }
    assert ncam._parse_digest_challenge("Basic realm=\"x\"") == {}

    header = ncam._digest_authorization(USER, PASSWORD, "GET", "/ncamapi.json?part=status", challenge)
    assert header.startswith("Digest ")
    assert f'username="{USER}"' in header
    assert 'realm="Forbidden"' in header
    assert 'uri="/ncamapi.json?part=status"' in header
    assert "qop=auth" in header
    assert 'response="' in header
