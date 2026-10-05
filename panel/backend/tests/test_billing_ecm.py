"""Pruebas de la facturación por consumo de ECM."""

from __future__ import annotations

import pytest

from app import billing
from app import db as database
from app import ncam

from .conftest import auth_headers


def _fake_stats(counters: dict[str, int]) -> dict:
    """Respuesta simulada de ``part=userstats`` con los contadores indicados."""
    return {
        "reachable": True,
        "version": "Unofficial",
        "revision": "git-test",
        "users": {
            ncam.user_md5(username): {"status": "online", "ecm_ok": value, "expdate": "2026-12-31"}
            for username, value in counters.items()
        },
    }


@pytest.fixture()
def billing_line(client, reseller_token):
    """Línea del reseller con saldo, contadores a cero y limpieza al final."""
    with database.session() as conn:
        owner = database.query_one(conn, "SELECT * FROM users WHERE username = 'revendedor'")
        line_id = database.insert(
            conn,
            "lines",
            {
                "owner_id": owner["id"],
                "name": "Linea ECM",
                "protocol": "cccam",
                "username": "linea_ecm_test",
                "password": "secreto",
                "group_name": "1",
                "max_connections": 1,
                "expires_at": "2027-01-01T00:00:00+00:00",
                "status": "active",
                "created_at": database.utcnow(),
                "updated_at": database.utcnow(),
            },
        )
    yield line_id
    with database.session() as conn:
        database.execute(conn, "DELETE FROM ecm_usage WHERE line_id = ?", (line_id,))
        database.execute(conn, "DELETE FROM lines WHERE id = ?", (line_id,))


def _balance(username: str = "revendedor") -> int:
    with database.session() as conn:
        return int(database.query_one(conn, "SELECT credits FROM users WHERE username = ?", (username,))["credits"])


def _set_balance(credits: int, username: str = "revendedor") -> None:
    with database.session() as conn:
        database.execute(conn, "UPDATE users SET credits = ? WHERE username = ?", (credits, username))


def test_refresh_usage_measures_delta(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 2500}))
    with database.session() as conn:
        report = billing.refresh_usage(conn)

    assert report["reachable"] is True
    entry = next(item for item in report["measured"] if item["line_id"] == billing_line)
    assert entry["ecm_ok"] == 2500
    assert entry["ecm_delta"] == 2500

    with database.session() as conn:
        line = database.query_one(conn, "SELECT * FROM lines WHERE id = ?", (billing_line,))
    assert line["ecm_total"] == 2500

    # segunda medición: el delta solo cuenta lo nuevo
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 2600}))
    with database.session() as conn:
        second = billing.refresh_usage(conn)
    assert next(i for i in second["measured"] if i["line_id"] == billing_line)["ecm_delta"] == 100


def test_daemon_restart_does_not_invent_usage(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 5000}))
    with database.session() as conn:
        billing.refresh_usage(conn)

    # el daemon se reinicia: el contador vuelve a 10
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 10}))
    with database.session() as conn:
        report = billing.refresh_usage(conn)

    entry = next(i for i in report["measured"] if i["line_id"] == billing_line)
    assert entry["ecm_delta"] == 0
    with database.session() as conn:
        line = database.query_one(conn, "SELECT ecm_total, ecm_billed FROM lines WHERE id = ?", (billing_line,))
        note = database.query_one(
            conn, "SELECT note FROM ecm_usage WHERE line_id = ? ORDER BY id DESC LIMIT 1", (billing_line,)
        )
    assert line["ecm_total"] == 10
    assert note["note"] == "reinicio del daemon"


def test_bill_usage_charges_complete_blocks(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 2500}))
    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.block", "1000")
        database.set_setting(conn, "billing.ecm.price", "10")
    _set_balance(1000)

    with database.session() as conn:
        report = billing.run_billing(conn, owner_id=None)

    entry = next(item for item in report["lines"] if item["line_id"] == billing_line)
    assert entry["blocks"] == 2
    assert entry["credits"] == 20
    assert entry["pending_ecm"] == 500  # el bloque incompleto no se cobra
    assert _balance() == 980

    # el contador facturado avanza solo lo cobrado
    with database.session() as conn:
        line = database.query_one(conn, "SELECT * FROM lines WHERE id = ?", (billing_line,))
        tx = database.query_one(
            conn,
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (line["owner_id"],),
        )
    assert line["ecm_billed"] == 2000
    assert tx["amount"] == -20
    assert "ECM" in tx["description"]

    # una segunda pasada no vuelve a cobrar lo mismo
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 2500}))
    with database.session() as conn:
        again = billing.run_billing(conn)
    assert [i for i in again["lines"] if i["line_id"] == billing_line] == []
    assert _balance() == 980


def test_insufficient_balance_leaves_blocks_pending(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 3000}))
    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.block", "1000")
        database.set_setting(conn, "billing.ecm.price", "50")
    _set_balance(60)  # solo alcanza para 1 bloque

    with database.session() as conn:
        report = billing.run_billing(conn)

    entry = next(item for item in report["lines"] if item["line_id"] == billing_line)
    assert entry["blocks"] == 1
    assert entry["pending_blocks"] == 2
    assert _balance() == 10
    assert any(item["line_id"] == billing_line and "saldo" in item["reason"] for item in report["skipped"])

    with database.session() as conn:
        line = database.query_one(conn, "SELECT * FROM lines WHERE id = ?", (billing_line,))
    assert line["ecm_billed"] == 1000  # nunca se factura por adelantado


