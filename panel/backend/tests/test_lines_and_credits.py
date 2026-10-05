"""Pruebas de líneas (altas, renovaciones, exportación) y del libro de créditos."""

from __future__ import annotations

from datetime import datetime, timezone

from .conftest import auth_headers


def _balance(client, token) -> int:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["credits"]


def test_line_lifecycle_and_credit_charge(client, reseller_token):
    balance_before = _balance(client, reseller_token)

    created = client.post(
        "/api/v1/lines",
        headers=auth_headers(reseller_token),
        json={"name": "Línea de prueba", "protocol": "cccam", "days": 30, "max_connections": 2},
    )
    assert created.status_code == 201, created.text
    line = created.json()
    assert line["username"]
    assert line["password"]            # el creador recibe las credenciales
    assert line["effective_status"] == "active"

    # la creación descuenta créditos (billing.line_cost = 10)
    assert _balance(client, reseller_token) == balance_before - 10

    # el listado no expone la contraseña
    listed = client.get("/api/v1/lines", headers=auth_headers(reseller_token)).json()["items"]
    entry = next(item for item in listed if item["id"] == line["id"])
    assert entry["password"] is None

    # la contraseña se puede consultar de forma explícita (queda auditado)
    revealed = client.get(f"/api/v1/lines/{line['id']}/password", headers=auth_headers(reseller_token))
    assert revealed.status_code == 200
    assert revealed.json()["password"] == line["password"]

    # renovación: extiende la fecha y cobra billing.renew_cost (5)
    balance_before_renew = _balance(client, reseller_token)
    renewed = client.post(
        f"/api/v1/lines/{line['id']}/renew", headers=auth_headers(reseller_token), json={"days": 30}
    )
    assert renewed.status_code == 200
    old_expiry = datetime.fromisoformat(line["expires_at"])
    new_expiry = datetime.fromisoformat(renewed.json()["expires_at"])
    assert (new_expiry - old_expiry).days == 30
    assert _balance(client, reseller_token) == balance_before_renew - 5

    # actualización
    updated = client.patch(
        f"/api/v1/lines/{line['id']}",
        headers=auth_headers(reseller_token),
        json={"cacheex_mode": 2, "cacheex_maxhop": 3, "max_connections": 4},
    )
    assert updated.status_code == 200
    assert updated.json()["cacheex_mode"] == 2
    assert updated.json()["cacheex_maxhop"] == 3

    # reset de contraseña
    reset = client.post(f"/api/v1/lines/{line['id']}/reset-password", headers=auth_headers(reseller_token))
    assert reset.status_code == 200
    assert reset.json()["password"] != line["password"]

    # borrado
    assert client.delete(f"/api/v1/lines/{line['id']}", headers=auth_headers(reseller_token)).status_code == 200
    assert client.get(f"/api/v1/lines/{line['id']}", headers=auth_headers(reseller_token)).status_code == 404


def test_export_formats(client, reseller_token):
    created = client.post(
        "/api/v1/lines",
        headers=auth_headers(reseller_token),
        json={"name": "Export test", "protocol": "cccam", "days": 10},
    ).json()

    ncam_block = client.get(f"/api/v1/lines/{created['id']}/export?format=ncam", headers=auth_headers(reseller_token))
    assert ncam_block.status_code == 200
    assert "[account]" in ncam_block.text
    assert created["username"] in ncam_block.text

    cccam = client.get(f"/api/v1/lines/{created['id']}/export?format=cccam", headers=auth_headers(reseller_token))
    assert cccam.text.startswith("C: ")

    json_export = client.get(f"/api/v1/lines/{created['id']}/export?format=json", headers=auth_headers(reseller_token))
    assert json_export.json()["username"] == created["username"]

    bad = client.get(f"/api/v1/lines/{created['id']}/export?format=rtsp", headers=auth_headers(reseller_token))
    assert bad.status_code == 422

    client.delete(f"/api/v1/lines/{created['id']}", headers=auth_headers(reseller_token))


def test_insufficient_credits_block_line_creation(client, admin_token, reseller_token):
    """Sin saldo, crear una línea debe fallar con 400 y no dejar rastro."""
    accounts = client.get("/api/v1/accounts", headers=auth_headers(admin_token)).json()["items"]
    reseller = next(item for item in accounts if item["username"] == "revendedor")

    # el reseller deja su cuenta a cero pasando el saldo a su usuario
    user = client.post(
        "/api/v1/accounts",
        headers=auth_headers(reseller_token),
        json={"username": "caja_fuerte", "password": "CajaFuerte!2026", "role": "user", "credits": 0},
    ).json()
    balance = _balance(client, reseller_token)
    if balance > 0:
        moved = client.post(
            f"/api/v1/accounts/{reseller['id']}/transfer",
            headers=auth_headers(reseller_token),
            json={"target_id": user["id"], "amount": balance},
        )
        assert moved.status_code == 200, moved.text
    assert _balance(client, reseller_token) == 0

    lines_before = len(client.get("/api/v1/lines", headers=auth_headers(reseller_token)).json()["items"])
    blocked = client.post(
        "/api/v1/lines",
        headers=auth_headers(reseller_token),
        json={"name": "Sin saldo", "protocol": "cccam", "days": 30},
    )
    assert blocked.status_code == 400
    assert "insuficientes" in blocked.json()["detail"].lower()

    # la transacción fallida no creó la línea
    lines_after = len(client.get("/api/v1/lines", headers=auth_headers(reseller_token)).json()["items"])
    assert lines_after == lines_before

    # el super admin le devuelve el saldo para no romper el resto de pruebas
    client.post(
        f"/api/v1/accounts/{reseller['id']}/credits",
        headers=auth_headers(admin_token),
        json={"amount": 500, "description": "reposición para pruebas"},
    )


