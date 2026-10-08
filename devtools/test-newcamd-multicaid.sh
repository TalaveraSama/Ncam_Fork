#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: prueba funcional de newcamd multi-CAID en un solo puerto
#
#   sh devtools/test-newcamd-multicaid.sh
#
# Requisitos: el daemon ya compilado en Distribution/ (lo deja `make`), gcc
# y python3. Levanta el daemon con una configuración temporal en puertos
# altos, le habla con devtools/ncd_test_client.c y comprueba en el log:
#   * un puerto sirve varios CAID (1802, 1861, 0B00) y rechaza los no listados
#   * los clientes estilo oscam (caid 0) se mapean al CAID del puerto
#   * los puertos de un solo CAID y los puertos planos se comportan como antes
#   * la cuenta con `caid =` anuncia solo su CAID permitido
#   * el WebIf muestra y guarda el puerto múltiple sin perder CAID
#   * más de 16 CAID avisa y recorta sin tumbar el daemon
# ---------------------------------------------------------------------------
set -e

NCAM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$NCAM_ROOT"

ok=0
fail=0
check() {   # check <descripción> <0|1>
	if [ "$1" = "0" ]; then
		printf '  [ ok ] %s\n' "$2"
		ok=$((ok + 1))
	else
		printf '  [FALLO] %s\n' "$2"
		fail=$((fail + 1))
	fi
}
# try <descripción> <comando...>: ejecuta sin que `set -e` aborte si falla
try() {
	desc="$1"
	shift
	if "$@" >/dev/null 2>&1; then
		check 0 "$desc"
	else
		check 1 "$desc"
	fi
}

BIN="$(ls -1t Distribution/ncam-Unofficial-* 2>/dev/null | grep -v '\.debug$' | head -n1)"
if [ -z "$BIN" ]; then
	echo "No hay daemon compilado en Distribution/ (ejecuta ./config.sh ... && make primero)"
	exit 1
fi
if ! strings "$BIN" | grep -q "newcamd: extended: report card" || ! strings "$BIN" | grep -q "HTTP Server running"; then
	echo "El binario no trae newcamd+webif: prueba omitida"
	exit 0
fi

