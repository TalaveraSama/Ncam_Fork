#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: comandos rápidos de consola para los servicios
#
#   ncam-ng-ctl status                  estado de los dos servicios y los puertos
#   ncam-ng-ctl restart [ncam|panel]    reinicia (por defecto los dos)
#   ncam-ng-ctl start|stop [ncam|panel] arranca / detiene
#   ncam-ng-ctl logs [ncam|panel] [-f]  últimas líneas del registro (journalctl)
#   ncam-ng-ctl config [ncam|panel]     edita la configuración con tu editor
#   ncam-ng-ctl passwd [usuario]        nueva contraseña del panel (una vez)
#   ncam-ng-ctl version                 versiones instaladas
#
# Atajos (instalados como enlaces a este mismo script):
#
#   restart-ncam          = ncam-ng-ctl restart ncam
#   restart-ncam-panel    = ncam-ng-ctl restart panel
#   ncam-ng-status        = ncam-ng-ctl status
#
# Opciones: --dry-run (solo muestra lo que haría), -n N / --lines N, -f / --follow
# ---------------------------------------------------------------------------
set -e

NCAM_SERVICE="ncam"
PANEL_SERVICE="ncam-panel"
NCAM_CONF="/etc/ncam/ncam.conf"
PANEL_DIR="/opt/ncam-ng-panel"
PANEL_ENV="$PANEL_DIR/.env"
PANEL_DB_DEFAULT="/var/lib/ncam-ng-panel/panel.db"

ACTION=""
TARGET="all"
DRY=0
FOLLOW=0
LINES=50
USERNAME=""

# Los argumentos se van consumiendo al analizarlos, así que se guarda una copia
# para poder re-ejecutar el script con sudo conservándolos.
ORIG_ARGS="$*"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
	awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

# ---------------------------------------------------------------------------
# argumentos (con los atajos según el nombre con el que se haya llamado)
# ---------------------------------------------------------------------------
case "$(basename "$0")" in
	restart-ncam)       set -- restart ncam "$@" ;;
	restart-ncam-panel) set -- restart panel "$@" ;;
	ncam-ng-status)     set -- status "$@" ;;
esac

validate_args() {
	# Se comprueban las opciones (lo que empieza por "-") antes de pedir sudo;
	# las palabras sueltas se validan después de re-ejecutar con sudo, porque
	# "passwd" admite además un nombre de usuario.
	while [ $# -gt 0 ]; do
		case "$1" in
			-n|--lines)
				case "${2:-}" in
					''|*[!0-9]*) echo "error: --lines necesita un número" >&2; exit 2 ;;
				esac
				shift 2 ;;
			-f|--follow|--dry-run|-h|--help|status|start|stop|restart|logs|config|passwd|version|help) shift ;;
			-*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
			*) shift ;;
		esac
	done
}
validate_args "$@"

while [ $# -gt 0 ]; do
	case "$1" in
		status|start|stop|restart|logs|config|passwd|version|help)
			if [ -z "$ACTION" ]; then
				ACTION="$1"
			elif [ "$ACTION" = "passwd" ]; then
				USERNAME="$1"     # ncam-ng-ctl passwd <usuario>
			else
				die "sobra el argumento '$1' (usa --help)"
			fi
			shift ;;
		ncam|daemon) TARGET="daemon"; shift ;;
		panel)       TARGET="panel"; shift ;;
		all|both)    TARGET="all"; shift ;;
		-f|--follow) FOLLOW=1; shift ;;
		-n|--lines)  LINES="$2"; shift 2 ;;
		--dry-run)   DRY=1; shift ;;
		-h|--help)   usage; exit 0 ;;
		-*)          die "opción no reconocida: $1 (usa --help)" ;;
		*)
			if [ "$ACTION" = "passwd" ] && [ -z "$USERNAME" ]; then
				USERNAME="$1"
			else
				die "argumento no reconocido: '$1' (usa --help)"
			fi
			shift ;;
	esac
done

if [ -z "$ACTION" ] || [ "$ACTION" = "help" ]; then
	usage
	exit 0
fi

