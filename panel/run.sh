#!/bin/sh
# Arranca el panel NCam-NG (API + frontend) en el puerto indicado.
#
#   ./run.sh                     # usa panel/.venv si existe (si no, python3 del sistema)
#   NCAM_PANEL_PORT=9000 ./run.sh
#
# Variables de entorno útiles: NCAM_PANEL_HOST, NCAM_PANEL_PORT, NCAM_PANEL_DB,
# NCAM_WEBIF_URL... (cualquiera del .env.example).
set -e
cd "$(dirname "$0")"

# .env, si existe (sin sobreescribir lo que ya venga del entorno).
# Se cargan solo las asignaciones "CLAVE=valor" válidas: los comentarios y los
# valores con espacios (p. ej. NCAM_PANEL_NAME=NCPanel) no rompen el script.
if [ -f .env ]; then
	while IFS= read -r line; do
		case "$line" in ''|'#'*) continue ;; esac
		key=${line%%=*}
		[ "$key" = "$line" ] && continue
		case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
		value=${line#*=}
		case "$value" in
			\"*\") value=${value#\"}; value=${value%\"} ;;
			\'*\') value=${value#\'}; value=${value%\'} ;;
		esac
		# lo que ya venga del entorno del usuario manda sobre el .env
		eval "current=\${$key:-}"
		[ -n "$current" ] && continue
		export "$key=$value"
	done < .env
fi

export PYTHONPATH="$(pwd)/backend:${PYTHONPATH}"

if [ -x ".venv/bin/python" ]; then
	PYTHON="$(pwd)/.venv/bin/python"
else
	PYTHON=python3
	if ! "$PYTHON" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
		echo "aviso: no encuentro panel/.venv y el python3 del sistema no tiene fastapi/uvicorn." >&2
		echo "       prepara el entorno con:  devtools/install-panel.sh" >&2
	fi
fi

exec "$PYTHON" -m uvicorn app.main:app \
	--host "${NCAM_PANEL_HOST:-0.0.0.0}" \
	--port "${NCAM_PANEL_PORT:-8080}"
