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
#   ncam-ng-ctl admin                   cuentas del panel (usuario, rol, estado)
#   ncam-ng-ctl admin add USUARIO [ROL] [CLAVE] [EMAIL]
#                                       crea un administrador (por defecto
#                                       super_admin) o un revendedor; la clave
#                                       se genera y se muestra una vez
#   ncam-ng-ctl admin role USUARIO ROL  cambia el rol de una cuenta
#   ncam-ng-ctl admin del USUARIO       elimina una cuenta del panel
#   ncam-ng-ctl admin passwd USUARIO    nueva contraseña para esa cuenta
#
#   ncam-ng-ctl webif                   quién puede entrar al WebIf (IPs permitidas)
#   ncam-ng-ctl webif add IP|RANGO|DOMINIO [...]    permite ese acceso
#   ncam-ng-ctl webif del IP|RANGO|DOMINIO [...]    quita ese acceso
#   ncam-ng-ctl webif add any           permite cualquier IP (¡con cuidado!)
#
# Atajos (instalados como enlaces a este mismo script):
#
#   restart-ncam          = ncam-ng-ctl restart ncam
#   restart-ncam-panel    = ncam-ng-ctl restart panel
#   ncam-ng-status        = ncam-ng-ctl status
#
# Opciones: --dry-run (solo muestra lo que haría), -n N / --lines N, -f / --follow,
#           --no-restart (webif: cambia la configuración sin reiniciar el daemon)
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
WEBIF_OP=""
WEBIF_ITEMS=""
ADMIN_OP=""
ADMIN_ITEMS=""
NO_RESTART=0

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
			-f|--follow|--dry-run|--no-restart|-h|--help|status|start|stop|restart|logs|config|passwd|version|webif|admin|help) shift ;;
			-*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
			*) shift ;;
		esac
	done
}
validate_args "$@"

while [ $# -gt 0 ]; do
	case "$1" in
		status|start|stop|restart|logs|config|passwd|version|webif|admin|help)
			if [ -z "$ACTION" ]; then
				ACTION="$1"
			elif [ "$ACTION" = "admin" ] && [ -z "$ADMIN_OP" ] \
				&& { [ "$1" = "add" ] || [ "$1" = "del" ] || [ "$1" = "remove" ] \
					|| [ "$1" = "role" ] || [ "$1" = "passwd" ] || [ "$1" = "list" ]; }; then
				case "$1" in
					remove) ADMIN_OP="del" ;;
					*)      ADMIN_OP="$1" ;;
				esac
			elif [ "$ACTION" = "webif" ] && [ -z "$WEBIF_OP" ] \
				&& { [ "$1" = "add" ] || [ "$1" = "del" ] || [ "$1" = "remove" ] || [ "$1" = "list" ]; }; then
				case "$1" in
					remove) WEBIF_OP="del" ;;
					*)      WEBIF_OP="$1" ;;
				esac
			elif [ "$ACTION" = "passwd" ]; then
				USERNAME="$1"     # ncam-ng-ctl passwd <usuario>
			elif [ "$ACTION" = "admin" ]; then
				ADMIN_ITEMS="$ADMIN_ITEMS $1"   # el usuario puede llamarse "admin", "version"...
			elif [ "$ACTION" = "webif" ]; then
				WEBIF_ITEMS="$WEBIF_ITEMS $1"
			else
				die "sobra el argumento '$1' (usa --help)"
			fi
			shift ;;
		ncam|daemon) TARGET="daemon"; shift ;;
		panel)       TARGET="panel"; shift ;;
		all|both)    TARGET="all"; shift ;;
		-f|--follow)    FOLLOW=1; shift ;;
		-n|--lines)     LINES="$2"; shift 2 ;;
		--dry-run)      DRY=1; shift ;;
		--no-restart)   NO_RESTART=1; shift ;;
		-h|--help)   usage; exit 0 ;;
		-*)          die "opción no reconocida: $1 (usa --help)" ;;
		*)
			if [ "$ACTION" = "admin" ] && [ -z "$ADMIN_OP" ] \
				&& { [ "$1" = "add" ] || [ "$1" = "del" ] || [ "$1" = "remove" ] \
					|| [ "$1" = "role" ] || [ "$1" = "passwd" ] || [ "$1" = "list" ]; }; then
				case "$1" in
					remove) ADMIN_OP="del" ;;
					*)      ADMIN_OP="$1" ;;
				esac
			elif [ "$ACTION" = "admin" ]; then
				ADMIN_ITEMS="$ADMIN_ITEMS $1"    # ncam-ng-ctl admin add USUARIO [rol] [clave] [email]
			elif [ "$ACTION" = "passwd" ] && [ -z "$USERNAME" ]; then
				USERNAME="$1"
			elif [ "$ACTION" = "webif" ] && [ -z "$WEBIF_OP" ] \
				&& { [ "$1" = "add" ] || [ "$1" = "del" ] || [ "$1" = "remove" ] || [ "$1" = "list" ]; }; then
				case "$1" in
					remove) WEBIF_OP="del" ;;
					*)      WEBIF_OP="$1" ;;
				esac
			elif [ "$ACTION" = "webif" ]; then
				WEBIF_ITEMS="$WEBIF_ITEMS $1"   # ncam-ng-ctl webif add <ip|rango|dominio> ...
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
	webif) [ -z "$WEBIF_OP" ] || [ "$WEBIF_OP" = "list" ] && NEED_ROOT=0 ;;
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
# WebIf: quién puede entrar (httpallowed / httpdyndns de ncam.conf)
# ---------------------------------------------------------------------------
conf_value() {   # conf_value <clave>  -> valor de la última línea con esa clave
	[ -r "$NCAM_CONF" ] || return 0
	sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$NCAM_CONF" | tail -n 1 \
		| sed 's/[[:space:]]*$//'
}

