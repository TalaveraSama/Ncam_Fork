#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: comprobaciones de los scripts de instalación
#
#   sh devtools/run-install-tests.sh
#
# Verifica lo que sí se puede comprobar sin tocar el sistema:
#   * los scripts son válidos para sh y responden a --help
#   * ninguna función se llama a sí misma (un error así provocó el fallo
#     "Maximum function recursion depth reached" en el instalador)
#   * el instalador localiza los paquetes de una release real
#
# Las pruebas que requieren internet se omiten si no hay conexión.
# ---------------------------------------------------------------------------
set -e

NCAM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$NCAM_ROOT"

ok=0
fail=0
check() {   # check <descripción> <resultado>
	if [ "$2" = "0" ]; then
		printf '  [ ok ] %s\n' "$1"
		ok=$((ok + 1))
	else
		printf '  [FALLO] %s\n' "$1"
		fail=$((fail + 1))
	fi
}

echo "== sintaxis y ayuda de los scripts =="
for script in devtools/install-deb.sh devtools/build-deb.sh devtools/install-daemon.sh \
		devtools/install-panel.sh devtools/install-systemd.sh; do
	sh -n "$script" 2>/dev/null
	check "$script: sintaxis válida" $?
	sh "$script" --help >/dev/null 2>&1
	check "$script: --help responde" $?
done

echo "== funciones que se llaman a sí mismas (recursión) =="
# Un "| nombre |" o "nombre |" dentro de la propia definición de la función es
# casi siempre un error de edición; se detecta comparando con el nombre.
for script in devtools/install-deb.sh devtools/build-deb.sh; do
	bad=0
	for fn in $(sed -n 's/^\([a-z_][a-z_]*\)() *{.*/\1/p' "$script"); do
		if awk -v f="$fn" '
			$0 ~ "^" f "\\(\\)" { inside = 1; next }
			inside && /^}/ { inside = 0 }
			inside && index($0, f " |") { found = 1 }
			END { exit(found ? 0 : 1) }
		' "$script"; then
			echo "         $script: la función $fn se llama a sí misma"
			bad=1
		fi
	done
	check "$script: sin funciones recursivas" "$bad"
done

echo "== gestor de servicios (ncam-ng-ctl) =="
sh -n packaging/ncam-ng-ctl.sh 2>/dev/null
check "ncam-ng-ctl: sintaxis válida" $?
sh packaging/ncam-ng-ctl.sh --help >/dev/null 2>&1
check "ncam-ng-ctl: --help responde" $?
out="$(sh packaging/ncam-ng-ctl.sh --dry-run restart ncam 2>&1)"
if printf '%s' "$out" | grep -q "systemctl restart ncam"; then r=0; else r=1; fi
check "restart ncam pide reiniciar solo el daemon" "$r"
out="$(sh packaging/ncam-ng-ctl.sh --dry-run restart panel 2>&1)"
if printf '%s' "$out" | grep -q "systemctl restart ncam-panel"; then r=0; else r=1; fi
check "restart panel pide reiniciar solo el panel" "$r"
out="$(sh packaging/ncam-ng-ctl.sh --dry-run restart 2>&1)"
if printf '%s' "$out" | grep -q "systemctl restart ncam" && printf '%s' "$out" | grep -q "systemctl restart ncam-panel"; then r=0; else r=1; fi
check "restart sin destino reinicia los dos" "$r"

# los atajos dependen del nombre con el que se llama al script
tmp_links="$(mktemp -d)"
for alias in restart-ncam restart-ncam-panel ncam-ng-status; do
	ln -sf "$NCAM_ROOT/packaging/ncam-ng-ctl.sh" "$tmp_links/$alias"
done
out="$("$tmp_links/restart-ncam" --dry-run 2>&1)"
if printf '%s' "$out" | grep -q "systemctl restart ncam$"; then r=0; else r=1; fi
check "atajo restart-ncam" "$r"
out="$("$tmp_links/restart-ncam-panel" --dry-run 2>&1)"
if printf '%s' "$out" | grep -q "systemctl restart ncam-panel"; then r=0; else r=1; fi
check "atajo restart-ncam-panel" "$r"
"$tmp_links/ncam-ng-status" >/dev/null 2>&1 && r=0 || r=$?
check "atajo ncam-ng-status funciona sin root" "$r"
rm -rf "$tmp_links"

