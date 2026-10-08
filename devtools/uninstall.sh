#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: desinstalador del daemon y del panel
#
#   sudo sh uninstall.sh                  # quita los programas, conserva config y datos
#   sudo sh uninstall.sh --purge           # borra también configuración, datos y logs
#   sudo sh uninstall.sh --daemon-only     # solo el daemon NCam
#   sudo sh uninstall.sh --panel-only      # solo NCPanel
#   sh uninstall.sh --dry-run              # muestra lo que haría (sin root, sin tocar nada)
#
# Detecta instalaciones por paquetes .deb (ncam-ng, ncam-ng-panel) y desde el
# código (/usr/local/bin/ncam, unidades de systemd manuales):
#   * detiene y deshabilita los servicios ncam y ncam-panel
#   * quita los paquetes con apt (remove) o los binarios/unidades manuales
#   * con --purge borra además /etc/ncam, /usr/local/etc/ncam.*,
#     /var/lib/ncam-ng-panel, /var/log/ncam y el usuario ncam-panel
#
# Sin --purge no se pierde nada irrecuperable: la configuración del daemon, la
# base de datos del panel y el .env se conservan, y al final se listan.
#
# En un clon del repositorio este mismo script está en devtools/uninstall.sh.
# ---------------------------------------------------------------------------
set -e

ONLY=""
PURGE=0
ASSUME_YES=0
DRY_RUN=0

# Para poder probarlo sin ser root, todas las rutas del sistema se prefijan
# con $ROOT (vacío en un uso real); ver devtools/run-install-tests.sh.
ROOT="${NCAM_UNINSTALL_ROOT:-}"
P_BIN_NCAM="$ROOT/usr/local/bin/ncam"
P_BIN_DEBUG="$ROOT/usr/local/bin/ncam.debug"
P_SRC_ETC="$ROOT/usr/local/etc"
P_UNIT_DIR="$ROOT/etc/systemd/system"
P_LIB_UNIT_DIR="$ROOT/lib/systemd/system"
P_ETC_NCAM="$ROOT/etc/ncam"
P_LOG_NCAM="$ROOT/var/log/ncam"
P_DATA_PANEL="$ROOT/var/lib/ncam-ng-panel"
P_OPT_PANEL="$ROOT/opt/ncam-ng-panel"

