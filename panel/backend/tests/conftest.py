"""Fixtures compartidas de las pruebas del panel NCam-NG."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# La configuración se evalúa al importar: se prepara el entorno de pruebas antes.
_TMP_DIR = tempfile.mkdtemp(prefix="ncam-panel-tests-")
os.environ["NCAM_PANEL_DB"] = str(Path(_TMP_DIR) / "panel-test.db")
os.environ["NCAM_PANEL_SECRET"] = "test-secret-key-for-unit-tests"
os.environ["NCAM_PANEL_CACHE_POLL"] = "0"
os.environ["NCAM_WEBIF_URL"] = "http://127.0.0.1:1"          # inalcanzable a propósito
os.environ["NCAM_PANEL_LINE_COST"] = "10"
os.environ["NCAM_PANEL_RENEW_COST"] = "5"
os.environ["NCAM_PANEL_PASSWORD_MIN"] = "8"

from fastapi.testclient import TestClient  # noqa: E402

from app import db as database  # noqa: E402
from app.main import app  # noqa: E402
from app.security import ROLE_RESELLER, ROLE_SUPER_ADMIN, hash_password  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session", autouse=True)
def _initial_data(client):
    """Crea un super admin y un reseller con saldo para todas las pruebas."""
    with database.session() as conn:
        now = database.utcnow()
        admin_id = database.insert(
            conn,
            "users",
            {
                "username": "superadmin",
                "password_hash": hash_password("SuperAdmin!2026"),
                "role": ROLE_SUPER_ADMIN,
                "credits": 0,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        database.insert(
            conn,
            "users",
            {
                "username": "revendedor",
                "password_hash": hash_password("Revendedor!2026"),
                "role": ROLE_RESELLER,
                "credits": 200,
                "max_lines": 5,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        database.insert(
            conn,
            "users",
            {
                "username": "cliente",
                "password_hash": hash_password("Cliente!2026"),
                "role": "user",
                "parent_id": None,
                "credits": 0,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        database.set_setting(conn, "billing.line_cost", "10")
        database.set_setting(conn, "billing.renew_cost", "5")
    return {"admin_id": admin_id}


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    return login(client, "superadmin", "SuperAdmin!2026")["access_token"]


@pytest.fixture(scope="session")
def reseller_token(client) -> str:
    return login(client, "revendedor", "Revendedor!2026")["access_token"]


@pytest.fixture(scope="session")
def client_token(client) -> str:
    return login(client, "cliente", "Cliente!2026")["access_token"]


@pytest.fixture()
def listening_port():
    """Puerto TCP abierto, para probar el chequeo de peers de caché."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        yield port
    finally:
        sock.close()