sh packaging/ncam-ng-ctl.sh --opcion-mala >/dev/null 2>&1 && r=0 || r=$?
[ "$r" = "2" ] && r=0 || r=1
check "ncam-ng-ctl: opción desconocida avisa (sin sudo)" "$r"

echo "== acceso al WebIf (ncam-ng-ctl webif) =="
tmp_webif="$(mktemp -d)"
cat > "$tmp_webif/ncam.conf" <<'CONF'
[global]
nice = -1

[webif]
httpport = 8181
httpuser = admin
httpallowed = 127.0.0.1,192.168.0.0-192.168.255.255
CONF
sed "s|^NCAM_CONF=.*|NCAM_CONF=\"$tmp_webif/ncam.conf\"|" packaging/ncam-ng-ctl.sh > "$tmp_webif/ctl"
chmod +x "$tmp_webif/ctl"

out="$(sh "$tmp_webif/ctl" --dry-run webif add 191.103.121.243 2>&1)"
if printf '%s' "$out" | grep -q "191.103.121.243"; then r=0; else r=1; fi
check "webif add: simula la IP que se permite" "$r"
if grep -q "191.103.121.243" "$tmp_webif/ncam.conf"; then r=1; else r=0; fi
check "webif add --dry-run no toca la configuración" "$r"

out="$(sh "$tmp_webif/ctl" --no-restart webif add 191.103.121.243 192.6.154.19 2>&1)"
if grep -q "^httpallowed = 127.0.0.1,192.168.0.0-192.168.255.255,191.103.121.243,192.6.154.19$" "$tmp_webif/ncam.conf"; then r=0; else r=1; fi
check "webif add: añade las IP al final de httpallowed" "$r"
if ls "$tmp_webif"/ncam.conf.bak-* >/dev/null 2>&1; then r=0; else r=1; fi
check "webif add: guarda copia de seguridad" "$r"

out="$(sh "$tmp_webif/ctl" --no-restart webif add 191.103.121.243 2>&1)"
if printf '%s' "$out" | grep -q "ya estaba permitido"; then r=0; else r=1; fi
check "webif add: no duplica una IP ya permitida" "$r"

out="$(sh "$tmp_webif/ctl" --no-restart webif add micasa.dyndns.org 2>&1)"
if grep -q "^httpdyndns = micasa.dyndns.org$" "$tmp_webif/ncam.conf"; then r=0; else r=1; fi
check "webif add: un dominio va a httpdyndns" "$r"

sh "$tmp_webif/ctl" --no-restart webif del 192.6.154.19 >/dev/null 2>&1
if grep -q "^httpallowed = 127.0.0.1,192.168.0.0-192.168.255.255,191.103.121.243$" "$tmp_webif/ncam.conf"; then r=0; else r=1; fi
check "webif del: quita solo esa IP" "$r"

out="$(sh "$tmp_webif/ctl" --no-restart webif 2>&1)"
if printf '%s' "$out" | grep -q "191.103.121.243" && printf '%s' "$out" | grep -q "IP pública / VPN"; then r=0; else r=1; fi
check "webif: muestra las IP permitidas y su tipo" "$r"

sh "$tmp_webif/ctl" --no-restart webif add 10.0.0.7 >/dev/null 2>&1
out="$(sh "$tmp_webif/ctl" --no-restart webif 2>&1)"
if printf '%s' "$out" | grep -q "10.0.0.7" && printf '%s' "$out" | grep -q "red local"; then r=0; else r=1; fi
check "webif: distingue una IP de red local" "$r"

sh "$tmp_webif/ctl" --no-restart webif add 999.1.1.1 >/dev/null 2>&1 && r=0 || r=$?
if [ "$r" != "0" ]; then r=0; else r=1; fi
check "webif add: rechaza algo que no es IP, rango ni dominio" "$r"

cat > "$tmp_webif/sin.conf" <<'CONF'
[global]
nice = -1

