"""Pruebas del control del daemon (aplicar peers/líneas/ajustes, reiniciar).

El panel habla contra el simulador del WebIf (``panel/tools/mock_ncam_webif.py``)
levantado en la propia máquina: imita los marcadores del daemon de verdad
(``User Account updated and saved``, ...) y guarda lo recibido para poder
afirmarlo.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import mock_ncam_webif as mock  # noqa: E402

from .conftest import auth_headers  # noqa: E402


@pytest.fixture(scope="module")
def webif():
    server = mock.start_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def live_daemon(client, admin_token, webif):
    """Apunta el panel al simulador durante la prueba y restaura después."""
    before = client.get("/api/v1/settings", headers=auth_headers(admin_token)).json()["items"][
        "panel.ncam_webif_url"
    ]
    client.patch(
        "/api/v1/settings",
        headers=auth_headers(admin_token),
        json={"values": {"panel.ncam_webif_url": webif}},
    )
    yield webif
    client.patch(
        "/api/v1/settings",
        headers=auth_headers(admin_token),
        json={"values": {"panel.ncam_webif_url": before}},
    )


@pytest.fixture(autouse=True)
def _clean_mock_state():
    mock.STATE.readers.clear()
    mock.STATE.applied_users.clear()
    mock.STATE.cache_section.clear()
    mock.STATE.restarts = 0
    yield


def _make_peer(client, token, **overrides):
    payload = {
        "name": "Peer aplicado",
        "host": "192.168.1.60",
        "port": 12000,
        "protocol": "cccam",
        "username": "peeruser",
        "password": "peerpass",
        "priority": 9,
    }
    payload.update(overrides)
    created = client.post("/api/v1/cache/servers", headers=auth_headers(token), json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _make_line(client, token, **overrides):
    payload = {"name": "Línea aplicada", "protocol": "cccam", "days": 30}
    payload.update(overrides)
    created = client.post("/api/v1/lines", headers=auth_headers(token), json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def test_apply_new_peer_creates_reader(client, admin_token, live_daemon):
    server = _make_peer(client, admin_token)
    response = client.post(f"/api/v1/cache/servers/{server['id']}/apply", headers=auth_headers(admin_token))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["created"] is True
    assert data["label"] == "Peer_aplicado"

    applied = mock.STATE.readers["Peer_aplicado"]
    assert applied["protocol"] == "cccam"
    assert applied["device"] == "192.168.1.60,12000"
    assert applied["user"] == "peeruser"
    assert applied["password"] == "peerpass"
    assert applied["cacheex"] == "3"  # claves reales del daemon, no cachex*
    assert applied["cacheex_maxhop"] == "2"
    assert applied["enable"] == "1"

    row = client.get(f"/api/v1/cache/servers/{server['id']}", headers=auth_headers(admin_token)).json()
    assert row["last_apply_ok"] == 1
    assert row["last_apply_at"] is not None


def test_apply_existing_peer_updates_reader(client, admin_token, live_daemon):
    server = _make_peer(client, admin_token, name="Peer viejo")
    mock.STATE.readers["Peer_viejo"] = {"label": "Peer_viejo"}
    response = client.post(f"/api/v1/cache/servers/{server['id']}/apply", headers=auth_headers(admin_token))
    assert response.json()["ok"] is True
    assert response.json()["created"] is False
    assert mock.STATE.readers["Peer_viejo"]["device"] == "192.168.1.60,12000"


def test_apply_peer_reseller_forbidden(client, admin_token, reseller_token, live_daemon):
    server = _make_peer(client, reseller_token, name="Peer ajeno")
    response = client.post(f"/api/v1/cache/servers/{server['id']}/apply", headers=auth_headers(reseller_token))
    assert response.status_code == 403


def test_apply_peer_unreachable_daemon_is_not_500(client, admin_token):
    # sin live_daemon: la URL apunta a un puerto cerrado, como en el resto de la suite
    server = _make_peer(client, admin_token, name="Peer sin daemon")
    response = client.post(f"/api/v1/cache/servers/{server['id']}/apply", headers=auth_headers(admin_token))
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "message" in response.json()
    row = client.get(f"/api/v1/cache/servers/{server['id']}", headers=auth_headers(admin_token)).json()
    assert row["last_apply_ok"] == 0


def test_apply_line_creates_account(client, admin_token, reseller_token, live_daemon):
    line = _make_line(client, reseller_token)
    response = client.post(f"/api/v1/lines/{line['id']}/apply", headers=auth_headers(admin_token))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["created"] is True

    applied = mock.STATE.applied_users[line["username"]]
    assert applied["pwd"] == line["password"]
    assert applied["disabled"] == "0"
    assert applied["group"] == "1"
    assert applied["expdate"]  # YYYY-MM-DD a partir de expires_at

    row = client.get(f"/api/v1/lines/{line['id']}", headers=auth_headers(admin_token)).json()
    assert row["last_apply_ok"] == 1


def test_apply_suspended_line_disables_account(client, admin_token, reseller_token, live_daemon):
    line = _make_line(client, reseller_token)
    patched = client.patch(
        f"/api/v1/lines/{line['id']}", headers=auth_headers(admin_token), json={"status": "suspended"}
    )
    assert patched.status_code == 200
    response = client.post(f"/api/v1/lines/{line['id']}/apply", headers=auth_headers(admin_token))
    assert response.json()["ok"] is True
    assert mock.STATE.applied_users[line["username"]]["disabled"] == "1"


def test_apply_line_reseller_forbidden(client, reseller_token, live_daemon):
    line = _make_line(client, reseller_token)
    response = client.post(f"/api/v1/lines/{line['id']}/apply", headers=auth_headers(reseller_token))
    assert response.status_code == 403


def test_apply_cache_settings(client, admin_token, live_daemon):
    client.patch(
        "/api/v1/settings",
        headers=auth_headers(admin_token),
        json={"values": {"ncam.cache.max_time": "22", "ncam.cache.max_entries": "7000"}},
    )
    response = client.post("/api/v1/cache/settings/apply", headers=auth_headers(admin_token))
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert mock.STATE.cache_section == {"max_time": "22", "max_entries": "7000", "cacheexenablestats": "1"}


def test_restart_daemon(client, admin_token, reseller_token, live_daemon):
    denied = client.post("/api/v1/daemon/restart", headers=auth_headers(reseller_token))
    assert denied.status_code == 403
    response = client.post("/api/v1/daemon/restart", headers=auth_headers(admin_token))
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert mock.STATE.restarts == 1


def test_daemon_status(client, admin_token, reseller_token, live_daemon):
    status = client.get("/api/v1/daemon/status", headers=auth_headers(reseller_token)).json()
    assert status["reachable"] is True
    assert status["version"]
    status = client.get("/api/v1/daemon/status", headers=auth_headers(admin_token)).json()
    assert status["reachable"] is True


def test_account_render_drops_dead_keys(client, admin_token, reseller_token):
    line = _make_line(client, reseller_token, cacheex_disable=1)
    block = client.get(
        f"/api/v1/lines/{line['id']}/export?format=ncam", headers=auth_headers(admin_token)
    ).text
    assert "cacheex_disable" not in block  # no existe como clave del daemon