is_ipv4() {   # is_ipv4 <texto>  -> 0 si es una IPv4 correcta
	case "$1" in
		*[!0-9.]*|'') return 1 ;;
	esac
	old_ifs=$IFS; IFS=.
	# shellcheck disable=SC2086
	set -- $1
	IFS=$old_ifs
	[ $# -eq 4 ] || return 1
	for octet in "$@"; do
		case "$octet" in
			''|*[!0-9]*) return 1 ;;
		esac
		[ "$octet" -le 255 ] || return 1
	done
	return 0
}

is_iprange() {   # is_iprange <inicio-fin>
	case "$1" in
		*-*) ;;
		*) return 1 ;;
	esac
	range_start=${1%%-*}
	range_end=${1#*-}
	case "$range_end" in
		*-*) return 1 ;;
	esac
	is_ipv4 "$range_start" && is_ipv4 "$range_end"
}

is_hostname() {   # is_hostname <texto>  (para httpdyndns)
	case "$1" in
		*[!A-Za-z0-9.-]*|'') return 1 ;;
	esac
	case "$1" in
		*.*) return 0 ;;
		*) return 1 ;;
	esac
}

looks_like_ip() {   # looks_like_ip <texto>  (para no confundir 999.1.1.1 con un dominio)
	case "$1" in
		*[!0-9.-]*|'') return 1 ;;
	esac
	return 0
}

is_private_ipv4() {
	case "$1" in
		10.*|127.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|169.254.*) return 0 ;;
		*) return 1 ;;
	esac
}

split_list() {   # split_list <a,b,c>  -> una entrada por línea
	printf '%s' "$1" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' || true
}

add_or_remove() {   # add_or_remove <lista> <entrada> <add|del>
	list="$1"; item="$2"; op="$3"
	result=""; found=0
	while IFS= read -r entry; do
		[ -n "$entry" ] || continue
		if [ "$(printf '%s' "$entry" | tr 'A-Z' 'a-z')" = "$(printf '%s' "$item" | tr 'A-Z' 'a-z')" ]; then
			found=1
			[ "$op" = "del" ] && continue
		fi
		result="${result:+$result,}$entry"
	done <<EOF
$(split_list "$list")
EOF
	if [ "$op" = "add" ] && [ "$found" = "0" ]; then
		result="${result:+$result,}$item"
	fi
	printf '%s' "$result"
}

