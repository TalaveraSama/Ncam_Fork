"""Pruebas de los avisos de caducidad (email / Telegram)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app import db as database
from app import notifications
from app.services import utcnow

from .conftest import auth_headers


@pytest.fixture()
def expiring_line(client, reseller_token):
    """Crea una línea del reseller que caduca en 2 días y la borra al terminar."""
    with database.session() as conn:
        owner = database.query_one(conn, "SELECT * FROM users WHERE username = 'revendedor'")
        line_id = database.insert(
            conn,
            "lines",
            {
                "owner_id": owner["id"],
                "name": "Linea por caducar",
                "protocol": "cccam",
                "username": "linea_aviso_test",
                "password": "secreto",
                "group_name": "1",
                "max_connections": 1,
                "expires_at": (utcnow() + timedelta(days=2)).replace(microsecond=0).isoformat(),
                "status": "active",
                "created_at": database.utcnow(),
                "updated_at": database.utcnow(),
                "notify_email": "cliente@example.com",
                "notify_telegram": "555000",
            },
        )
    yield line_id
    with database.session() as conn:
        database.execute(conn, "DELETE FROM notification_log WHERE line_id = ?", (line_id,))
        database.execute(conn, "DELETE FROM lines WHERE id = ?", (line_id,))


def test_expiring_endpoint_lists_line(client, reseller_token, expiring_line):
    response = client.get("/api/v1/notifications/expiring?days=7", headers=auth_headers(reseller_token))
    assert response.status_code == 200, response.text
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert expiring_line in ids
    item = next(item for item in body["items"] if item["id"] == expiring_line)
    assert item["days_left"] == 2
    assert item["owner_username"] == "revendedor"


def test_run_dry_run_does_not_send(client, admin_token, expiring_line, monkeypatch):
    sent: list = []
    monkeypatch.setattr(notifications, "send_email", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(notifications, "send_telegram", lambda *a, **k: sent.append(a))

    with database.session() as conn:
        database.set_setting(conn, "notify.enabled", "1")
        database.set_setting(conn, "notify.channel.email", "1")
        database.set_setting(conn, "notify.days_before", "5")

    response = client.post(
        "/api/v1/notifications/run", json={"dry_run": True}, headers=auth_headers(admin_token)
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["dry_run"] is True
    assert any(item["line_id"] == expiring_line for item in report["sent"])
    assert sent == []  # en simulación no se envía nada

    # tampoco debe quedar registro en el histórico
    with database.session() as conn:
        rows = database.query(
            conn, "SELECT * FROM notification_log WHERE line_id = ?", (expiring_line,)
        )
    assert rows == []


def test_run_sends_and_dedupes(client, admin_token, expiring_line, monkeypatch):
    calls: list[tuple] = []

    def fake_email(conf, target, subject, body):
        calls.append(("email", target, subject))

    def fake_telegram(conf, target, text):
        calls.append(("telegram", target, text))

    monkeypatch.setattr(notifications, "send_email", fake_email)
    monkeypatch.setattr(notifications, "send_telegram", fake_telegram)

    with database.session() as conn:
        database.set_setting(conn, "notify.enabled", "1")
        database.set_setting(conn, "notify.channel.email", "1")
        database.set_setting(conn, "notify.channel.telegram", "1")
        database.set_setting(conn, "notify.days_before", "5")
        database.set_setting(conn, "notify.smtp.host", "smtp.example.com")
        database.set_setting(conn, "notify.telegram.bot_token", "123:ABC")

    first = client.post(
        "/api/v1/notifications/run", json={"days": 5}, headers=auth_headers(admin_token)
    )
    assert first.status_code == 200, first.text
    report = first.json()
    mine = [item for item in report["sent"] if item["line_id"] == expiring_line]
    assert {item["channel"] for item in mine} == {"email", "telegram"}
    assert {call[0] for call in calls} == {"email", "telegram"}

    # segunda pasada: no debe reenviar la misma línea
    calls.clear()
    second = client.post(
        "/api/v1/notifications/run", json={"days": 5}, headers=auth_headers(admin_token)
    )
    assert second.status_code == 200
    assert [item for item in second.json()["sent"] if item["line_id"] == expiring_line] == []
    assert calls == []
    skipped = [item for item in second.json()["skipped"] if item["line_id"] == expiring_line]
    assert skipped and all(
        "ya" in item["reason"] or "últimas" in item["reason"] for item in skipped
    )

    # forzando se vuelve a enviar (útil desde el panel)
    forced = client.post(
        "/api/v1/notifications/run",
        json={"force": True, "days": 5, "channels": ["email", "telegram"]},
        headers=auth_headers(admin_token),
    )
    assert forced.status_code == 200
    assert len([item for item in forced.json()["sent"] if item["line_id"] == expiring_line]) == 2
    assert {call[0] for call in calls} == {"email", "telegram"}


def test_failures_are_recorded_and_retried(client, admin_token, expiring_line, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("smtp caído")

    monkeypatch.setattr(notifications, "send_email", boom)

    with database.session() as conn:
        database.set_setting(conn, "notify.enabled", "1")
        database.set_setting(conn, "notify.channel.email", "1")
        database.set_setting(conn, "notify.days_before", "5")

    response = client.post(
        "/api/v1/notifications/run", json={"channels": ["email"], "force": True}, headers=auth_headers(admin_token)
    )
    assert response.status_code == 200
    assert response.json()["failed"], "el fallo debe reportarse"
    assert "smtp caído" in response.json()["failed"][0]["error"]

    with database.session() as conn:
        last = database.query_one(
            conn,
            "SELECT * FROM notification_log WHERE line_id = ? ORDER BY id DESC LIMIT 1",
            (expiring_line,),
        )
    assert last["status"] == "failed"
    assert "smtp caído" in last["error"]


def test_line_without_destination_is_skipped(client, admin_token, monkeypatch):
    monkeypatch.setattr(notifications, "send_email", lambda *a, **k: pytest.fail("no debe enviarse"))
    with database.session() as conn:
        database.set_setting(conn, "notify.channel.email", "1")
        owner = database.query_one(conn, "SELECT * FROM users WHERE username = 'cliente'")
        line_id = database.insert(
            conn,
            "lines",
            {
                "owner_id": owner["id"],
                "name": "Sin destino",
                "protocol": "newcamd",
                "username": "linea_sin_destino_test",
                "password": "secreto",
                "group_name": "1",
                "expires_at": (utcnow() + timedelta(days=1)).replace(microsecond=0).isoformat(),
                "status": "active",
                "created_at": database.utcnow(),
                "updated_at": database.utcnow(),
            },
        )
    try:
        response = client.post(
            "/api/v1/notifications/run",
            json={"channels": ["email"], "force": True, "days": 5},
            headers=auth_headers(admin_token),
        )
        assert response.status_code == 200
        skipped = [item for item in response.json()["skipped"] if item["line_id"] == line_id]
        assert skipped and skipped[0]["reason"] == "sin destino configurado"
    finally:
        with database.session() as conn:
            database.execute(conn, "DELETE FROM notification_log WHERE line_id = ?", (line_id,))
            database.execute(conn, "DELETE FROM lines WHERE id = ?", (line_id,))


def test_telegram_payload(monkeypatch):
    """Comprueba la petición real a la Bot API sin salir a Internet."""
    captured: dict = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(notifications.urllib.request, "urlopen", fake_urlopen)
    conf = {"telegram": {"bot_token": "999:XYZ"}}
    notifications.send_telegram(conf, "12345", "hola línea")

    import json

    assert captured["url"] == "https://api.telegram.org/bot999:XYZ/sendMessage"
    payload = json.loads(captured["body"])
    assert payload["chat_id"] == "12345"
    assert payload["text"] == "hola línea"


def test_message_singular_plural():
    line = {"name": "L1", "protocol": "cccam", "username": "u1", "owner_username": "rev", "expires_at": "2026-01-01"}
    subject_one, body_one = notifications.build_message(line, 1, "Panel")
    subject_many, _ = notifications.build_message(line, 3, "Panel")
    assert "en 1 día" in subject_one
    assert "en 3 días" in subject_many
    assert "Días restantes: 1" in body_one


def test_user_role_cannot_run(client, client_token):
    response = client.post("/api/v1/notifications/run", json={}, headers=auth_headers(client_token))
    assert response.status_code == 403


def test_config_summary_hides_secrets(client, admin_token):
    with database.session() as conn:
        database.set_setting(conn, "notify.telegram.bot_token", "secreto-telegram")
    response = client.get("/api/v1/notifications/config", headers=auth_headers(admin_token))
    assert response.status_code == 200
    payload = response.text
    assert "secreto-telegram" not in payload
    body = response.json()
    assert {"enabled", "days_before", "email", "telegram"} <= set(body)


def test_history_endpoint(client, admin_token, expiring_line, monkeypatch):
    monkeypatch.setattr(notifications, "send_email", lambda *a, **k: None)
    with database.session() as conn:
        database.set_setting(conn, "notify.channel.email", "1")
        database.set_setting(conn, "notify.days_before", "5")

    client.post(
        "/api/v1/notifications/run",
        json={"channels": ["email"], "force": True, "days": 5},
        headers=auth_headers(admin_token),
    )
    response = client.get("/api/v1/notifications/log?limit=50", headers=auth_headers(admin_token))
    assert response.status_code == 200
    items = [item for item in response.json()["items"] if item["line_id"] == expiring_line]
    assert items, "el envío debe aparecer en el histórico"
    assert items[0]["channel"] == "email"
    assert items[0]["line_name"] == "Linea por caducar"
    assert items[0]["status"] == "sent"


def test_line_notify_days_threshold(client, admin_token, expiring_line):
    """Una línea con notify_days propio no avisa si aún falta más que ese umbral."""
    with database.session() as conn:
        database.execute(conn, "UPDATE lines SET notify_days = 1 WHERE id = ?", (expiring_line,))
    response = client.post(
        "/api/v1/notifications/run",
        json={"days": 10, "dry_run": True},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    skipped = [item for item in response.json()["skipped"] if item["line_id"] == expiring_line]
    assert skipped and "no toca" in skipped[0]["reason"]
    with database.session() as conn:
        database.execute(conn, "UPDATE lines SET notify_days = 0 WHERE id = ?", (expiring_line,))


def test_settings_are_editable(client, admin_token):
    response = client.patch(
        "/api/v1/settings",
        json={"values": {"notify.days_before": "7", "notify.channel.email": "1"}},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["rejected"] == []
    assert response.json()["applied"]["notify.days_before"] == "7"

    listing = client.get("/api/v1/settings", headers=auth_headers(admin_token))
    items = listing.json()["items"]
    assert items["notify.days_before"] == "7"
    assert items["notify.smtp.password"] in ("", "***")