WORK="$(mktemp -d /tmp/ncam-ncdtest.XXXXXX)"
CLIENT="$WORK/ncd_test_client"
LOG="$WORK/ncam.log"
DAEMON_PID=""
cleanup() {
	if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
		kill "$DAEMON_PID" 2>/dev/null || true
		sleep 1
		kill -9 "$DAEMON_PID" 2>/dev/null || true
	fi
	rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

echo "== compilación del cliente de pruebas =="
gcc -o "$CLIENT" devtools/ncd_test_client.c module-newcamd-des.c -I. -Wall 2>"$WORK/gcc.log"
try "ncd_test_client compila" test -x "$CLIENT"
try "ncd_test_client compila sin warnings" test ! -s "$WORK/gcc.log"

# crypt-md5 con salt "$1$abcdefgh$" (el que usa NCam; determinista)
H1='$1$abcdefgh$m0INEKWW1jrRTfpNdto3a/'   # clave "test1"
H2='$1$abcdefgh$4StlY5UCQz3PFChWJrguV.'   # clave "test1861"
DESKEY=0102030405060708091011121314
ECM=8030050703000100   # ECM sintético válido (patrón nagra para la adivinanza)

start_daemon() {   # start_daemon <dir-conf> <puerto-webif> [fichero-stderr]
	ERRF="${3:-/dev/null}"
	"$NCAM_ROOT/$BIN" -c "$1" -d 255 -r 0 >"$ERRF" 2>&1 &
	DAEMON_PID=$!
	i=0
	while [ "$i" -lt 40 ]; do
		if python3 -c "import socket; socket.create_connection(('127.0.0.1',$2),timeout=1).close()" 2>/dev/null; then
			return 0
		fi
		sleep 1
		i=$((i + 1))
	done
	echo "  el daemon no levantó el puerto $2"
	return 1
}
stop_daemon() {
	if [ -n "$DAEMON_PID" ]; then
		kill "$DAEMON_PID" 2>/dev/null || true
		sleep 1
		kill -9 "$DAEMON_PID" 2>/dev/null || true
		DAEMON_PID=""
	fi
}
# has <fichero> <texto-fijo> [texto-fijo...]: ¿contiene el fichero todos?
has() {
	f="$1"
	shift
	for t in "$@"; do
		grep -aqF "$t" "$f" || return 1
	done
	return 0
}
# ecmok <fragmento> <esperado>: la línea ECM que contiene el fragmento
# contiene también el resultado esperado (misma línea)
ecmok() {
	grep -aF "(ecm)" "$LOG" | grep -aF "$1" | grep -aq "$2"
}

mkdir -p "$WORK/conf"
cat > "$WORK/conf/ncam.conf" <<EOF
[global]
logfile = $LOG
maxlogsize = 102400
disablelog = 0

[newcamd]
port = 12222@1802:000000,1861:000000,0B00:000000;12333@0500:030300
key = $DESKEY
keepalive = 1

[webif]
httpport = 8181
httpuser = admin
httppwd = admin
httpallowed = 127.0.0.1
EOF
cat > "$WORK/conf/ncam.user" <<EOF
[account]
user = test1
pwd = test1
group = 1
au = 0

[account]
user = test1861
pwd = test1861
group = 1
caid = 1861
au = 0
EOF

echo "== un puerto sirve varios CAID =="
start_daemon "$WORK/conf" 8181
"$CLIENT" 127.0.0.1 12222 test1 "$H1" "$DESKEY" \
	0001:1802:000000:$ECM 0002:1861:000000:$ECM 0003:0B00:000000:$ECM 0004:0500:030300:$ECM \
	>"$WORK/out1.log" 2>&1
try "login + card data" has "$WORK/out1.log" "LOGIN_ACK" "CARD_DATA caid=1802"
sleep 1
try "1802 pasa los filtros" ecmok "test1 (1802@000000" "no matching reader"
try "1861 pasa los filtros" ecmok "test1 (1861@000000" "no matching reader"
try "0B00 pasa los filtros" ecmok "test1 (0B00@000000" "no matching reader"
try "0500 (no listado) se rechaza" ecmok "test1 (0500@" "no card support"

echo "== cliente estilo oscam (caid 0) =="
"$CLIENT" 127.0.0.1 12222 test1 "$H1" "$DESKEY" 0011:0000:000000:$ECM >/dev/null 2>&1
sleep 1
try "adivina nagra y mapea a 1802" has "$LOG" "mapped guessed caid 1801 to port caid 1802"
try "el ECM con caid 0 pasa los filtros" ecmok "test1 (1802@000000/0000/0011" "no matching reader"

echo "== puerto de un solo CAID (sin cambios) =="
"$CLIENT" 127.0.0.1 12333 test1 "$H1" "$DESKEY" 0022:0500:040400:$ECM 0024:0000:000000:$ECM \
	>"$WORK/out3.log" 2>&1
try "anuncia 0500" has "$WORK/out3.log" "CARD_DATA caid=0500"
sleep 1
try "provid no listado se rechaza" ecmok "test1 (0500@040400" "no card support"
try "caid 0 usa el CAID del puerto (0500)" ecmok "test1 (0500@030300/0000/0024" "no matching reader"
try "sin remapeo en puertos de un CAID" test "$(grep -ac 'mapped guessed' "$LOG")" = "1"

echo "== cuenta limitada con caid = 1861 =="
"$CLIENT" 127.0.0.1 12222 test1861 "$H2" "$DESKEY" 0031:1861:000000:$ECM 0032:1802:000000:$ECM \
	>"$WORK/out4.log" 2>&1
try "anuncia solo su CAID (1861)" has "$WORK/out4.log" "CARD_DATA caid=1861"
sleep 1
try "1861 pasa los filtros" ecmok "test1861 (1861@000000" "no matching reader"
try "1802 se rechaza por la cuenta" ecmok "test1861 (1802@000000" "invalid caid"

echo "== WebIf: muestra y guarda el puerto múltiple =="
MULTI="12222@1802:000000,1861:000000,0B00:000000;12333@0500:030300"
curl -s --digest -u admin:admin "http://127.0.0.1:8181/config.html?part=newcamd" >"$WORK/webif.html" 2>&1
try "el WebIf muestra los tres CAID" has "$WORK/webif.html" "$MULTI"
curl -s --digest -u admin:admin -G "http://127.0.0.1:8181/config.html" \
	--data-urlencode "part=newcamd" --data-urlencode "action=execute" \
	--data-urlencode "port=$MULTI" \
	--data-urlencode "serverip=" --data-urlencode "allowed=" \
	--data-urlencode "key=$DESKEY" --data-urlencode "keepalive=1" \
	--data-urlencode "mgclient=0" >"$WORK/save.html" 2>&1
try "guardar desde el WebIf responde OK" has "$WORK/save.html" "was saved"
try "ncam.conf conserva los tres CAID" has "$WORK/conf/ncam.conf" "$MULTI"
"$CLIENT" 127.0.0.1 12222 test1 "$H1" "$DESKEY" 0051:0B00:000000:$ECM >/dev/null 2>&1
sleep 1
try "tras guardar sigue sirviendo 0B00" ecmok "test1 (0B00@000000/0000/0051" "no matching reader"
stop_daemon

echo "== más de 16 CAID =="
mkdir -p "$WORK/conf20"
sed -e 's/12222@1802:000000,1861:000000,0B00:000000/12222@1802:000000,1861:000000,0B00:000000,0100:00006A,0500:040400,0600:000000,0D00:000000,0E00:000000,0900:000000,1702:000000,1722:000000,1830:000000,1833:000000,1834:000000,1843:000000,098C:000000,09C4:000000,0B01:000000,0B02:000000,4A00:000000/' \
	-e 's/;12333@0500:030300//' -e 's/httpport *= 8181/httpport = 8182/' \
	"$WORK/conf/ncam.conf" > "$WORK/conf20/ncam.conf"
cp "$WORK/conf/ncam.user" "$WORK/conf20/ncam.user"
start_daemon "$WORK/conf20" 8182 "$WORK/stderr20.log"
try "avisa por stderr" has "$WORK/stderr20.log" "too many CAIDs for port 12222"
curl -s --digest -u admin:admin "http://127.0.0.1:8182/config.html?part=newcamd" >"$WORK/webif20.html" 2>&1
try "conserva los 16 primeros" has "$WORK/webif20.html" \
	"12222@1802:000000,1861:000000,0B00:000000,0100:00006A,0500:040400,0600:000000,0D00:000000,0E00:000000,0900:000000,1702:000000,1722:000000,1830:000000,1833:000000,1834:000000,1843:000000,098C:000000"
try "el daemon sigue vivo" kill -0 "$DAEMON_PID"
stop_daemon

echo
echo "$((ok + fail)) comprobaciones, $fail fallo(s)"
test "$fail" = "0"
