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