def test_credit_ledger_and_transfer(client, admin_token, reseller_token):
    accounts = client.get("/api/v1/accounts", headers=auth_headers(admin_token)).json()["items"]
    reseller = next(item for item in accounts if item["username"] == "revendedor")
    target = next(item for item in accounts if item["username"] == "cliente_del_revendedor")

    # el super admin recarga al reseller
    before = _balance(client, reseller_token)
    topup = client.post(
        f"/api/v1/accounts/{reseller['id']}/credits",
        headers=auth_headers(admin_token),
        json={"amount": 100, "description": "recarga de prueba"},
    )
    assert topup.json()["credits"] == before + 100

    # el reseller transfiere a su usuario final
    transfer = client.post(
        f"/api/v1/accounts/{reseller['id']}/transfer",
        headers=auth_headers(reseller_token),
        json={"target_id": target["id"], "amount": 25, "description": "saldo para el cliente"},
    )
    assert transfer.status_code == 200, transfer.text
    assert transfer.json()["source_balance"] == before + 75
    assert transfer.json()["target_balance"] >= 25

    # el libro mayor registra ambos movimientos con su saldo resultante
    ledger = client.get("/api/v1/accounts/transactions?limit=200", headers=auth_headers(reseller_token)).json()["items"]
    kinds = {item["kind"] for item in ledger}
    assert "topup" in kinds and "debit" in kinds
    assert all("balance_after" in item for item in ledger)


def test_transfer_to_foreign_user_is_forbidden(client, admin_token, reseller_token):
    other = client.post(
        "/api/v1/accounts",
        headers=auth_headers(admin_token),
        json={"username": "ajeno", "password": "Ajeno!2026", "role": "user", "credits": 0},
    ).json()
    accounts = client.get("/api/v1/accounts", headers=auth_headers(admin_token)).json()["items"]
    reseller = next(item for item in accounts if item["username"] == "revendedor")

    response = client.post(
        f"/api/v1/accounts/{reseller['id']}/transfer",
        headers=auth_headers(reseller_token),
        json={"target_id": other["id"], "amount": 5},
    )
    assert response.status_code == 403


def test_expiring_endpoint(client, reseller_token):
    created = client.post(
        "/api/v1/lines",
        headers=auth_headers(reseller_token),
        json={"name": "Caduca pronto", "protocol": "newcamd", "days": 1},
    ).json()

    items = client.get("/api/v1/stats/expiring?days=3", headers=auth_headers(reseller_token)).json()["items"]
    assert any(item["id"] == created["id"] for item in items)

    client.delete(f"/api/v1/lines/{created['id']}", headers=auth_headers(reseller_token))


def test_overview_counts(client, admin_token):
    data = client.get("/api/v1/stats/overview", headers=auth_headers(admin_token)).json()
    assert data["lines"]["total"] >= 0
    assert "resellers" in data["accounts"]
    assert data["cache_servers"]["total"] >= 0
    assert data["ncam"]["reachable"] is False  # sin daemon en las pruebas


def test_timeseries_is_empty_without_daemon(client, admin_token):
    data = client.get("/api/v1/stats/timeseries?metric=cache.hit_ratio&hours=1", headers=auth_headers(admin_token)).json()
    assert data["metric"] == "cache.hit_ratio"
    assert isinstance(data["items"], list)


def test_account_update_requires_super_admin_for_credits(client, reseller_token, admin_token):
    accounts = client.get("/api/v1/accounts", headers=auth_headers(admin_token)).json()["items"]
    user = next(item for item in accounts if item["username"] == "cliente_del_revendedor")

    # el reseller intenta fijar créditos directamente -> se ignora
    client.patch(
        f"/api/v1/accounts/{user['id']}",
        headers=auth_headers(reseller_token),
        json={"credits": 99999},
    )
    after = client.get(f"/api/v1/accounts/{user['id']}", headers=auth_headers(reseller_token)).json()
    assert after["credits"] < 99999


def test_password_policy(client, admin_token):
    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(admin_token),
        json={"username": "corta", "password": "1234", "role": "user"},
    )
    assert response.status_code == 422