# ---------------------------------------------------------------------------
# permisos (antes de tocar nada, y solo cuando hace falta)
# ---------------------------------------------------------------------------
NEED_ROOT=1
case "$ACTION" in
	status|version) NEED_ROOT=0 ;;
esac
[ "$DRY" = "1" ] && NEED_ROOT=0

if [ "$NEED_ROOT" = "1" ] && [ "$(id -u)" != "0" ]; then
	self_path() {
		case "$0" in
			*/*) printf '%s' "$0" ;;
			*) command -v -- "$0" 2>/dev/null || printf '%s/%s' "$(pwd)" "$0" ;;
		esac
	}
	if command -v sudo >/dev/null 2>&1; then
		say "==> se necesitan permisos de root; reintentando con sudo"
		if sudo -- sh "$(self_path)" $ORIG_ARGS; then
			exit 0
		fi
		die "no se pudo completar con sudo; ejecútalo como root:  sudo ncam-ng-ctl $ACTION"
	else
		die "ejecuta este comando como root:  sudo ncam-ng-ctl $ACTION"
	fi
fi

command -v systemctl >/dev/null 2>&1 || die "no encuentro systemctl (¿systemd instalado?)"

service_present() {
	# con --dry-run no se exige que las unidades existan: se muestra lo que haría
	[ "$DRY" = "1" ] && return 0
	[ -f "/usr/lib/systemd/system/$1.service" ] || [ -f "/etc/systemd/system/$1.service" ]
}

run() {   # respeta --dry-run
	if [ "$DRY" = "1" ]; then
		say "  [dry-run] $*"
		return 0
	fi
	"$@"
}

targets_for() {
	case "$1" in
		daemon) printf '%s' "$NCAM_SERVICE" ;;
		panel)  printf '%s' "$PANEL_SERVICE" ;;
		all)    printf '%s %s' "$NCAM_SERVICE" "$PANEL_SERVICE" ;;
	esac
}

panel_port() {
	if [ -r "$PANEL_ENV" ]; then
		p=$(sed -n 's/^NCAM_PANEL_PORT=[[:space:]]*//p' "$PANEL_ENV" | tail -n 1 | tr -d '"')
		[ -n "$p" ] && { printf '%s' "$p"; return; }
	fi
	printf '%s' 8080
}

webif_port() {
	if [ -r "$NCAM_CONF" ]; then
		p=$(sed -n 's/^[[:space:]]*httpport[[:space:]]*=[[:space:]]*//p' "$NCAM_CONF" | tail -n 1 | tr -d '[:space:]')
		[ -n "$p" ] && { printf '%s' "$p"; return; }
	fi
	printf '%s' 8181
}

http_code_retry() {   # http_code_retry <url> [<segundos>]
	url="$1"; secs="${2:-10}"; i=0; code=""
	while [ "$i" -lt "$secs" ]; do
		code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || true)
		if [ -n "$code" ] && [ "$code" != "000" ]; then
			printf '%s' "$code"
			return 0
		fi
		i=$((i + 1))
		sleep 1
	done
	printf '%s' "${code:-000}"
	return 1
}

body_retry() {   # body_retry <url> [<segundos>]  -> devuelve el cuerpo
	url="$1"; secs="${2:-10}"; i=0; out=""
	while [ "$i" -lt "$secs" ]; do
		out=$(curl -s --max-time 3 "$url" 2>/dev/null || true)
		if [ -n "$out" ]; then
			printf '%s' "$out"
			return 0
		fi
		i=$((i + 1))
		sleep 1
	done
	return 1
}

wait_active() {   # wait_active <servicio> <segundos>
	svc="$1"; secs="$2"; i=0
	while [ "$i" -lt "$secs" ]; do
		systemctl is-active --quiet "$svc" && return 0
		i=$((i + 1))
		sleep 1
	done
	return 1
}

