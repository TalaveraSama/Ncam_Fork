"""Pruebas del subsistema de caché, ajustes, auditoría y API keys."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from app import ncam as ncam_module

from .conftest import auth_headers


def test_cache_stats_reports_daemon_unreachable(client, admin_token):
    data = client.get("/api/v1/cache/stats", headers=auth_headers(admin_token)).json()
    assert data["reachable"] is False
    assert "error" in data
    assert data["peers"]["total"] >= 0


def test_cache_limits_reflect_settings(client, admin_token):
    client.patch(
        "/api/v1/settings",
        headers=auth_headers(admin_token),
        json={"values": {"ncam.cache.max_time": "20", "ncam.cache.max_entries": "5000"}},
    )
    limits = client.get("/api/v1/cache/limits", headers=auth_headers(admin_token)).json()
    assert limits["max_time"] == 20
    assert limits["max_entries"] == 5000


def test_cache_server_crud_and_tcp_probe(client, reseller_token, listening_port):
    created = client.post(
        "/api/v1/cache/servers",
        headers=auth_headers(reseller_token),
        json={
            "name": "Peer de prueba",
            "host": "127.0.0.1",
            "port": listening_port,
            "protocol": "cccam",
            "priority": 7,
        },
    )
    assert created.status_code == 201, created.text
    server = created.json()
    assert server["name"] == "Peer de prueba"
    assert "password" not in server

    # la prueba TCP contra un puerto abierto debe funcionar
    probe = client.post(f"/api/v1/cache/servers/{server['id']}/test", headers=auth_headers(reseller_token))
    assert probe.status_code == 200
    assert probe.json()["ok"] is True
    assert probe.json()["latency_ms"] is not None

    # y contra un puerto cerrado debe informar el fallo
    closed = client.post(
        "/api/v1/cache/servers",
        headers=auth_headers(reseller_token),
        json={"name": "Peer caído", "host": "127.0.0.1", "port": 1, "protocol": "csp"},
    ).json()
    failed = client.post(f"/api/v1/cache/servers/{closed['id']}/test", headers=auth_headers(reseller_token))
    assert failed.json()["ok"] is False
    assert failed.json()["error"]

    # config generada para ncam.server
    block = client.get(f"/api/v1/cache/servers/{server['id']}/config", headers=auth_headers(reseller_token)).json()["block"]
    assert "[reader]" in block
    assert "cachex" in block

    assert client.delete(f"/api/v1/cache/servers/{server['id']}", headers=auth_headers(reseller_token)).status_code == 200
    assert client.delete(f"/api/v1/cache/servers/{closed['id']}", headers=auth_headers(reseller_token)).status_code == 200


def test_cache_server_concurrent_probe_without_500(client, reseller_token, monkeypatch):
    """Varios «Probar» a la vez no deben terminar en HTTP 500 (regresión).

    El sondeo TCP tarda hasta segundos y corre fuera de la transacción de la
    petición: si la transacción de lectura se mantiene abierta durante la red,
    los UPDATE concurrentes chocan con «database is locked» (reproducido con
    12 peticiones a la vez: 11 devolvían 500).
    """
    original_probe = ncam_module.probe_tcp

    def slow_probe(host, port, timeout=3.0):
        time.sleep(0.5)  # fuerza el solape de las transacciones
        return original_probe("127.0.0.1", port, timeout=timeout)

    monkeypatch.setattr(ncam_module, "probe_tcp", slow_probe)
    created = client.post(
        "/api/v1/cache/servers",
        headers=auth_headers(reseller_token),
        json={"name": "Peer concurrente", "host": "127.0.0.1", "port": 1, "protocol": "cccam"},
    )
    assert created.status_code == 201, created.text
    server_id = created.json()["id"]

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    f"/api/v1/cache/servers/{server_id}/test",
                    headers=auth_headers(reseller_token),
                ),
                range(10),
            )
        )
    failures = [(response.status_code, response.text[:160]) for response in responses if response.status_code != 200]
    assert not failures, f"peticiones con error: {failures}"

    row = client.get(f"/api/v1/cache/servers/{server_id}", headers=auth_headers(reseller_token)).json()
    assert row["last_check_at"] is not None
    assert client.delete(
        f"/api/v1/cache/servers/{server_id}", headers=auth_headers(reseller_token)
    ).status_code == 200


def test_cache_server_validation(client, reseller_token):
    bad_port = client.post(
        "/api/v1/cache/servers",
        headers=auth_headers(reseller_token),
        json={"name": "Malo", "host": "127.0.0.1", "port": 99999},
    )
    assert bad_port.status_code == 422


def test_cache_config_blocks(client, admin_token, reseller_token):
    client.post(
        "/api/v1/lines",
        headers=auth_headers(reseller_token),
        json={"name": "Para config", "protocol": "cccam", "days": 5},
    )
    data = client.get("/api/v1/cache/config", headers=auth_headers(admin_token)).json()
    blocks = data["blocks"]
    assert "[cache]" in blocks["ncam.conf"]
    assert "max_entries" in blocks["ncam.conf"]
    assert "[account]" in blocks["ncam.user"]

    download = client.get("/api/v1/cache/config/download?file=ncam.conf", headers=auth_headers(admin_token))
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    invalid = client.get("/api/v1/cache/config/download?file=passwd", headers=auth_headers(admin_token))
    assert invalid.status_code == 422


def test_snapshot_without_daemon_is_reported_not_fatal(client, admin_token):
    response = client.post("/api/v1/cache/stats/snapshot", headers=auth_headers(admin_token))
    assert response.status_code == 200
    assert response.json()["saved"] == 0


def test_settings_whitelist_and_secret_masking(client, admin_token, reseller_token):
    # el reseller no puede leer los ajustes internos del daemon
    values = client.get("/api/v1/settings", headers=auth_headers(reseller_token)).json()["items"]
    assert not any(key.startswith("ncam.") for key in values)

    client.patch(
        "/api/v1/settings",
        headers=auth_headers(admin_token),
        json={"values": {"panel.ncam_webif_password": "secreto-del-webif", "panel.public_host": "cam.midominio.tv"}},
    )
    admin_values = client.get("/api/v1/settings", headers=auth_headers(admin_token)).json()["items"]
    assert admin_values["panel.ncam_webif_password"] == "***"
    assert admin_values["panel.public_host"] == "cam.midominio.tv"

    # una clave no permitida se rechaza sin romper el resto
    result = client.patch(
        "/api/v1/settings",
        headers=auth_headers(admin_token),
        json={"values": {"sistema.inventado": "1", "billing.currency": "€"}},
    ).json()
    assert "sistema.inventado" in result["rejected"]
    assert result["applied"]["billing.currency"] == "€"


def test_panel_poll_setting_controls_automatic_sampling(client, admin_token):
    """El muestreo automático se puede apagar desde Ajustes (ncam.cache.panel_poll)."""
    from app import db as database
    from app import main as panel_main
    from app import ncam as ncam_module

    def fake_stats(conn):
        return {
            "reachable": True,
            "hit_ratio": 0.5,
            "entries": 1,
            "lookups": 10,
            "hits": 5,
            "misses": 5,
            "mem_bytes": 1024,
        }

    original = ncam_module.fetch_cache_stats
    ncam_module.fetch_cache_stats = fake_stats
    try:
        # con el ajuste a 0, el planificador no guarda nada
        client.patch(
            "/api/v1/settings",
            headers=auth_headers(admin_token),
            json={"values": {"ncam.cache.panel_poll": "0"}},
        )
        panel_main._collect_snapshot()
        with database.session() as conn:
            assert database.query_one(
                conn, "SELECT COUNT(*) AS total FROM usage_snapshots WHERE source = 'panel-poller'"
            )["total"] == 0

        # con el ajuste a 1, sí guarda
        client.patch(
            "/api/v1/settings",
            headers=auth_headers(admin_token),
            json={"values": {"ncam.cache.panel_poll": "1"}},
        )
        panel_main._collect_snapshot()
        with database.session() as conn:
            assert database.query_one(
                conn, "SELECT COUNT(*) AS total FROM usage_snapshots WHERE source = 'panel-poller'"
            )["total"] > 0
    finally:
        ncam_module.fetch_cache_stats = original


def test_reseller_cannot_change_settings(client, reseller_token):
    response = client.patch(
        "/api/v1/settings", headers=auth_headers(reseller_token), json={"values": {"billing.line_cost": "0"}}
    )
    assert response.status_code == 403


def test_api_key_authentication(client, admin_token):
    accounts = client.get("/api/v1/accounts", headers=auth_headers(admin_token)).json()["items"]
    reseller = next(item for item in accounts if item["username"] == "revendedor")

    rotated = client.post(f"/api/v1/accounts/{reseller['id']}/api-key", headers=auth_headers(admin_token))
    assert rotated.status_code == 200
    api_key = rotated.json()["api_key"]
    assert api_key.startswith("ng_")

    response = client.get("/api/v1/lines", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert client.get("/api/v1/lines", headers={"X-API-Key": "ng_invalida"}).status_code == 401


def test_audit_log_records_sensitive_actions(client, admin_token):
    logs = client.get("/api/v1/audit-logs?limit=200", headers=auth_headers(admin_token)).json()["items"]
    actions = {item["action"] for item in logs}
    assert "auth.login" in actions
    assert "line.create.done" in actions
    assert "settings.update" in actions
    assert all(item["created_at"] for item in logs)


def test_reseller_audit_scope(client, reseller_token, admin_token):
    logs = client.get("/api/v1/audit-logs?limit=200", headers=auth_headers(reseller_token)).json()["items"]
    actors = {item["actor_username"] for item in logs if item["actor_username"]}
    assert "superadmin" not in actors  # no ve las acciones del super admin


def test_meta_endpoint(client, admin_token):
    meta = client.get("/api/v1/meta", headers=auth_headers(admin_token)).json()
    assert "super_admin" in meta["roles"]
    assert "reseller" in meta["roles"]
    assert "cacheex" in meta["protocols"]


def test_maintenance_purge_requires_super_admin(client, admin_token, reseller_token):
    denied = client.post("/api/v1/maintenance/purge?days=30", headers=auth_headers(reseller_token))
    assert denied.status_code == 403
    ok = client.post("/api/v1/maintenance/purge?days=30", headers=auth_headers(admin_token))
    assert ok.status_code == 200
    assert "snapshots_removed" in ok.json()


def test_suspended_account_cannot_login_or_use_api(client, admin_token):
    created = client.post(
        "/api/v1/accounts",
        headers=auth_headers(admin_token),
        json={"username": "suspendido", "password": "Suspendido!2026", "role": "user"},
    ).json()

    token = client.post(
        "/api/v1/auth/login", json={"username": "suspendido", "password": "Suspendido!2026"}
    ).json()["access_token"]
    assert client.get("/api/v1/lines", headers=auth_headers(token)).status_code == 200

    client.patch(f"/api/v1/accounts/{created['id']}", headers=auth_headers(admin_token), json={"status": "suspended"})

    assert client.post(
        "/api/v1/auth/login", json={"username": "suspendido", "password": "Suspendido!2026"}
    ).status_code == 403
    assert client.get("/api/v1/lines", headers=auth_headers(token)).status_code == 403
