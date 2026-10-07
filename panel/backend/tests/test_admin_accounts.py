"""NCPanel :: varios administradores (super admins) y cambios de rol.

Comprueba, en una base de datos propia y aislada, las reglas que permiten tener
más de un administrador en el panel:

* un super admin puede crear otro super admin y el nuevo entra con control total;
* un revendedor no puede crear super admins ni cambiar roles;
* nadie puede cambiarse el rol ni suspenderse a sí mismo;
* no se puede dejar el panel sin ningún super admin **activo** (degradar,
  suspender o eliminar al último): una cuenta suspendida no puede entrar.

También pasa por la API HTTP para cubrir los mismos caminos con permisos y
sesiones reales.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app import db as database
from app import services
from app.security import ROLE_RESELLER, ROLE_SUPER_ADMIN, ROLE_USER

from .conftest import auth_headers


class _Ctx:
    """Contexto mínimo de autenticación para llamar a los servicios."""

    def __init__(self, user_id: int, username: str, role: str) -> None:
        self.id = user_id
        self.username = username
        self.role = role
        self.user: dict = {}

    @property
    def is_super_admin(self) -> bool:
        return self.role == ROLE_SUPER_ADMIN

    @property
    def is_reseller(self) -> bool:
        return self.role == ROLE_RESELLER

    def owns(self, owner_id) -> bool:
        return self.is_super_admin or int(owner_id or 0) == int(self.id)


@pytest.fixture()
def panel_db(tmp_path: Path):
    """Base de datos limpia con un super admin, un revendedor y un usuario."""
    path = tmp_path / "panel.db"
    database.init_db(path)
    now = database.utcnow()
    with database.session(path) as conn:
        admin = database.insert(
            conn,
            "users",
            {
                "username": "jefa",
                "password_hash": "x",
                "role": ROLE_SUPER_ADMIN,
                "credits": 0,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        reseller = database.insert(
            conn,
            "users",
            {
                "username": "revendedor2",
                "password_hash": "x",
                "role": ROLE_RESELLER,
                "credits": 100,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        child = database.insert(
            conn,
            "users",
            {
                "username": "cliente2",
                "password_hash": "x",
                "role": ROLE_USER,
                "parent_id": reseller,
                "credits": 0,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        database.set_setting(conn, "billing.line_cost", "10")
    return {"path": path, "admin": admin, "reseller": reseller, "child": child}


def _add(conn, ctx, username: str, role: str) -> dict:
    row = services.create_account(
        conn, ctx, {"username": username, "password": "ClaveSegura!23", "role": role}
    )
    return dict(row)


# ---------------------------------------------------------------------------
# servicios
# ---------------------------------------------------------------------------
def test_super_admin_creates_super_admin(panel_db):
    with database.session(panel_db["path"]) as conn:
        ctx = _Ctx(panel_db["admin"], "jefa", ROLE_SUPER_ADMIN)
        nuevo = _add(conn, ctx, "jefe2", ROLE_SUPER_ADMIN)
        assert nuevo["role"] == ROLE_SUPER_ADMIN
        assert nuevo["parent_id"] is None
        assert services.count_super_admins(conn) == 2

        # un revendedor no puede crear administradores
        with pytest.raises(HTTPException) as exc:
            _add(conn, _Ctx(panel_db["reseller"], "revendedor2", ROLE_RESELLER), "intruso", ROLE_SUPER_ADMIN)
        assert exc.value.status_code == 403
        assert "super administrador" in exc.value.detail

        # ni un usuario final puede crear cuentas
        with pytest.raises(HTTPException) as exc:
            _add(conn, _Ctx(panel_db["child"], "cliente2", ROLE_USER), "otro", ROLE_USER)
        assert exc.value.status_code == 403


def test_super_admin_can_change_roles(panel_db):
    with database.session(panel_db["path"]) as conn:
        ctx = _Ctx(panel_db["admin"], "jefa", ROLE_SUPER_ADMIN)
        otro = _add(conn, ctx, "jefe2", ROLE_SUPER_ADMIN)

        # degradarlo es posible porque queda otro super admin
        actualizado = dict(services.update_account(conn, ctx, int(otro["id"]), {"role": ROLE_RESELLER}))
        assert actualizado["role"] == ROLE_RESELLER
        assert services.count_super_admins(conn) == 1

        # ascender al revendedor de siempre
        ascendido = dict(services.update_account(conn, ctx, int(panel_db["reseller"]), {"role": ROLE_SUPER_ADMIN}))
        assert ascendido["role"] == ROLE_SUPER_ADMIN
        assert services.count_super_admins(conn) == 2

        # un revendedor no puede cambiar roles (ni el suyo propio)
        rev = _Ctx(panel_db["reseller"], "revendedor2", ROLE_RESELLER)
        with pytest.raises(HTTPException) as exc:
            services.update_account(conn, rev, int(panel_db["reseller"]), {"role": ROLE_USER})
        assert exc.value.status_code in (400, 403)
        with pytest.raises(HTTPException) as exc:
            services.update_account(conn, rev, int(panel_db["child"]), {"role": ROLE_RESELLER})
        assert exc.value.status_code == 403
        assert "super administrador" in exc.value.detail

        # nadie puede cambiarse el rol a sí mismo
        with pytest.raises(HTTPException) as exc:
            services.update_account(conn, ctx, int(panel_db["admin"]), {"role": ROLE_USER})
        assert exc.value.status_code == 400
        assert "a sí mismo" in exc.value.detail


def test_last_active_super_admin_is_protected(panel_db):
    jefa = int(panel_db["admin"])
    with database.session(panel_db["path"]) as conn:
        ctx = _Ctx(jefa, "jefa", ROLE_SUPER_ADMIN)
        segundo = _add(conn, ctx, "jefe2", ROLE_SUPER_ADMIN)

        # se puede suspender a un administrador mientras quede otro activo
        suspendido = dict(services.update_account(conn, ctx, int(segundo["id"]), {"status": "suspended"}))
        assert suspendido["status"] == "suspended"
        assert services.count_super_admins(conn) == 1

        otro = _Ctx(int(segundo["id"]), "jefe2", ROLE_SUPER_ADMIN)
        # el único super admin activo no se puede degradar...
        with pytest.raises(HTTPException) as exc:
            services.update_account(conn, otro, jefa, {"role": ROLE_USER})
        assert exc.value.status_code == 400
        assert "super administrador" in exc.value.detail
        # ... ni suspender
        with pytest.raises(HTTPException) as exc:
            services.update_account(conn, otro, jefa, {"status": "suspended"})
        assert exc.value.status_code == 400
        # ... ni eliminar
        with pytest.raises(HTTPException) as exc:
            services.delete_account(conn, otro, jefa)
        assert exc.value.status_code == 400
        assert "super administrador" in exc.value.detail

        # y cada uno no puede borrarse a sí mismo (aviso propio, antes del guarda)
        with pytest.raises(HTTPException) as exc:
            services.delete_account(conn, ctx, jefa)
        assert "propia cuenta" in exc.value.detail

        # al reactivar al segundo, recuperar el rol de jefa ya es posible
        services.update_account(conn, ctx, int(segundo["id"]), {"status": "active"})
        assert services.count_super_admins(conn) == 2
        degradada = dict(services.update_account(conn, otro, jefa, {"role": ROLE_RESELLER}))
        assert degradada["role"] == ROLE_RESELLER


def test_role_change_is_audited(panel_db):
    with database.session(panel_db["path"]) as conn:
        ctx = _Ctx(panel_db["admin"], "jefa", ROLE_SUPER_ADMIN)
        _add(conn, ctx, "jefe2", ROLE_SUPER_ADMIN)
        services.update_account(conn, ctx, int(panel_db["reseller"]), {"role": ROLE_SUPER_ADMIN})
        rows = database.query(
            conn, "SELECT details FROM audit_logs WHERE action = 'account.update' ORDER BY id DESC LIMIT 3"
        )
        detalle = " ".join(str(row["details"]) for row in rows)
        assert "role" in detalle and "super_admin" in detalle


# ---------------------------------------------------------------------------
# API HTTP (permisos y sesiones reales)
# ---------------------------------------------------------------------------
def test_api_super_admin_creates_super_admin_who_can_log_in(client, admin_token):
    respuesta = client.post(
        "/api/v1/accounts",
        headers=auth_headers(admin_token),
        json={"username": "nuevo_admin", "password": "ClaveSegura!23", "role": "super_admin"},
    )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["role"] == "super_admin"

    acceso = client.post(
        "/api/v1/auth/login", json={"username": "nuevo_admin", "password": "ClaveSegura!23"}
    )
    assert acceso.status_code == 200, acceso.text
    assert acceso.json()["user"]["role"] == "super_admin"

    # el nuevo administrador entra en Ajustes (un revendedor no podría)
    cabeceras = auth_headers(acceso.json()["access_token"])
    assert client.get("/api/v1/settings", headers=cabeceras).status_code == 200


def test_api_reseller_cannot_create_super_admin(client, reseller_token):
    respuesta = client.post(
        "/api/v1/accounts",
        headers=auth_headers(reseller_token),
        json={"username": "intruso", "password": "ClaveSegura!23", "role": "super_admin"},
    )
    assert respuesta.status_code == 403
    assert "super administrador" in respuesta.json()["detail"]


def test_api_cannot_change_own_role(client, admin_token):
    yo = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    respuesta = client.patch(
        f"/api/v1/accounts/{yo['id']}", headers=auth_headers(admin_token), json={"role": "user"}
    )
    assert respuesta.status_code == 400
    assert "a sí mismo" in respuesta.json()["detail"]