[webif]
httpport = 8181
CONF
sed "s|^NCAM_CONF=.*|NCAM_CONF=\"$tmp_webif/sin.conf\"|" packaging/ncam-ng-ctl.sh > "$tmp_webif/ctl2"
chmod +x "$tmp_webif/ctl2"
sh "$tmp_webif/ctl2" --no-restart webif add 191.103.121.243 >/dev/null 2>&1
if grep -q "^httpallowed = 127.0.0.1,191.103.121.243$" "$tmp_webif/sin.conf" && awk '/^\[webif\]/{print NR}' "$tmp_webif/sin.conf" | head -1 | grep -q . ; then
	section_line=$(awk '/^\[webif\]/{print NR}' "$tmp_webif/sin.conf")
	http_line=$(awk '/^httpallowed/{print NR}' "$tmp_webif/sin.conf")
	# tiene que quedar dentro de la sección (justo después de la cabecera)
	[ "$http_line" -gt "$section_line" ] && r=0 || r=1
else
	r=1
fi
check "webif add: crea httpallowed si no existía (tras [webif])" "$r"

echo "== aviso del panel: el WebIf tiene que permitir 127.0.0.1 =="
# El panel consulta el WebIf desde dentro de la máquina; si 127.0.0.1 no está en
# httpallowed el daemon responde 403 y el panel se queda «sin conexión».
mkdir -p "$tmp_webif/panel"
sed "s|^NCAM_CONF=.*|NCAM_CONF=\"$tmp_webif/panel.conf\"|; s|^PANEL_DIR=.*|PANEL_DIR=\"$tmp_webif/panel\"|" \
	packaging/ncam-ng-ctl.sh > "$tmp_webif/ctl3"
chmod +x "$tmp_webif/ctl3"
printf '[webif]\nhttpallowed = 191.103.121.243\n' > "$tmp_webif/panel.conf"

out="$(sh "$tmp_webif/ctl3" webif 2>&1)"
if printf '%s' "$out" | grep -q "AVISO: el panel NCPanel"; then r=0; else r=1; fi
check "webif: avisa si el panel (127.0.0.1) no puede consultar el WebIf" "$r"

sh "$tmp_webif/ctl3" webif check >/dev/null 2>&1 && r=0 || r=$?
if [ "$r" = "1" ]; then r=0; else r=1; fi
check "webif check: devuelve 1 cuando falta 127.0.0.1" "$r"

printf '[webif]\nhttpallowed = 127.0.0.1,191.103.121.243\n' > "$tmp_webif/panel.conf"
out="$(sh "$tmp_webif/ctl3" webif 2>&1)"
if printf '%s' "$out" | grep -q "AVISO: el panel NCPanel"; then r=1; else r=0; fi
check "webif: no avisa si 127.0.0.1 está permitida" "$r"

sh "$tmp_webif/ctl3" webif check >/dev/null 2>&1 && r=0 || r=$?
check "webif check: devuelve 0 cuando 127.0.0.1 está permitida" "$r"

# el postinst del panel usa esa misma comprobación (una sola fuente de verdad)
sed -n '/# 8\. el panel consulta/,/^fi$/p' packaging/ncam-ng-panel.postinst \
	| sed "s|/usr/bin/ncam-ng-ctl|$tmp_webif/ctl3|g" > "$tmp_webif/postinst-bloque.sh"
{ printf 'ROOT=""\nlog() { printf "%%s\\n" "$*"; }\n'; cat "$tmp_webif/postinst-bloque.sh"; } \
	> "$tmp_webif/postinst-run.sh"

printf '[webif]\nhttpallowed = 191.103.121.243\n' > "$tmp_webif/panel.conf"
out="$(NCAM_CONF="$tmp_webif/panel.conf" NCAM_CONF_FILE="$tmp_webif/panel.conf" sh "$tmp_webif/postinst-run.sh" 2>&1)"
if printf '%s' "$out" | grep -q "AVISO"; then r=0; else r=1; fi
check "postinst del panel: avisa cuando el WebIf no permite 127.0.0.1" "$r"

printf '[webif]\nhttpallowed = 127.0.0.1\n' > "$tmp_webif/panel.conf"
out="$(NCAM_CONF="$tmp_webif/panel.conf" NCAM_CONF_FILE="$tmp_webif/panel.conf" sh "$tmp_webif/postinst-run.sh" 2>&1)"
if printf '%s' "$out" | grep -q "AVISO"; then r=1; else r=0; fi
check "postinst del panel: no avisa si 127.0.0.1 está permitida" "$r"

rm -rf "$tmp_webif"

