#!/bin/sh
# NCam-NG :: pruebas del frontend (jsdom). Instala jsdom en una carpeta temporal
# y ejecuta devtools/frontend-smoke-test.mjs. Pensado para el CI y para local.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work="${TMPDIR:-/tmp}/ncam-ng-frontend-tests"
mkdir -p "$work"

if ! command -v node >/dev/null 2>&1; then
	echo "aviso: node no está instalado; se omiten las pruebas del frontend" >&2
	exit 0
fi

if [ ! -d "$work/node_modules/jsdom" ]; then
	echo "==> instalando jsdom en $work"
	( cd "$work" && npm install --silent --no-audit --no-fund jsdom >/dev/null 2>&1 ) || {
		echo "aviso: no se pudo instalar jsdom (¿sin red?); se omiten las pruebas del frontend" >&2
		exit 0
	}
fi

NCAM_NG_JSDOM_DIR="$work/node_modules" node "$root/devtools/frontend-smoke-test.mjs"