conf_set() {   # conf_set <clave> <valor>  (mantiene el resto del fichero intacto)
	key="$1"; value="$2"
	tmp="$NCAM_CONF.ncam-ng-ctl.$$"
	awk -v key="$key" -v value="$value" '
		{ line[NR] = $0 }
		END {
			done = 0
			for (i = 1; i <= NR; i++) {
				low = tolower(line[i])
				if (!done && low ~ ("^[ \t]*" key "[ \t]*=")) {
					match(line[i], "^[ \t]*"); indent = substr(line[i], 1, RLENGTH)
					print indent key " = " value
					done = 1
					continue
				}
				print line[i]
			}
			if (!done) { print "__NCAM_NG_INSERT__" key " = " value }
		}' "$NCAM_CONF" > "$tmp"

	if grep -q '^__NCAM_NG_INSERT__' "$tmp"; then
		# la clave no existía: se mete detrás de la cabecera [webif]
		grep -v '^__NCAM_NG_INSERT__' "$tmp" > "$tmp.body"
		awk -v key="$key" -v value="$value" '
			{ print }
			/^[ \t]*\[webif\][ \t]*$/ { print key " = " value; inserted = 1 }
			END { if (!inserted) printf "\n[webif]\n%s = %s\n", key, value }
		' "$tmp.body" > "$tmp"
		rm -f "$tmp.body"
	fi

	if [ "$DRY" = "1" ]; then
		say "  [dry-run] dejaría en $NCAM_CONF:  $key = $value"
		rm -f "$tmp"
		return 0
	fi
	cp -p "$NCAM_CONF" "$NCAM_CONF.bak-$(date +%Y%m%d-%H%M%S)"
	cat "$tmp" > "$NCAM_CONF"
	rm -f "$tmp"
}

do_webif_show() {
	port="$(webif_port)"
	allowed="$(conf_value httpallowed)"
	dyndns="$(conf_value httpdyndns)"

	say "WebIf de NCam (puerto $port)"
	say "==========================="
	if [ ! -r "$NCAM_CONF" ]; then
		say "  no encuentro $NCAM_CONF"
		return 0
	fi
	say "  archivo:   $NCAM_CONF"
	say "  usuario:   $(conf_value httpuser)"
	if [ -n "$dyndns" ]; then
		say "  dominios:  $dyndns   (httpdyndns: se resuelven solos)"
	fi
	say ""
	say "  Acceso permitido (httpallowed):"
	if [ -z "$allowed" ]; then
		say "    (vacío) -> NADIE puede entrar al WebIf"
		say "    añade tu IP con:  ncam-ng-ctl webif add TU_IP"
	else
		split_list "$allowed" | while IFS= read -r entry; do
			label=""
			case "$entry" in
				any|0.0.0.0-255.255.255.255) label="CUALQUIER IP (abierto a internet)" ;;
				*)
					if is_ipv4 "$entry"; then
						if is_private_ipv4 "$entry"; then label="red local"; else label="IP pública / VPN"; fi
					elif is_iprange "$entry"; then
						first=${entry%%-*}
						if is_private_ipv4 "$first"; then label="red local (rango)"; else label="rango público / VPN"; fi
					fi
					;;
			esac
			say "    - $entry${label:+   [$label]}"
		done
	fi

	say ""
	say "  Entrar desde otra máquina:  http://<esa-ip-o-dominio>:$port"
	if [ "$(id -u)" = "0" ] && command -v ufw >/dev/null 2>&1; then
		case "$(ufw status 2>/dev/null | head -n 1 || true)" in
			*activo*|*active*)
				say "  cortafuegos ufw: activo"
				if ufw status 2>/dev/null | grep -qE "^$port(/tcp)?\b"; then
					ufw status 2>/dev/null | grep -E "^$port(/tcp)?\b" | sed 's/^/    /'
				else
					say "    (sin ninguna regla para el puerto $port: ábrelo si entras desde fuera)"
				fi
				;;
		esac
	fi
	say ""
	say "  La IP permitida es la de QUIEN se conecta, tal como la ve este servidor:"
	say "  si navegas desde tu PC por la VPN, hay que permitir la IP de tu PC."
	return 0
}