echo "== puerto del panel (run.sh, unidad systemd y ncam-ng-ctl panel port) =="
# El puerto del panel se lee del .env, tanto a mano (run.sh) como con el servicio.
# Se comprueba con un python de mentira que imprime los argumentos con los que se
# arrancaría uvicorn de verdad.
tmp_run="$(mktemp -d)"
mkdir -p "$tmp_run/.venv/bin"
cp panel/run.sh "$tmp_run/"
printf '#!/bin/sh\necho "FAKE-PYTHON: $*"\n' > "$tmp_run/.venv/bin/python"
chmod +x "$tmp_run/.venv/bin/python"

printf 'NCAM_PANEL_HOST=127.0.0.1\nNCAM_PANEL_PORT=8095\n' > "$tmp_run/.env"
out="$(sh "$tmp_run/run.sh" 2>&1)"
if printf '%s' "$out" | grep -q -- "--host 127.0.0.1 --port 8095"; then r=0; else r=1; fi
check "run.sh: la dirección y el puerto salen del .env" "$r"

out="$(NCAM_PANEL_PORT=9000 sh "$tmp_run/run.sh" 2>&1)"
if printf '%s' "$out" | grep -q -- "--port 9000"; then r=0; else r=1; fi
check "run.sh: lo que venga en el entorno manda sobre el .env" "$r"

printf 'NCAM_PANEL_PORT=ochomil\n' > "$tmp_run/.env"
out="$(sh "$tmp_run/run.sh" 2>&1)" && r=1 || r=0
if printf '%s' "$out" | grep -q "no es un número"; then r=0; else r=1; fi
check "run.sh: un puerto no numérico avisa y no arranca" "$r"

# la unidad systemd no puede volver a fijar el puerto por su cuenta: eso era lo
# que hacía que cambiar el .env no sirviera de nada
if grep -q -- "ExecStart=/opt/ncam-ng-panel/run.sh" packaging/ncam-panel.service; then r=0; else r=1; fi
check "unidad systemd: arranca con run.sh (una sola fuente de verdad)" "$r"
if grep -qE "ExecStart=.*--port|Environment=NCAM_PANEL_PORT|Environment=NCAM_PANEL_HOST" packaging/ncam-panel.service; then r=1; else r=0; fi
check "unidad systemd: no fija host ni puerto (mandan el .env y run.sh)" "$r"

tmp_cf="$(mktemp -d)"
printf '[webif]\nNCAM_PANEL_X=1\n' > /dev/null 2>&1 || true
cat > "$tmp_cf/.env" <<'ENV'
NCAM_PANEL_HOST=0.0.0.0
NCAM_PANEL_PORT=8080
NCAM_PANEL_SECRET=secreto-de-prueba
ENV
cat > "$tmp_cf/cloudflared.yml" <<'CF'
tunnel: ncpanel
ingress:
  - hostname: panel.ejemplo.com
    service: http://127.0.0.1:8080
  - service: http_status:404
CF

out="$(NCAM_PANEL_DIR="$tmp_cf" NCAM_CLOUDFLARED_CONF="$tmp_cf/cloudflared.yml" \
	sh packaging/ncam-ng-ctl.sh --dry-run panel port 2>&1)"
if printf '%s' "$out" | grep -q "puerto 8080" && printf '%s' "$out" | grep -q "cloudflared"; then r=0; else r=1; fi
check "panel port: muestra el puerto y a dónde apunta el túnel" "$r"

out="$(NCAM_PANEL_DIR="$tmp_cf" sh packaging/ncam-ng-ctl.sh --dry-run panel port 99999 2>&1)" && r=1 || r=0
if printf '%s' "$out" | grep -q "no es válido"; then r=0; else r=1; fi
check "panel port: rechaza un puerto fuera de rango" "$r"

out="$(NCAM_PANEL_DIR="$tmp_cf" sh packaging/ncam-ng-ctl.sh --dry-run panel port abc 2>&1)" && r=1 || r=0
if printf '%s' "$out" | grep -q "no es válido"; then r=0; else r=1; fi
check "panel port: rechaza un puerto que no es un número" "$r"

