#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG Panel :: prepara el entorno del panel (instalado por el .deb)
#
#   sudo ncam-ng-panel-setup              # crea/actualiza el entorno y las dependencias
#   sudo ncam-ng-panel-setup --online     # ignora las ruedas incluidas y usa PyPI
#
# Es idempotente: se puede repetir tras una actualización o si algo falla.
# El paquete incluye las dependencias de Python (ruedas) para instalar sin
# conexión cuando la versión de Python coincide; si no, usa PyPI.
# ---------------------------------------------------------------------------
set -e

PANEL_DIR="${PANEL_DIR:-/opt/ncam-ng-panel}"
VENV="$PANEL_DIR/.venv"
WHEELS="${WHEELS:-/usr/lib/ncam-ng-panel/wheels}"
ONLINE=0
[ "$1" = "--online" ] && ONLINE=1

log() { echo "ncam-ng-panel-setup: $*"; }

if [ ! -f "$PANEL_DIR/requirements.txt" ]; then
	log "ERROR: no encuentro $PANEL_DIR/requirements.txt"
	exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
	log "ERROR: falta python3 (sudo apt install python3 python3-venv)"
	exit 1
fi

# 1. entorno virtual
if [ ! -x "$VENV/bin/python" ]; then
	log "creando entorno virtual en $VENV"
	python3 -m venv "$VENV" || {
		log "ERROR: no se pudo crear el entorno virtual."
		log "       instala python3-venv:  sudo apt install python3-venv"
		exit 1
	}
	FRESH=1
else
	log "entorno virtual ya existente: $VENV"
	FRESH=0
fi

# 2. dependencias
install_deps() {
	"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
	"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$PANEL_DIR/requirements.txt"
}

if [ "$ONLINE" = "0" ] && [ -d "$WHEELS" ]; then
	log "instalando dependencias sin conexión desde $WHEELS"
	if "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
			--no-index --find-links "$WHEELS" -r "$PANEL_DIR/requirements.txt"; then
		:
	else
		log "las ruedas incluidas no sirven para este Python; usando PyPI"
		install_deps
	fi
else
	log "instalando dependencias desde PyPI"
	install_deps
fi

# 3. comprobación
if ! "$VENV/bin/python" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
	log "ERROR: el panel no puede arrancar (faltan fastapi/uvicorn)."
	log "       revisa tu conexión y reintenta:  sudo ncam-ng-panel-setup --online"
	exit 1
fi
log "dependencias listas: $("$VENV/bin/python" -c 'import fastapi, uvicorn; print("fastapi", fastapi.__version__, "| uvicorn", uvicorn.__version__)')"

[ "$FRESH" = "1" ] && log "entorno preparado en $VENV"
exit 0
