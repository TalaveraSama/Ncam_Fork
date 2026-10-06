"""
NCPanel :: configuración de la aplicación.

Toda la configuración se toma de variables de entorno (o de un archivo .env
situado junto al panel) para que el despliegue no requiera tocar el código.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]          # .../panel
BACKEND_DIR = Path(__file__).resolve().parents[1]       # .../panel/backend
FRONTEND_DIR = BASE_DIR / "frontend"


def _load_dotenv() -> None:
    """Carga panel/.env (si existe) sin dependencias externas."""
    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _env_list(name: str, default: str) -> tuple[str, ...]:
    """Lista separada por comas (admite IPs y rangos CIDR)."""
    raw = os.environ.get(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _secret_key() -> str:
    """Clave de firma de los tokens.

    Si no se define NCAM_PANEL_SECRET se genera una y se guarda en
    panel/.secret_key para que los tokens sobrevivan a los reinicios.
    """
    from_env = os.environ.get("NCAM_PANEL_SECRET")
    if from_env:
        return from_env
    secret_file = BASE_DIR / ".secret_key"
    if secret_file.is_file():
        return secret_file.read_text(encoding="utf-8").strip()
    generated = secrets.token_urlsafe(48)
    try:
        secret_file.write_text(generated, encoding="utf-8")
        os.chmod(secret_file, 0o600)
    except OSError:
        pass
    return generated


@dataclass(frozen=True)
class Settings:
    # --- servidor -----------------------------------------------------------
    host: str = os.environ.get("NCAM_PANEL_HOST", "0.0.0.0")
    port: int = _env_int("NCAM_PANEL_PORT", 8080)
    debug: bool = _env_bool("NCAM_PANEL_DEBUG", False)

    # --- seguridad ----------------------------------------------------------
    secret_key: str = field(default_factory=_secret_key)
    access_token_ttl: int = _env_int("NCAM_PANEL_ACCESS_TTL", 30 * 60)         # 30 min
    refresh_token_ttl: int = _env_int("NCAM_PANEL_REFRESH_TTL", 7 * 24 * 3600)  # 7 días
    password_min_length: int = _env_int("NCAM_PANEL_PASSWORD_MIN", 10)
    max_login_attempts: int = _env_int("NCAM_PANEL_MAX_LOGIN_ATTEMPTS", 8)
    login_lockout_seconds: int = _env_int("NCAM_PANEL_LOGIN_LOCKOUT", 300)
    # Proxies de confianza (IPs o rangos CIDR). Solo si la conexión llega desde
    # uno de ellos se hace caso a CF-Connecting-IP / X-Forwarded-For / X-Real-IP:
    # si no, cualquiera podría falsear su IP en la auditoría y saltarse el bloqueo
    # por intentos fallidos. Por defecto la propia máquina, que es lo que se ve
    # con cloudflared, nginx, Caddy o el proxy del panel en el mismo servidor.
    trusted_proxies: tuple[str, ...] = _env_list("NCAM_PANEL_TRUSTED_PROXIES", "127.0.0.1,::1")

    # --- base de datos ------------------------------------------------------
    db_path: Path = Path(os.environ.get("NCAM_PANEL_DB", str(BACKEND_DIR / "data" / "panel.db")))

    # --- integración con NCam ----------------------------------------------
    # WebIf de NCam (para leer estadísticas del motor de caché, estado,
    # usuarios conectados...). Puede ser interna: http://127.0.0.1:8181
    ncam_webif_url: str = os.environ.get("NCAM_WEBIF_URL", "http://127.0.0.1:8181").rstrip("/")
    ncam_webif_user: str = os.environ.get("NCAM_WEBIF_USER", "")
    ncam_webif_password: str = os.environ.get("NCAM_WEBIF_PASSWORD", "")
    ncam_timeout: float = float(os.environ.get("NCAM_WEBIF_TIMEOUT", "4"))
    # Si está activo, el panel guarda periódicamente una muestra de las
    # estadísticas de caché para poder dibujar históricos.
    ncam_poll_enabled: bool = _env_bool("NCAM_PANEL_CACHE_POLL", True)
    ncam_poll_interval: int = _env_int("NCAM_PANEL_CACHE_POLL_INTERVAL", 60)

    # --- avisos de caducidad -----------------------------------------------
    panel_name: str = os.environ.get("NCAM_PANEL_NAME", "NCPanel")
    # el envío periódico se controla con notify.enabled / notify.interval_seconds
    # en los ajustes del panel; esto es solo el valor de arranque del planificador
    notify_enabled: bool = _env_bool("NCAM_PANEL_NOTIFY", True)

    # --- reglas de negocio --------------------------------------------------
    default_line_days: int = _env_int("NCAM_PANEL_LINE_DAYS", 30)
    line_cost_credits: int = _env_int("NCAM_PANEL_LINE_COST", 10)
    renew_cost_credits: int = _env_int("NCAM_PANEL_RENEW_COST", 10)
    reseller_default_credits: int = _env_int("NCAM_PANEL_RESELLER_CREDITS", 100)
    default_group: str = os.environ.get("NCAM_PANEL_DEFAULT_GROUP", "1")

    # --- CORS ---------------------------------------------------------------
    # El panel sirve el frontend desde el mismo origen, por lo que CORS solo es
    # necesario si se integra desde otro dominio. "*" permite cualquier origen.
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.environ.get("NCAM_PANEL_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    )

    @property
    def version(self) -> str:
        """Versión del panel.

        Se toma, por orden: la variable ``NCAM_PANEL_VERSION``, el fichero
        ``VERSION`` que deja el paquete .deb junto al panel y, si no hay nada,
        la versión de desarrollo. Así `apt`, la API y el frontend coinciden.
        """
        from_file = os.environ.get("NCAM_PANEL_VERSION")
        if from_file:
            return from_file
        try:
            version_file = Path(__file__).resolve().parents[2] / "VERSION"
            value = version_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
        return "2.0.0"


settings = Settings()