if [ "$(id -u)" = "0" ]; then
	out="$(NCAM_PANEL_DIR="$tmp_cf" NCAM_CLOUDFLARED_CONF="$tmp_cf/cloudflared.yml" \
		sh packaging/ncam-ng-ctl.sh --no-restart panel port 8090 2>&1)"
	if grep -q "^NCAM_PANEL_PORT=8090$" "$tmp_cf/.env"; then r=0; else r=1; fi
	check "panel port: escribe el puerto nuevo en el .env" "$r"
	if ls "$tmp_cf"/.env.bak-* >/dev/null 2>&1; then r=0; else r=1; fi
	check "panel port: deja copia de seguridad del .env" "$r"
	if printf '%s' "$out" | grep -q "el túnel de Cloudflare"; then r=0; else r=1; fi
	check "panel port: avisa de que cloudflared apunta al puerto viejo" "$r"
	if grep -q "^NCAM_PANEL_HOST=0.0.0.0$" "$tmp_cf/.env" && grep -q "^NCAM_PANEL_SECRET=secreto-de-prueba$" "$tmp_cf/.env"; then r=0; else r=1; fi
	check "panel port: respeta las demás claves del .env" "$r"

	# con la clave repetida, al cambiar el puerto tiene que quedar UNA sola línea
	# (si quedan varias, el panel usa la primera y el cambio no surte efecto)
	printf 'NCAM_PANEL_PORT=8080\nNCAM_PANEL_SECRET=x\nNCAM_PANEL_PORT=8090\n' > "$tmp_cf/.env"
	out="$(NCAM_PANEL_DIR="$tmp_cf" sh packaging/ncam-ng-ctl.sh --no-restart panel port 8082 2>&1)"
	n="$(grep -cE '^[[:space:]]*NCAM_PANEL_PORT[[:space:]]*=' "$tmp_cf/.env")"
	if [ "$n" = "1" ] && grep -q "^NCAM_PANEL_PORT=8082$" "$tmp_cf/.env"; then r=0; else r=1; fi
	check "panel port: al cambiarlo, deja una sola línea de la clave" "$r"
	if printf '%s' "$out" | grep -q "estaba 2 veces"; then r=0; else r=1; fi
	check "panel port: avisa de que ha quitado la línea repetida" "$r"
else
	echo "  [omitido] escritura real del .env (necesita root; ejecuta la suite con sudo)"
fi

# El panel arranca con la PRIMERA aparición de la clave (lo hacen run.sh y
# config.py); si el .env la tiene dos veces, la herramienta tiene que decir la
# misma que usará el panel, no la última.
cat > "$tmp_cf/.env" <<'ENV'
NCAM_PANEL_HOST=0.0.0.0
NCAM_PANEL_PORT=8090
NCAM_PANEL_SECRET=secreto-de-prueba
NCAM_PANEL_PORT=8082
ENV
out="$(NCAM_PANEL_DIR="$tmp_cf" sh packaging/ncam-ng-ctl.sh --dry-run panel port 2>&1)"
if printf '%s' "$out" | grep -q "puerto 8090" && printf '%s' "$out" | grep -q "hay 2 líneas"; then r=0; else r=1; fi
check "panel port: con la clave repetida usa la primera y avisa" "$r"

# un "#" al final de la línea se toma como parte del valor: hay que avisarlo
printf 'NCAM_PANEL_PORT=8090  # panel\nNCAM_PANEL_SECRET=x\n' > "$tmp_cf/.env"
out="$(NCAM_PANEL_DIR="$tmp_cf" sh packaging/ncam-ng-ctl.sh --dry-run panel port 2>&1)"
if printf '%s' "$out" | grep -q "comentario detrás"; then r=0; else r=1; fi
check "panel port: avisa si la línea lleva un comentario detrás" "$r"

# con espacios delante de la clave (nano los deja a veces) sí hay que leerla
printf '   NCAM_PANEL_PORT=8091\nNCAM_PANEL_SECRET=x\n' > "$tmp_cf/.env"
out="$(NCAM_PANEL_DIR="$tmp_cf" sh packaging/ncam-ng-ctl.sh --dry-run panel port 2>&1)"
if printf '%s' "$out" | grep -q "puerto 8091"; then r=0; else r=1; fi
check "panel port: entiende la clave con espacios delante" "$r"

rm -rf "$tmp_run" "$tmp_cf"

echo "== cuentas del panel (ncam-ng-ctl admin) =="
out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin 2>&1)"
if printf '%s' "$out" | grep -q "app.seed --list"; then r=0; else r=1; fi
check "admin: lista las cuentas del panel" "$r"