# ---------------------------------------------------------------------------
# acciones
# ---------------------------------------------------------------------------
do_start_stop_restart() {
	what="$1"      # start | stop | restart
	target_svc=""
	for svc in $(targets_for "$TARGET"); do
		if ! service_present "$svc"; then
			if [ "$TARGET" = "all" ]; then
				say "  $svc: no está instalado ($( [ "$svc" = "$PANEL_SERVICE" ] && echo 'paquete ncam-ng-panel' || echo 'paquete ncam-ng' ))"
				continue
			fi
			die "$svc no está instalado"
		fi
		target_svc="$svc"

		case "$what" in
			start)   say "==> arrancando $svc";   run systemctl start "$svc" ;;
			stop)    say "==> deteniendo $svc";   run systemctl stop "$svc" ;;
			restart) say "==> reiniciando $svc";  run systemctl restart "$svc" ;;
		esac

		if [ "$DRY" = "0" ] && [ "$what" != "stop" ]; then
			if wait_active "$svc" 15; then
				say "    ok: $svc activo ($(systemctl show -p ActiveEnterTimestamp --value "$svc" 2>/dev/null || true))"
			else
				say "    AVISO: $svc no está activo; revisa los últimos errores:"
				say "    ---"
				journalctl -u "$svc" -n 15 --no-pager 2>/dev/null | sed 's/^/    /' || true
				say "    ---"
				return 1
			fi
		fi
	done

	# comprobación amable después de arrancar o reiniciar
	if [ "$DRY" = "0" ] && [ "$what" != "stop" ] && service_present "$PANEL_SERVICE"; then
		pp="$(panel_port)"
		code=$(http_code_retry "http://127.0.0.1:$pp/api/v1/health" 15 || true)
		if [ "$code" = "200" ]; then
			say "    panel:  http://TU_IP:$pp  (health ok)"
		else
			say "    panel:  sin respuesta en /api/v1/health (HTTP ${code:-000})"
		fi
	fi
	if [ "$DRY" = "0" ] && [ "$what" != "stop" ] && service_present "$NCAM_SERVICE"; then
		wp="$(webif_port)"
		code=$(http_code_retry "http://127.0.0.1:$wp/" 10 || true)
		case "$code" in
			200) say "    WebIf:  http://TU_IP:$wp  (ok)" ;;
			401) say "    WebIf:  http://TU_IP:$wp  (responde; pide usuario y contraseña, es normal)" ;;
			*)   say "    WebIf:  sin respuesta en el puerto $wp (HTTP ${code:-000})" ;;
		esac
	fi
	return 0
}

do_status() {
	say "Servicios de NCam-NG"
	say "===================="
	for svc in $(targets_for "$TARGET"); do
		if ! service_present "$svc"; then
			say "  $svc: no instalado"
			continue
		fi
		state="$(systemctl is-active "$svc" 2>/dev/null || true)"
		enabled="$(systemctl is-enabled "$svc" 2>/dev/null || true)"
		since="$(systemctl show -p ActiveEnterTimestamp --value "$svc" 2>/dev/null || true)"
		say "  $svc: ${state:-?} (${enabled:-?})${since:+  desde $since}"
	done

	say ""
	say "Puertos"
	say "======="
	pp="$(panel_port)"; wp="$(webif_port)"
	for pair in "panel:$pp" "WebIf:$wp"; do
		label="${pair%%:*}"; port="${pair##*:}"
		if ss -ltn 2>/dev/null | grep -q ":$port "; then
			say "  $label: escuchando en $port"
		else
			say "  $label: nada escuchando en $port"
		fi
	done

	say ""
	say "Comprobación HTTP"
	say "================="
	if service_present "$PANEL_SERVICE"; then
		health="$(body_retry "http://127.0.0.1:$pp/api/v1/health" 5 || true)"
		if [ -n "$health" ]; then
			say "  panel:  $health"
		else
			say "  panel:  sin respuesta en http://127.0.0.1:$pp/api/v1/health"
		fi
	fi
	if service_present "$NCAM_SERVICE"; then
		code="$(http_code_retry "http://127.0.0.1:$wp/cacheengine.html" 5 || true)"
		case "$code" in
			200) say "  WebIf:  ok (http://127.0.0.1:$wp/cacheengine.html)" ;;
			401) say "  WebIf:  pide usuario y contraseña (lo normal; usuario admin)" ;;
			*)   say "  WebIf:  sin respuesta (HTTP ${code:-000})" ;;
		esac
	fi

	say ""
	say "Rutas"
	say "====="
	say "  configuración del daemon: $NCAM_CONF"
	say "  configuración del panel:  $PANEL_ENV"
	say "  registros:                ncam-ng-ctl logs [ncam|panel] -f"
	return 0
}

