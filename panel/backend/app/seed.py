"""
NCPanel :: inicialización de datos (seed).

Crea el super administrador (si no existe), un reseller de ejemplo y un par de
líneas/peers de demostración cuando se ejecuta con ``--demo``.

Uso:
    python -m app.seed                 # crea el super admin y muestra la clave
    python -m app.seed --demo          # añade datos de ejemplo
    python -m app.seed --list          # cuentas del panel (usuario, rol, estado)
    python -m app.seed --create --username X --role super_admin
    python -m app.seed --create --username Y --role reseller --email y@ejemplo.com
    python -m app.seed --set-role X super_admin|reseller|user
    python -m app.seed --delete X
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
from .security import ALL_ROLES, ROLE_RESELLER, ROLE_SUPER_ADMIN, ROLE_USER, hash_password
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


def _super_admin_count(conn, exclude_id: int | None = None) -> int:
    # solo cuentan los activos: uno suspendido no puede entrar en el panel
    sql = "SELECT COUNT(*) AS c FROM users WHERE role = ? AND status = 'active'"
    params: list = [ROLE_SUPER_ADMIN]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(int(exclude_id))
    return int(database.query_one(conn, sql, params)["c"])


def _print_credentials(title: str, username: str, password: str) -> None:
    print("=" * 62)
    print(f"  {title}")
    print(f"  usuario:    {username}")
    print(f"  contraseña: {password}")
    print("  Guárdela: no se vuelve a mostrar.")
    print("=" * 62)


def create_user(
    username: str,
    password: str | None = None,
    role: str = ROLE_SUPER_ADMIN,
    email: str | None = None,
) -> tuple[str, str, str]:
    """Crea una cuenta con el rol indicado (permite varios super admins).

    Devuelve ``(usuario, contraseña, rol)``. Falla con ``SystemExit`` si el
    usuario ya existe o el rol no es válido.
    """
    if role not in ALL_ROLES:
        raise SystemExit(f"Rol desconocido '{role}'. Válidos: {', '.join(ALL_ROLES)}")

    username = username.strip()
    with database.session() as conn:
        if database.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,)):
            raise SystemExit(
                f"Ya existe un usuario '{username}'. Use --set-role para cambiar su rol "
                "o --username " + username + " --reset-password para su contraseña."
            )

        new_password = password or _random_password()
        now = database.utcnow()
        database.insert(
            conn,
            "users",
            {
                "username": username,
                "password_hash": hash_password(new_password),
                "role": role,
                "email": email,
                "credits": 0,
                "max_lines": 0,
                "status": "active",
                "notes": f"Cuenta {role} creada desde la consola (app.seed --create)",
                "created_at": now,
                "updated_at": now,
            },
        )
    return username, new_password, role


def list_users() -> list[dict]:
    """Cuentas del panel ordenadas por rol y nombre."""
    with database.session() as conn:
        rows = database.query(
            conn,
            "SELECT id, username, role, status, credits, email, parent_id, created_at"
            " FROM users"
            " ORDER BY CASE role WHEN 'super_admin' THEN 0 WHEN 'reseller' THEN 1 ELSE 2 END, username",
        )
    return [dict(row) for row in rows]


def set_user_role(username: str, role: str) -> tuple[str, str]:
    """Cambia el rol de una cuenta. No deja el panel sin super administradores."""
    if role not in ALL_ROLES:
        raise SystemExit(f"Rol desconocido '{role}'. Válidos: {', '.join(ALL_ROLES)}")
    with database.session() as conn:
        row = database.query_one(conn, "SELECT * FROM users WHERE username = ?", (username,))
        if row is None:
            raise SystemExit(f"No existe ningún usuario llamado {username}.")
        previous = str(row["role"])
        if previous == role:
            return username, previous
        if previous == ROLE_SUPER_ADMIN and _super_admin_count(conn, exclude_id=int(row["id"])) == 0:
            raise SystemExit(
                "No se puede degradar el único super administrador activo: cree antes otro"
                " (ncam-ng-ctl admin add USUARIO)."
            )
        values: dict = {"role": role, "updated_at": database.utcnow()}
        if role == ROLE_SUPER_ADMIN:
            values["parent_id"] = None    # un super administrador no depende de nadie
        database.update(conn, "users", int(row["id"]), values)
    return username, previous


def delete_user(username: str) -> str:
    """Elimina una cuenta (nunca el último super administrador)."""
    with database.session() as conn:
        row = database.query_one(conn, "SELECT * FROM users WHERE username = ?", (username,))
        if row is None:
            raise SystemExit(f"No existe ningún usuario llamado {username}.")
        if row["role"] == ROLE_SUPER_ADMIN and _super_admin_count(conn, exclude_id=int(row["id"])) == 0:
            raise SystemExit("No se puede eliminar el único super administrador activo del panel.")
        database.execute(conn, "DELETE FROM users WHERE id = ?", (int(row["id"]),))
    return username


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
    parser.add_argument(
        "--create",
        action="store_true",
        help="crea la cuenta de --username con --role (aunque ya existan administradores)",
    )
    parser.add_argument(
        "--role",
        choices=list(ALL_ROLES),
        default=None,
        help="rol para --create (por defecto super_admin)",
    )
    parser.add_argument("--email", default=None, help="email de la cuenta creada con --create")
    parser.add_argument("--list", dest="list_accounts", action="store_true", help="lista las cuentas del panel")
    parser.add_argument(
        "--set-role",
        nargs=2,
        metavar=("USUARIO", "ROL"),
        help="cambia el rol de una cuenta (super_admin|reseller|user)",
    )
    parser.add_argument("--delete", metavar="USUARIO", help="elimina una cuenta del panel")
    args = parser.parse_args(argv)

    database.init_db()

    if args.list_accounts:
        rows = list_users()
        if not rows:
            print("Todavía no hay ninguna cuenta en el panel.")
            return 0
        roles = {ROLE_SUPER_ADMIN: "super admin", ROLE_RESELLER: "revendedor", ROLE_USER: "usuario"}
        print(f"Base de datos: {settings.db_path}")
        print(f"{'id':>4}  {'usuario':<24} {'rol':<12} {'estado':<10} {'líneas/vínculo'}")
        print("-" * 72)
        for row in rows:
            role = roles.get(str(row["role"]), str(row["role"]))
            parent = f"  (padre id {row['parent_id']})" if row["parent_id"] else ""
            email = f"  {row['email']}" if row["email"] else ""
            print(f"{row['id']:>4}  {row['username']:<24} {role:<12} {row['status']:<10}{parent}{email}")
        print()
        print("Crear otro administrador:  ncam-ng-ctl admin add USUARIO [super_admin|reseller|user]")
        return 0

    if args.set_role:
        username, role = args.set_role
        user, previous = set_user_role(username, role)
        print(f"Rol cambiado: {user} era '{previous}' y ahora es '{role}'.")
        if role == ROLE_SUPER_ADMIN:
            print("Ya puede entrar en el panel con su usuario y contraseña actuales.")
        return 0

    if args.delete:
        user = delete_user(args.delete)
        print(f"Cuenta eliminada: {user}")
        return 0

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

    if args.create:
        role = args.role or ROLE_SUPER_ADMIN
        username, password, role = create_user(args.username, args.password, role, args.email)
        print(f"Base de datos: {settings.db_path}")
        _print_credentials("CUENTA CREADA", username, password)
        if role == ROLE_SUPER_ADMIN:
            print("Entra en el panel con este usuario: tiene control total (super admin).")
        elif role == ROLE_RESELLER:
            print("Entra en el panel con este usuario: gestiona sus líneas y sus usuarios.")
        else:
            print("Entra en el panel con este usuario: solo lectura de sus líneas.")
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
        print("Para crear OTRO administrador:  ncam-ng-ctl admin add USUARIO [rol]")

    if args.demo:
        create_demo_data()

    return 0


if __name__ == "__main__":
    sys.exit(main())