out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin add ana 2>&1)"
if printf '%s' "$out" | grep -q -- "--create --username ana --role super_admin"; then r=0; else r=1; fi
check "admin add: crea un super administrador por defecto" "$r"

out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin add luis reseller 2>&1)"
if printf '%s' "$out" | grep -q -- "--role reseller"; then r=0; else r=1; fi
check "admin add: admite el rol revendedor" "$r"

out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin add pepe user Clave.Pepe1 pepe@ejemplo.com 2>&1)"
if printf '%s' "$out" | grep -q -- "--role user" && printf '%s' "$out" | grep -q -- "--password Clave.Pepe1" \
	&& printf '%s' "$out" | grep -q -- "--email pepe@ejemplo.com"; then r=0; else r=1; fi
check "admin add: acepta rol, contraseña y email" "$r"

out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin role luis reseller 2>&1)"
if printf '%s' "$out" | grep -q -- "--set-role luis reseller"; then r=0; else r=1; fi
check "admin role: cambia el rol de una cuenta" "$r"

out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin del viejo 2>&1)"
if printf '%s' "$out" | grep -q -- "--delete viejo"; then r=0; else r=1; fi
check "admin del: elimina una cuenta" "$r"

# "admin" también es un nombre de usuario válido
out="$(sh packaging/ncam-ng-ctl.sh --dry-run admin passwd admin 2>&1)"
if printf '%s' "$out" | grep -q -- "--username admin --reset-password"; then r=0; else r=1; fi
check "admin passwd: admite nombres de usuario que son palabras clave" "$r"

sh packaging/ncam-ng-ctl.sh --dry-run admin borrar cosas >/dev/null 2>&1 && r=0 || r=$?
if [ "$r" != "0" ]; then r=0; else r=1; fi
check "admin: una opción desconocida avisa" "$r"

sh packaging/ncam-ng-ctl.sh --help 2>/dev/null | grep -q "ncam-ng-ctl admin add"
check "ncam-ng-ctl --help documenta admin add" $?

sh packaging/ncam-ng-ctl.sh --help 2>/dev/null | grep -q "ncam-ng-ctl webif check"
check "ncam-ng-ctl --help documenta webif check" $?

sh packaging/ncam-ng-ctl.sh --help 2>/dev/null | grep -q "ncam-ng-ctl panel port"
check "ncam-ng-ctl --help documenta panel port" $?

# el comando de siempre para cambiar una contraseña sigue funcionando
out="$(sh packaging/ncam-ng-ctl.sh --dry-run passwd admin 2>&1)"
if printf '%s' "$out" | grep -q -- "--username admin --reset-password"; then r=0; else r=1; fi
check "passwd: sigue funcionando tras el refactor" "$r"

echo "== opciones del instalador =="
sh devtools/install-deb.sh --help 2>/dev/null | grep -q -- '--list-assets'
check "el instalador documenta --list-assets" $?
sh devtools/install-deb.sh --opcion-inventada >/dev/null 2>&1 && r=0 || r=$?
[ "$r" = "2" ] && r=0 || r=1
check "una opción desconocida termina con error" "$r"

echo "== análisis de una release real (necesita internet) =="
if curl -fsSL --connect-timeout 10 -o /dev/null \
		https://api.github.com/repos/TalaveraSama/Ncam_Fork/releases/latest 2>/dev/null; then
	out="$(sh devtools/install-deb.sh --list-assets 2>&1)"

	# ojo: con "set -e" no vale terminar un grep en falso; se comprueba con if
	if printf '%s' "$out" | grep -q "recursion"; then r=1; else r=0; fi
	check "sin avisos de recursión" "$r"
	if printf '%s' "$out" | grep -q "ncam-ng_.*amd64[.]deb"; then r=0; else r=1; fi
	check "encuentra el paquete del daemon" "$r"
	if printf '%s' "$out" | grep -q "ncam-ng-panel_.*amd64[.]deb"; then r=0; else r=1; fi
	check "encuentra el paquete del panel" "$r"
	if printf '%s' "$out" | grep -q "SHA256SUMS"; then r=0; else r=1; fi
	check "encuentra el SHA256SUMS" "$r"
else
	echo "  [omitido] sin conexión a la API de GitHub"
fi

echo
echo "================================="
echo "$ok comprobaciones, $fail fallos"
[ "$fail" = "0" ] || exit 1