usage() {
	awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

self_path() {   # ruta absoluta de este script (para poder re-ejecutarlo con sudo)
	case "$0" in
		*/*) printf '%s' "$0" ;;
		*) command -v -- "$0" 2>/dev/null || printf '%s/%s' "$(pwd)" "$0" ;;
	esac
}

# ---------------------------------------------------------------------------
# 0. validación de las opciones (ANTES de pedir sudo, como el instalador)
# ---------------------------------------------------------------------------
validate_args() {
	while [ $# -gt 0 ]; do
		case "$1" in
			--daemon-only|--panel-only|--purge|--dry-run|-y|--yes|-h|--help)
				shift ;;
			*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
		esac
	done
}
validate_args "$@"

NEED_ROOT=1
for arg in "$@"; do
	case "$arg" in
		--dry-run|-h|--help) NEED_ROOT=0 ;;
	esac
done

# Si este script viene dentro del paquete que va a borrar (/usr/bin), se copia
# a un temporal y se re-ejecuta desde ahí: si no, apt lo borraría a mitad de
# la desinstalación y el script moriría a medias.
if [ -z "${NCAM_NG_UNINSTALL_REEXEC:-}" ]; then
	case "$(self_path)" in
		/usr/bin/*|/opt/*)
			tmp_copy="$(mktemp /tmp/ncam-ng-uninstall.XXXXXX)" || die "no se pudo crear un temporal"
			cp -- "$(self_path)" "$tmp_copy"
			chmod +x "$tmp_copy"
			NCAM_NG_UNINSTALL_REEXEC=1 exec sh "$tmp_copy" "$@"
			;;
	esac
fi

if [ "$NEED_ROOT" = "1" ] && [ "$(id -u)" != "0" ]; then
	if command -v sudo >/dev/null 2>&1; then
		say "==> se necesitan permisos de root; reintentando con sudo"
		if sudo -- sh "$(self_path)" "$@"; then
			exit 0
		fi
		die "no se pudo completar con sudo; ejecútalo como root:  sudo sh $(self_path)"
	else
		die "ejecuta este desinstalador como root:  sudo sh $(self_path)"
	fi
fi

while [ $# -gt 0 ]; do
	case "$1" in
		--daemon-only) ONLY="daemon"; shift ;;
		--panel-only)  ONLY="panel"; shift ;;
		--purge)       PURGE=1; shift ;;
		--dry-run)     DRY_RUN=1; shift ;;
		-y|--yes)      ASSUME_YES=1; shift ;;
		-h|--help)     usage; exit 0 ;;
		*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
	esac
done

want_daemon() { [ "$ONLY" != "panel" ]; }
want_panel() { [ "$ONLY" != "daemon" ]; }

# ---------------------------------------------------------------------------
# 1. detección de lo instalado
# ---------------------------------------------------------------------------
deb_installed() {   # deb_installed <paquete> -> 0 si está instalado
	dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "ok installed"
}

DEB_DAEMON=0; DEB_PANEL=0
deb_installed ncam-ng && DEB_DAEMON=1
deb_installed ncam-ng-panel && DEB_PANEL=1

SRC_BIN=""; [ -x "$P_BIN_NCAM" ] && SRC_BIN="$P_BIN_NCAM"
SRC_ETC=""; [ -d "$P_SRC_ETC" ] && [ -n "$(ls "$P_SRC_ETC"/ncam.* 2>/dev/null)" ] && SRC_ETC="$P_SRC_ETC"
UNIT_DAEMON=""; [ -f "$P_UNIT_DIR/ncam.service" ] && UNIT_DAEMON="$P_UNIT_DIR/ncam.service"
UNIT_PANEL=""; [ -f "$P_UNIT_DIR/ncam-panel.service" ] && UNIT_PANEL="$P_UNIT_DIR/ncam-panel.service"
DEB_UNIT_DAEMON=""; [ -f "$P_LIB_UNIT_DIR/ncam.service" ] && DEB_UNIT_DAEMON="$P_LIB_UNIT_DIR/ncam.service"
DEB_UNIT_PANEL=""; [ -f "$P_LIB_UNIT_DIR/ncam-panel.service" ] && DEB_UNIT_PANEL="$P_LIB_UNIT_DIR/ncam-panel.service"
HAS_SYSTEMD=0; command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] && HAS_SYSTEMD=1

if want_daemon && [ "$DEB_DAEMON" = "0" ] && [ -z "$SRC_BIN" ] && [ -z "$UNIT_DAEMON" ] && [ -z "$DEB_UNIT_DAEMON" ]; then
	HAVE_DAEMON=0
else
	HAVE_DAEMON=1
fi
if want_panel && [ "$DEB_PANEL" = "0" ] && [ -z "$UNIT_PANEL" ] && [ -z "$DEB_UNIT_PANEL" ] \
		&& [ ! -d "$P_OPT_PANEL" ] && [ ! -d "$P_DATA_PANEL" ]; then
	HAVE_PANEL=0
else
	HAVE_PANEL=1
fi
want_daemon || HAVE_DAEMON=0
want_panel || HAVE_PANEL=0

if [ "$HAVE_DAEMON" = "0" ] && [ "$HAVE_PANEL" = "0" ]; then
	say "No hay nada de NCam-NG instalado (ni daemon ni panel)."
	exit 0
fi

# ---------------------------------------------------------------------------
# 2. plan
# ---------------------------------------------------------------------------
plan="Se va a desinstalar:"
[ "$HAVE_DAEMON" = "1" ] && plan="$plan
  - daemon NCam      (paquete .deb: $([ "$DEB_DAEMON" = "1" ] && echo sí || echo no); desde código: $([ -n "$SRC_BIN$UNIT_DAEMON" ] && echo sí || echo no))"
[ "$HAVE_PANEL" = "1" ] && plan="$plan
  - panel NCPanel    (paquete .deb: $([ "$DEB_PANEL" = "1" ] && echo sí || echo no); desde código: $([ -n "$UNIT_PANEL" ] || [ -d "$P_OPT_PANEL" ] && echo sí || echo no))"
if [ "$PURGE" = "1" ]; then
	plan="$plan
  - BORRADO TOTAL (--purge): configuración, base de datos, logs y usuario ncam-panel"
else
	plan="$plan
  - se CONSERVAN la configuración y los datos (usa --purge para borrarlos también)"
fi
say "$plan"

if [ "$DRY_RUN" = "1" ]; then
	say ""
	say "(--dry-run: no se ha tocado nada)"
	exit 0
fi

if [ "$ASSUME_YES" != "1" ]; then
	if [ ! -t 0 ]; then
		die "sin terminal interactiva; confirma con --yes o ejecútalo a mano"
	fi
	printf '¿Desinstalar? [s/N] '
	read -r answer
	case "$answer" in
		[sSyY]*) ;;
		*) say "Cancelado, no se ha tocado nada."; exit 0 ;;
	esac
fi

run() {   # run <descripción> <comando...>: lo muestra y lo ejecuta (ignora fallos sueltos)
	say "==> $1"
	shift
	"$@" 2>&1 | sed 's/^/    /' || true
}

# ---------------------------------------------------------------------------
# 3. parar y deshabilitar servicios
# ---------------------------------------------------------------------------
if [ "$HAS_SYSTEMD" = "1" ]; then
	[ "$HAVE_DAEMON" = "1" ] && run "deteniendo ncam" systemctl stop ncam.service
	[ "$HAVE_PANEL" = "1" ] && run "deteniendo ncam-panel" systemctl stop ncam-panel.service
	[ "$HAVE_DAEMON" = "1" ] && run "deshabilitando ncam" systemctl disable ncam.service
	[ "$HAVE_PANEL" = "1" ] && run "deshabilitando ncam-panel" systemctl disable ncam-panel.service
else
	say "==> sin systemd: no hay servicios que parar"
fi

# ---------------------------------------------------------------------------
# 4. paquetes .deb
# ---------------------------------------------------------------------------
APT_MARK="remove"   # remove conserva config y datos; purge lo borra todo
[ "$PURGE" = "1" ] && APT_MARK="purge"
PKGS=""
[ "$HAVE_DAEMON" = "1" ] && [ "$DEB_DAEMON" = "1" ] && PKGS="$PKGS ncam-ng"
[ "$HAVE_PANEL" = "1" ] && [ "$DEB_PANEL" = "1" ] && PKGS="$PKGS ncam-ng-panel"
if [ -n "$PKGS" ]; then
	# shellcheck disable=SC2086
	run "apt $APT_MARK$PKGS" env DEBIAN_FRONTEND=noninteractive apt-get -y "$APT_MARK" $PKGS
fi

# ---------------------------------------------------------------------------
# 5. restos de instalaciones desde el código
# ---------------------------------------------------------------------------
if [ "$HAVE_DAEMON" = "1" ] && [ -n "$SRC_BIN" ]; then
	run "quitando $SRC_BIN" rm -f "$SRC_BIN"
	[ -f "$P_BIN_DEBUG" ] && run "quitando $P_BIN_DEBUG" rm -f "$P_BIN_DEBUG"
fi
if [ "$HAVE_DAEMON" = "1" ] && [ -n "$UNIT_DAEMON" ]; then
	run "quitando $UNIT_DAEMON" rm -f "$UNIT_DAEMON"
fi
if [ "$HAVE_PANEL" = "1" ] && [ -n "$UNIT_PANEL" ]; then
	run "quitando $UNIT_PANEL" rm -f "$UNIT_PANEL"
fi
if [ "$HAS_SYSTEMD" = "1" ] && { [ -n "$UNIT_DAEMON" ] || [ -n "$UNIT_PANEL" ]; }; then
	run "recargando systemd" systemctl daemon-reload
fi

# unidades del paquete que hubieran quedado huérfanas (paquete quitado a mano)
if [ "$HAVE_DAEMON" = "1" ] && [ "$DEB_DAEMON" = "0" ] && [ -n "$DEB_UNIT_DAEMON" ]; then
	if ! dpkg -S "$DEB_UNIT_DAEMON" >/dev/null 2>&1; then
		run "quitando unidad huérfana $DEB_UNIT_DAEMON" rm -f "$DEB_UNIT_DAEMON"
		[ "$HAS_SYSTEMD" = "1" ] && run "recargando systemd" systemctl daemon-reload
	fi
fi
if [ "$HAVE_PANEL" = "1" ] && [ "$DEB_PANEL" = "0" ] && [ -n "$DEB_UNIT_PANEL" ]; then
	if ! dpkg -S "$DEB_UNIT_PANEL" >/dev/null 2>&1; then
		run "quitando unidad huérfana $DEB_UNIT_PANEL" rm -f "$DEB_UNIT_PANEL"
		[ "$HAS_SYSTEMD" = "1" ] && run "recargando systemd" systemctl daemon-reload
	fi
fi

# ---------------------------------------------------------------------------
# 6. borrado total (--purge) o conservación
# ---------------------------------------------------------------------------
KEPT=""
if [ "$PURGE" = "1" ]; then
	[ "$HAVE_DAEMON" = "1" ] && [ -d "$P_ETC_NCAM" ] && run "borrando $P_ETC_NCAM" rm -rf "$P_ETC_NCAM"
	[ "$HAVE_DAEMON" = "1" ] && [ -d "$P_LOG_NCAM" ] && run "borrando $P_LOG_NCAM" rm -rf "$P_LOG_NCAM"
	if [ "$HAVE_DAEMON" = "1" ] && [ -n "$SRC_ETC" ]; then
		run "borrando $SRC_ETC/ncam.*" rm -f "$SRC_ETC"/ncam.conf "$SRC_ETC"/ncam.server \
			"$SRC_ETC"/ncam.user "$SRC_ETC"/ncam.services "$SRC_ETC"/ncam.conf.bak-*
	fi
	[ "$HAVE_PANEL" = "1" ] && [ -d "$P_DATA_PANEL" ] && run "borrando $P_DATA_PANEL" rm -rf "$P_DATA_PANEL"
	[ "$HAVE_PANEL" = "1" ] && [ -d "$P_OPT_PANEL" ] && run "borrando $P_OPT_PANEL" rm -rf "$P_OPT_PANEL"
	if [ "$HAVE_PANEL" = "1" ] && id ncam-panel >/dev/null 2>&1; then
		run "eliminando el usuario ncam-panel" userdel ncam-panel
	fi
else
	[ "$HAVE_DAEMON" = "1" ] && [ -d "$P_ETC_NCAM" ] && KEPT="$KEPT
    - $P_ETC_NCAM  (configuración del daemon)"
	[ "$HAVE_DAEMON" = "1" ] && [ -d "$P_LOG_NCAM" ] && KEPT="$KEPT
    - $P_LOG_NCAM  (logs del daemon)"
	[ "$HAVE_DAEMON" = "1" ] && [ -n "$SRC_ETC" ] && KEPT="$KEPT
    - $SRC_ETC/ncam.*  (configuración del daemon desde código)"
	[ "$HAVE_PANEL" = "1" ] && [ -d "$P_DATA_PANEL" ] && KEPT="$KEPT
    - $P_DATA_PANEL  (base de datos del panel)"
	[ "$HAVE_PANEL" = "1" ] && [ -f "$P_OPT_PANEL/.env" ] && KEPT="$KEPT
    - $P_OPT_PANEL/.env  (ajustes del panel)"
fi

# ---------------------------------------------------------------------------
# 7. verificación
# ---------------------------------------------------------------------------
say ""
say "== comprobación =="
LEFT=0
if [ "$HAVE_DAEMON" = "1" ]; then
	if command -v ncam >/dev/null 2>&1 || [ -x "$ROOT/usr/bin/ncam" ] || [ -x "$P_BIN_NCAM" ]; then
		say "  aviso: queda un binario ncam"; LEFT=1
	else
		say "  daemon: sin binarios ni servicio"
	fi
fi
if [ "$HAVE_PANEL" = "1" ]; then
	if [ -d "$P_OPT_PANEL" ] && [ "$(ls -A "$P_OPT_PANEL" 2>/dev/null)" ]; then
		say "  aviso: queda contenido en $P_OPT_PANEL"; LEFT=1
	elif [ "$PURGE" = "1" ] && [ -d "$P_DATA_PANEL" ]; then
		say "  aviso: queda $P_DATA_PANEL"; LEFT=1
	else
		say "  panel: sin servicio ni programa"
	fi
fi
if [ "$HAS_SYSTEMD" = "1" ]; then
	if [ "$HAVE_DAEMON" = "1" ] && systemctl is-active --quiet ncam.service 2>/dev/null; then
		say "  aviso: el servicio ncam sigue activo"; LEFT=1
	fi
	if [ "$HAVE_PANEL" = "1" ] && systemctl is-active --quiet ncam-panel.service 2>/dev/null; then
		say "  aviso: el servicio ncam-panel sigue activo"; LEFT=1
	fi
fi
if pgrep -x ncam >/dev/null 2>&1; then
	say "  aviso: hay un proceso 'ncam' en marcha (arrancado a mano); mátalo con:  pkill -x ncam"
	LEFT=1
fi

say ""
if [ -n "$KEPT" ]; then
	say "Se ha desinstalado. Se CONSERVA (por si reinstalas):$KEPT"
	case "$(self_path)" in
		/tmp/ncam-ng-uninstall.*)
			say "Para borrarlo también, descarga de nuevo el script y ejecútalo con --purge" ;;
		*)
			say "Para borrarlo también:  sudo sh $(self_path) --purge" ;;
	esac
else
	say "Se ha desinstalado NCam-NG del todo (--purge)."
fi
[ "$LEFT" = "0" ] || say "Revisa los avisos de arriba."
# si nos re-ejecutamos desde un temporal (veníamos en /usr/bin), se limpia
case "$(self_path)" in
	/tmp/ncam-ng-uninstall.*) rm -f -- "$(self_path)" ;;
esac
exit 0
