"""
NCam-NG Panel :: inicialización de datos (seed).

Crea el super administrador (si no existe), un reseller de ejemplo y un par de
líneas/peers de demostración cuando se ejecuta con ``--demo``.

Uso:
    python -m app.seed                 # crea el super admin y muestra la clave
    python -m app.seed --demo          # añade datos de ejemplo
    python -m app.seed --username X --password Y
    python -m app.seed --username X --reset-password   # nueva clave para X
"""

from __future__ import annotations

import argparse
import secrets
import string
import sys
from . import db as database
from .config import settings
from .security import ROLE_RESELLER, ROLE_SUPER_ADMIN, hash_password
from .services import generate_line_credentials


def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def ensure_super_admin(username: str = "admin", password: str | None = None) -> tuple[str, str, bool]:
    """Garantiza que exista un super administrador. Devuelve (user, pwd, creado)."""
    created = False
    with database.session() as conn:
        existing = database.query_one(conn, "SELECT * FROM users WHERE role = ? LIMIT 1", (ROLE_SUPER_ADMIN,))
        if existing:
            return str(existing["username"]), "", False

        password = password or _random_password()
        now = database.utcnow()
        database.insert(
            conn,
            "users",
            {
                "username": username,
                "password_hash": hash_password(password),
                "role": ROLE_SUPER_ADMIN,
                "credits": 0,
                "max_lines": 0,
                "status": "active",
                "notes": "Cuenta creada automáticamente por el seed del panel",
                "created_at": now,
                "updated_at": now,
            },
        )
        created = True
    return username, password or "", created


def create_demo_data() -> None:
    """Datos de ejemplo para probar el panel sin NCam en marcha."""
    from .services import create_account, create_cache_server, create_line

    class _SystemContext:
        """Contexto mínimo para reutilizar los servicios desde el seed."""

        id = 1
        username = "seed"
        role = ROLE_SUPER_ADMIN
        user: dict = {}

        @property
        def is_super_admin(self) -> bool:
            return True

        @property
        def is_reseller(self) -> bool:
            return False

        def owns(self, owner_id) -> bool:  # pragma: no cover - sencillo
            return True

    ctx = _SystemContext()
    with database.session() as conn:
        admin = database.query_one(conn, "SELECT * FROM users WHERE role = ? LIMIT 1", (ROLE_SUPER_ADMIN,))
        if not admin:
            raise SystemExit("Ejecute primero el seed del super administrador")
        ctx.id = int(admin["id"])

        existing = database.query_one(conn, "SELECT id FROM users WHERE username = ?", ("demo_reseller",))
        if existing:
            print("Los datos de demostración ya existen")
            return

        reseller = create_account(
            conn,
            ctx,
            {
                "username": "demo_reseller",
                "password": "DemoReseller!2026",
                "role": ROLE_RESELLER,
                "email": "reseller@example.com",
                "credits": 500,
                "max_lines": 50,
                "notes": "Revendedor de demostración",
            },
        )

        user = create_account(
            conn,
            ctx,
            {
                "username": "demo_cliente",
                "password": "DemoCliente!2026",
                "role": "user",
                "parent_id": int(reseller["id"]),
                "credits": 25,
            },
        )

        for name, protocol, days in (("Demo CCcam", "cccam", 30), ("Demo Newcamd", "newcamd", 90)):
            username, _ = generate_line_credentials(protocol)
            create_line(
                conn,
                ctx,
                {
                    "name": name,
                    "protocol": protocol,
                    "username": username,
                    "group_name": "1",
                    "max_connections": 2,
                    "days": days,
                    "owner_id": int(reseller["id"]),
                    "cacheex_mode": 1 if protocol == "cccam" else 0,
                },
            )

        create_cache_server(
            conn,
            ctx,
            {
                "name": "CacheEx Demo",
                "host": "127.0.0.1",
                "port": 8181,
                "protocol": "cccam",
                "username": "cacheex",
                "password": "cacheex",
                "priority": 10,
                "owner_id": int(reseller["id"]),
            },
        )
        print(f"Creados: reseller=demo_reseller (id {reseller['id']}), usuario={user['username']}")


def reset_password(username: str, password: str | None = None) -> tuple[str, str] | None:
    """Asigna una contraseña nueva a un usuario que ya existe.

    Devuelve ``(usuario, contraseña)`` o ``None`` si el usuario no existe.
    """
    new_password = password or _random_password()
    with database.session() as conn:
        row = database.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,))
        if row is None:
            return None
        database.update(conn, "users", int(row["id"]), {"password_hash": hash_password(new_password)})
    return username, new_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inicializa la base de datos del panel NCam-NG")
    parser.add_argument("--username", default="admin", help="usuario del super administrador")
    parser.add_argument("--password", default=None, help="contraseña (si se omite se genera una)")
    parser.add_argument("--demo", action="store_true", help="crear datos de demostración")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="cambia la contraseña de --username (útil si se perdió la del super admin)",
    )
    args = parser.parse_args(argv)

    database.init_db()

    if args.reset_password:
        result = reset_password(args.username, args.password)
        if result is None:
            print(f"No existe ningún usuario llamado {args.username}.", file=sys.stderr)
            return 1
        user, new_password = result
        print("=" * 62)
        print("  CONTRASEÑA CAMBIADA")
        print(f"  usuario:    {user}")
        print(f"  contraseña: {new_password}")
        print("  Guárdela: no se vuelve a mostrar.")
        print("=" * 62)
        return 0

    username, password, created = ensure_super_admin(args.username, args.password)

    print(f"Base de datos: {settings.db_path}")
    if created:
        print("=" * 62)
        print("  SUPER ADMINISTRADOR CREADO")
        print(f"  usuario:    {username}")
        print(f"  contraseña: {password if password else '(definida por parámetro)'}")
        print("  Guarde estas credenciales: no se vuelven a mostrar.")
        print("=" * 62)
    else:
        print(f"El super administrador ya existe ({username}); no se han hecho cambios.")

    if args.demo:
        create_demo_data()

    return 0


if __name__ == "__main__":
    sys.exit(main())
