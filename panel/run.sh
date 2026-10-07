#!/bin/sh
# Arranca el panel NCam-NG (API + frontend). Es también el arranque del servicio
# systemd (ExecStart=/opt/ncam-ng-panel/run.sh), así que la dirección y el puerto
# salen del MISMO sitio en los dos casos: el fichero .env del panel.
#
#   ./run.sh                          # usa panel/.venv si existe (si no, python3 del sistema)
#   NCAM_PANEL_PORT=9000 ./run.sh     # lo que pases en el entorno manda sobre el .env
#
# Variables de entorno útiles: NCAM_PANEL_HOST, NCAM_PANEL_PORT, NCAM_PANEL_DB,
# NCAM_WEBIF_URL... (cualquiera del .env.example).
#
# Para cambiar el puerto del servicio instalado:
#   sudo ncam-ng-ctl panel port 8090     (edita el .env, reinicia y comprueba)
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

# dirección y puerto: del .env o, si no hay, los de siempre (0.0.0.0:8080)
HOST="${NCAM_PANEL_HOST:-0.0.0.0}"
PORT="${NCAM_PANEL_PORT:-8080}"
case "$PORT" in
	''|*[!0-9]*)
		echo "error: NCAM_PANEL_PORT='$PORT' no es un número; revisa $(pwd)/.env" >&2
		exit 1
		;;
	0*)
		echo "error: NCAM_PANEL_PORT='$PORT' no es un puerto válido (1-65535); revisa $(pwd)/.env" >&2
		exit 1
		;;
esac
if [ "$PORT" -gt 65535 ]; then
	echo "error: NCAM_PANEL_PORT=$PORT está fuera de rango (1-65535); revisa $(pwd)/.env" >&2
	exit 1
fi

if [ -x ".venv/bin/python" ]; then
	PYTHON="$(pwd)/.venv/bin/python"
else
	PYTHON=python3
	if ! "$PYTHON" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
		echo "aviso: no encuentro panel/.venv y el python3 del sistema no tiene fastapi/uvicorn." >&2
		echo "       prepara el entorno con:  devtools/install-panel.sh" >&2
	fi
fi

echo "NCPanel: escuchando en http://$HOST:$PORT"
exec "$PYTHON" -m uvicorn app.main:app \
	--host "$HOST" \
	--port "$PORT"