do_webif_edit() {
	[ -r "$NCAM_CONF" ] || die "no encuentro $NCAM_CONF (¿está instalado el paquete ncam-ng?)"
	op="$1"; shift
	[ $# -gt 0 ] || die "indica qué IP, rango o dominio:  ncam-ng-ctl webif $op 191.103.121.243"

	allowed="$(conf_value httpallowed)"
	dyndns="$(conf_value httpdyndns)"
	dyndns_touched=0
	if [ -z "$allowed" ] && [ "$op" = "add" ]; then
		allowed="127.0.0.1"
		say "aviso: no había ninguna línea httpallowed; se parte de 127.0.0.1 (acceso local)"
	fi

	for item in "$@"; do
		case "$item" in
			any|todas|all)
				item="0.0.0.0-255.255.255.255"
				say "AVISO: 'any' deja el WebIf abierto a CUALQUIER IP de internet"
				;;
		esac

		if is_ipv4 "$item" || is_iprange "$item"; then
			new_list="$(add_or_remove "$allowed" "$item" "$op")"
			if [ "$new_list" = "$allowed" ]; then
				if [ "$op" = "add" ]; then say "  $item: ya estaba permitido"; else say "  $item: no estaba en la lista"; fi
			elif [ "$op" = "add" ]; then
				say "  $item: se permite el acceso"
			else
				say "  $item: se quita el acceso"
			fi
			allowed="$new_list"
		elif is_hostname "$item" && ! looks_like_ip "$item" && [ "$op" = "add" ]; then
			new_list="$(add_or_remove "$dyndns" "$item" add)"
			count="$(split_list "$new_list" | grep -c . || true)"
			if [ "$count" -gt 3 ]; then
				new_list="$(split_list "$new_list" | head -n 3 | paste -sd, -)"
				say "  $item: se añade a httpdyndns (máx. 3 dominios; la lista se recorta)"
			else
				say "  $item: se añade a httpdyndns (se resuelve solo al conectar)"
			fi
			dyndns="$new_list"
			dyndns_touched=1
		else
			die "'$item' no es una IP válida (191.103.121.243), un rango (10.0.0.0-10.0.0.255) ni un dominio (micasa.dyndns.org)"
		fi
	done

	conf_set httpallowed "$allowed"
	if [ "$dyndns_touched" = "1" ] || { [ "$op" = "del" ] && [ -n "$dyndns" ]; }; then
		conf_set httpdyndns "$dyndns"
	fi

	[ "$DRY" = "1" ] && return 0
	say ""
	say "  acceso permitido: $allowed"
	if [ -n "$dyndns" ]; then
		say "  dominios:         $dyndns"
	fi
	say "  copia de seguridad: ${NCAM_CONF}.bak-*"

	if [ "$NO_RESTART" = "1" ]; then
		say ""
		say "  (sin reiniciar todavía: aplícalo con  ncam-ng-ctl restart ncam)"
		return 0
	fi
	say ""
	say "==> reiniciando $NCAM_SERVICE para aplicar el cambio"
	run systemctl restart "$NCAM_SERVICE"
	if wait_active "$NCAM_SERVICE" 15; then
		port="$(webif_port)"
		code="$(http_code_retry "http://127.0.0.1:$port/" 10 || true)"
		say "    ok: $NCAM_SERVICE activo (WebIf HTTP ${code:-000})"
		for entry in $(split_list "$allowed"); do
			case "$entry" in
				*[!0-9.]*) continue ;;   # rangos y dominios: no se listan aquí
			esac
			if is_private_ipv4 "$entry"; then
				continue
			fi
			say "    desde ese equipo:  http://$entry:$port"
		done
	else
		say "    AVISO: $NCAM_SERVICE no arrancó; últimos errores:"
		journalctl -u "$NCAM_SERVICE" -n 15 --no-pager 2>/dev/null | sed 's/^/    /' || true
		return 1
	fi
	return 0
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
	allowed="$(conf_value httpallowed)"
	dyndns="$(conf_value httpdyndns)"
	if [ -z "$allowed" ]; then
		say "  acceso al WebIf:          (vacío: no entra nadie; ncam-ng-ctl webif add TU_IP)"
	else
		if [ "${#allowed}" -gt 78 ]; then
			allowed="$(printf '%s' "$allowed" | cut -c1-75)..."
		fi
		say "  acceso al WebIf:          $allowed"
		[ -n "$dyndns" ] && say "  dominios (httpdyndns):    $dyndns"
		say "                            (ncam-ng-ctl webif para verlo o añadir tu IP)"
	fi
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

panel_seed() {   # ejecuta `app.seed` como el usuario del panel, con su base de datos
	venv="$PANEL_DIR/.venv/bin/python"
	db="${NCAM_PANEL_DB:-$PANEL_DB_DEFAULT}"
	if [ "$DRY" = "1" ]; then
		say "  [dry-run] PYTHONPATH=$PANEL_DIR/backend NCAM_PANEL_DB=$db $venv -m app.seed $*"
		return 0
	fi
	[ -x "$venv" ] || die "no encuentro el entorno del panel ($venv); ¿falta el paquete ncam-ng-panel?"
	[ -f "$db" ] || say "aviso: aún no existe $db; se creará ahora"
	cmd_python=runuser
	command -v runuser >/dev/null 2>&1 || cmd_python=sudo
	$cmd_python -u "$PANEL_SERVICE" -- env PYTHONPATH="$PANEL_DIR/backend" NCAM_PANEL_DB="$db" \
		"$venv" -m app.seed "$@"
}