def test_suspend_on_debt(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 5000}))
    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.block", "1000")
        database.set_setting(conn, "billing.ecm.price", "100")
        database.set_setting(conn, "billing.ecm.suspend_on_debt", "1")
    _set_balance(50)

    with database.session() as conn:
        billing.run_billing(conn)

    with database.session() as conn:
        line = database.query_one(conn, "SELECT status FROM lines WHERE id = ?", (billing_line,))
    assert line["status"] == "suspended"

    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.suspend_on_debt", "0")
        database.execute(conn, "UPDATE lines SET status = 'active' WHERE id = ?", (billing_line,))


def test_dry_run_does_not_touch_credits(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 4000}))
    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.block", "1000")
        database.set_setting(conn, "billing.ecm.price", "5")
    _set_balance(500)
    before = _balance()

    response = client.post(
        "/api/v1/billing/ecm/run", json={"dry_run": True}, headers=auth_headers(admin_token)
    )
    assert response.status_code == 200, response.text
    report = response.json()
    entry = next(item for item in report["lines"] if item["line_id"] == billing_line)
    assert entry["blocks"] == 4
    assert entry["credits"] == 20
    assert report["billed_credits"] == 0
    assert _balance() == before

    with database.session() as conn:
        line = database.query_one(conn, "SELECT * FROM lines WHERE id = ?", (billing_line,))
    assert line["ecm_billed"] == 0

    # el super admin nunca se factura a sí mismo
    with database.session() as conn:
        admin = database.query_one(conn, "SELECT id FROM users WHERE username = 'superadmin'")
        database.execute(conn, "UPDATE lines SET owner_id = ? WHERE id = ?", (admin["id"], billing_line))
    try:
        response = client.post("/api/v1/billing/ecm/run", json={}, headers=auth_headers(admin_token))
        reasons = [item["reason"] for item in response.json()["skipped"]]
        assert any("super admin" in reason for reason in reasons)
    finally:
        with database.session() as conn:
            owner = database.query_one(conn, "SELECT id FROM users WHERE username = 'revendedor'")
            database.execute(conn, "UPDATE lines SET owner_id = ? WHERE id = ?", (owner["id"], billing_line))


def test_usage_endpoint_and_history(client, admin_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 1500}))
    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.block", "1000")
        database.set_setting(conn, "billing.ecm.price", "10")
    _set_balance(1000)

    client.post("/api/v1/billing/ecm/run", json={}, headers=auth_headers(admin_token))

    response = client.get("/api/v1/billing/ecm", headers=auth_headers(admin_token))
    assert response.status_code == 200
    item = next(i for i in response.json()["items"] if i["line_id"] == billing_line)
    assert item["ecm_total"] == 1500
    assert item["ecm_billed"] == 1000
    assert item["ecm_pending"] == 500
    assert item["blocks_pending"] == 0

    history = client.get(
        f"/api/v1/billing/ecm/history?line_id={billing_line}", headers=auth_headers(admin_token)
    )
    assert history.status_code == 200
    rows = history.json()["items"]
    assert rows
    assert rows[0]["line_name"] == "Linea ECM"
    assert rows[0]["blocks"] == 1
    assert rows[0]["credits"] == 10


def test_reseller_scope_and_permissions(client, reseller_token, client_token, billing_line):
    # un usuario final no puede facturar
    response = client.post("/api/v1/billing/ecm/run", json={}, headers=auth_headers(client_token))
    assert response.status_code == 403

    # un reseller solo ve y factura lo suyo
    response = client.get("/api/v1/billing/ecm", headers=auth_headers(reseller_token))
    assert response.status_code == 200
    owners = {item["owner"] for item in response.json()["items"]}
    assert owners <= {"revendedor", "cliente"}

    with database.session() as conn:
        admin = database.query_one(conn, "SELECT id FROM users WHERE username = 'superadmin'")
    response = client.post(
        "/api/v1/billing/ecm/run", json={"owner_id": int(admin["id"])}, headers=auth_headers(reseller_token)
    )
    assert response.status_code == 403


def test_history_is_scoped_for_reseller(client, reseller_token, billing_line, monkeypatch):
    monkeypatch.setattr(billing.ncam, "fetch_user_stats", lambda conn=None: _fake_stats({"linea_ecm_test": 2000}))
    with database.session() as conn:
        database.set_setting(conn, "billing.ecm.block", "1000")
    with database.session() as conn:
        billing.refresh_usage(conn)

    response = client.get("/api/v1/billing/ecm/history?limit=50", headers=auth_headers(reseller_token))
    assert response.status_code == 200
    assert all(item["owner_username"] in ("revendedor", "cliente") for item in response.json()["items"])


def test_settings_are_editable(client, admin_token):
    response = client.patch(
        "/api/v1/settings",
        json={"values": {"billing.ecm.enabled": "1", "billing.ecm.price": "25", "billing.ecm.block": "500"}},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["rejected"] == []

    with database.session() as conn:
        conf = billing.billing_settings(conn)
    assert conf["enabled"] is True
    assert conf["price"] == 25
    assert conf["block"] == 500
