"""Pruebas de autenticación, sesiones y control de acceso por roles."""

from __future__ import annotations

from .conftest import auth_headers, login


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    # el WebIf de NCam apunta a un puerto cerrado en las pruebas
    assert body["ncam_reachable"] is False


def test_login_ok_and_me(client, reseller_token):
    response = client.get("/api/v1/auth/me", headers=auth_headers(reseller_token))
    assert response.status_code == 200
    assert response.json()["username"] == "revendedor"
    assert response.json()["role"] == "reseller"


def test_login_wrong_password(client):
    response = client.post("/api/v1/auth/login", json={"username": "superadmin", "password": "nope"})
    assert response.status_code == 401


def test_login_unknown_user(client):
    response = client.post("/api/v1/auth/login", json={"username": "nadie", "password": "nope"})
    assert response.status_code == 401


def test_requests_without_token_are_rejected(client):
    assert client.get("/api/v1/lines").status_code == 401
    assert client.get("/api/v1/accounts").status_code == 401


def test_invalid_token_is_rejected(client):
    response = client.get("/api/v1/lines", headers=auth_headers("token.invalido.firma"))
    assert response.status_code == 401


def test_refresh_rotates_the_token(client):
    session = login(client, "cliente", "Cliente!2026")
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert first.status_code == 200
    new_refresh = first.json()["refresh_token"]
    assert new_refresh != session["refresh_token"]

    # el token antiguo queda revocado (rotación)
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert reused.status_code == 401

    # el nuevo sigue siendo válido
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 200


def test_access_token_is_not_accepted_as_refresh(client, admin_token):
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": admin_token})
    assert response.status_code == 401


def test_reseller_cannot_create_reseller(client, reseller_token):
    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(reseller_token),
        json={"username": "otro_revendedor", "password": "Secreta!2026", "role": "reseller"},
    )
    assert response.status_code == 403


def test_reseller_can_create_final_user(client, reseller_token):
    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(reseller_token),
        json={"username": "cliente_del_revendedor", "password": "Cliente!2026", "role": "user"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "user"
    assert response.json()["parent_id"] is not None


def test_nobody_can_create_super_admins(client, admin_token):
    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(admin_token),
        json={"username": "otro_admin", "password": "Secreta!2026", "role": "super_admin"},
    )
    assert response.status_code == 403


def test_final_user_is_read_only(client, client_token, admin_token):
    # no puede crear líneas
    response = client.post(
        "/api/v1/lines",
        headers=auth_headers(client_token),
        json={"name": "no permitido", "protocol": "cccam"},
    )
    assert response.status_code == 403

    # no puede crear cuentas
    response = client.post(
        "/api/v1/accounts",
        headers=auth_headers(client_token),
        json={"username": "intruso", "password": "Secreta!2026", "role": "user"},
    )
    assert response.status_code == 403

    # si es propietario sí puede listar sus líneas
    assert client.get("/api/v1/lines", headers=auth_headers(client_token)).status_code == 200
    assert admin_token  # el fixture se usa para garantizar datos previos


def test_only_super_admin_can_issue_credits(client, reseller_token, admin_token):
    accounts = client.get("/api/v1/accounts", headers=auth_headers(admin_token)).json()["items"]
    reseller = next(item for item in accounts if item["username"] == "revendedor")

    denied = client.post(
        f"/api/v1/accounts/{reseller['id']}/credits",
        headers=auth_headers(reseller_token),
        json={"amount": 1000},
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/v1/accounts/{reseller['id']}/credits",
        headers=auth_headers(admin_token),
        json={"amount": 1000, "description": "prueba"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["credits"] >= 1000


def test_resellers_do_not_see_each_other(client, admin_token, reseller_token):
    created = client.post(
        "/api/v1/accounts",
        headers=auth_headers(admin_token),
        json={"username": "revendedor_b", "password": "Revendedor!2026", "role": "reseller", "credits": 50},
    )
    assert created.status_code == 201
    other_id = created.json()["id"]

    visible = client.get("/api/v1/accounts", headers=auth_headers(reseller_token)).json()["items"]
    assert all(item["id"] != other_id for item in visible)

    forbidden = client.get(f"/api/v1/accounts/{other_id}", headers=auth_headers(reseller_token))
    assert forbidden.status_code == 403