do_passwd() {
	user="${USERNAME:-admin}"
	if [ "$DRY" = "1" ]; then
		panel_seed --username "$user" --reset-password
		return 0
	fi
	say "==> generando una contraseña nueva para '$user'"
	panel_seed --username "$user" --reset-password
	return 0
}

do_admin() {
	op="$ADMIN_OP"
	if [ -z "$op" ]; then
		# `ncam-ng-ctl admin` sin nada lista las cuentas, pero si viene un
		# argumento suelto ("admin borrar cosas") es un error de uso.
		if [ -n "$ADMIN_ITEMS" ]; then
			die "uso: ncam-ng-ctl admin [add|role|del|passwd] ...  (usa --help)"
		fi
		op="list"
	fi

	case "$op" in
		list)
			say "==> cuentas del panel (super admin, revendedores y usuarios)"
			panel_seed --list
			;;

		add)
			# ncam-ng-ctl admin add USUARIO [super_admin|reseller|user] [CLAVE] [EMAIL]
			items="$ADMIN_ITEMS"
			set -- $items
			[ $# -ge 1 ] || die "uso: ncam-ng-ctl admin add USUARIO [super_admin|reseller|user] [CLAVE] [EMAIL]"
			auser="$1"; shift
			arole="super_admin"
			apass=""
			amail=""
			for item in "$@"; do
				case "$item" in
					super_admin|superadmin|admin|super) arole="super_admin" ;;
					reseller|revendedor)               arole="reseller" ;;
					user|usuario|cliente)              arole="user" ;;
					*@*)                               amail="$item" ;;
					*)                                 apass="$item" ;;
				esac
			done

			say "==> creando la cuenta '$auser' (rol: $arole)"
			if [ "$DRY" = "1" ]; then
				if [ -n "$apass" ]; then
					panel_seed --create --username "$auser" --role "$arole" --password "$apass" ${amail:+--email "$amail"}
				else
					panel_seed --create --username "$auser" --role "$arole" ${amail:+--email "$amail"}
				fi
				return 0
			fi
			if [ -n "$apass" ]; then
				panel_seed --create --username "$auser" --role "$arole" --password "$apass" ${amail:+--email "$amail"}
			else
				panel_seed --create --username "$auser" --role "$arole" ${amail:+--email "$amail"}
			fi
			say ""
			pp="$(panel_port)"
			[ "$arole" = "super_admin" ] && say "  Ya puede entrar en http://<tu-ip>:$pp con ese usuario y contraseña."
			say "  Ver las cuentas:      ncam-ng-ctl admin"
			say "  Cambiar su rol:       ncam-ng-ctl admin role $auser reseller"
			;;

		role)
			items="$ADMIN_ITEMS"
			set -- $items
			[ $# -eq 2 ] || die "uso: ncam-ng-ctl admin role USUARIO super_admin|reseller|user"
			say "==> cambiando el rol de '$1' a '$2'"
			panel_seed --set-role "$1" "$2"
			;;

		del)
			items="$ADMIN_ITEMS"
			set -- $items
			[ $# -eq 1 ] || die "uso: ncam-ng-ctl admin del USUARIO"
			say "==> eliminando la cuenta '$1'"
			panel_seed --delete "$1"
			;;

		passwd)
			items="$ADMIN_ITEMS"
			set -- $items
			[ $# -eq 1 ] || die "uso: ncam-ng-ctl admin passwd USUARIO (o: ncam-ng-ctl passwd USUARIO)"
			USERNAME="$1"
			do_passwd
			;;

		*)
			die "opción desconocida de admin: '$op' (usa --help)"
			;;
	esac
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
	admin)   do_admin ;;
	version) do_version ;;
	webif)
		case "$WEBIF_OP" in
			add)  do_webif_edit add $WEBIF_ITEMS ;;
			del)  do_webif_edit del $WEBIF_ITEMS ;;
			*)    do_webif_show ;;
		esac
		;;
	*)       usage; exit 2 ;;
esac