do_logs() {
	for svc in $(targets_for "$TARGET"); do
		if ! service_present "$svc"; then
			say "  $svc: no instalado"
			continue
		fi
		say "==> registro de $svc (últimas $LINES líneas$([ "$FOLLOW" = 1 ] && echo ", siguiendo en vivo"))"
		if [ "$FOLLOW" = "1" ]; then
			run journalctl -u "$svc" -n "$LINES" -f
		else
			run journalctl -u "$svc" -n "$LINES" --no-pager
		fi
	done
	return 0
}

do_config() {
	case "$TARGET" in
		daemon) file="$NCAM_CONF" ;;
		panel)  file="$PANEL_ENV" ;;
		all)
			die "indica cuál quieres editar:  ncam-ng-ctl config ncam  |  ncam-ng-ctl config panel"
			;;
	esac
	[ -f "$file" ] || die "no existe $file (¿está instalado el paquete correspondiente?)"

	# EDITOR manda; si no, se usa el primer editor disponible
	editor=""
	if [ -n "$EDITOR" ]; then
		command -v "$EDITOR" >/dev/null 2>&1 && editor="$EDITOR"
	else
		for candidate in nano vi vim editor mcedit; do
			if command -v "$candidate" >/dev/null 2>&1; then
				editor="$candidate"
				break
			fi
		done
	fi

	if [ "$DRY" = "1" ]; then
		say "  [dry-run] ${editor:-EDITOR} $file"
		return 0
	fi
	[ -n "$editor" ] || die "no encuentro ningún editor (instala nano o define EDITOR=...)"
	say "==> abriendo $file con $editor"
	"$editor" "$file"
	say ""
	say "Para aplicar los cambios:  ncam-ng-ctl restart$([ "$TARGET" = "panel" ] && echo ' panel' || echo ' ncam')"
	return 0
}

do_passwd() {
	venv="$PANEL_DIR/.venv/bin/python"
	if [ "$DRY" = "0" ]; then
		[ -x "$venv" ] || die "no encuentro el entorno del panel ($venv); ¿falta el paquete ncam-ng-panel?"
	fi
	user="${USERNAME:-admin}"
	db="${NCAM_PANEL_DB:-$PANEL_DB_DEFAULT}"
	[ -f "$db" ] || say "aviso: aún no existe $db; se creará ahora"

	cmd_python=runuser
	command -v runuser >/dev/null 2>&1 || cmd_python=sudo
	if [ "$DRY" = "1" ]; then
		say "  [dry-run] PYTHONPATH=$PANEL_DIR/backend NCAM_PANEL_DB=$db $venv -m app.seed --username $user --reset-password"
		return 0
	fi
	say "==> generando una contraseña nueva para '$user'"
	$cmd_python -u "$PANEL_SERVICE" -- env PYTHONPATH="$PANEL_DIR/backend" NCAM_PANEL_DB="$db" \
		"$venv" -m app.seed --username "$user" --reset-password
	return 0
}

do_version() {
	say "ncam-ng-ctl (herramienta de gestión de NCam-NG)"
	say ""
	if command -v dpkg-query >/dev/null 2>&1; then
		dpkg-query -W -f='  ${Package} ${Version} (${Status})\n' ncam-ng ncam-ng-panel 2>/dev/null || true
	fi
	if [ -f "$PANEL_DIR/VERSION" ]; then
		say "  versión del panel instalado: $(cat "$PANEL_DIR/VERSION")"
	fi
	if [ -x /usr/bin/ncam ]; then
		say ""
		/usr/bin/ncam -V 2>/dev/null | sed -n '2,4p' | sed 's/^/  /' || true
	fi
	return 0
}

case "$ACTION" in
	status)  do_status ;;
	start)   do_start_stop_restart start ;;
	stop)    do_start_stop_restart stop ;;
	restart) do_start_stop_restart restart ;;
	logs)    do_logs ;;
	config)  do_config ;;
	passwd)  do_passwd ;;
	version) do_version ;;
	*)       usage; exit 2 ;;
esac
