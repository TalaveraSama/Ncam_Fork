#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: prepara el panel (entorno virtual + dependencias + .env)
#
#   devtools/install-panel.sh                 # venv, dependencias, .env y semilla
#   devtools/install-panel.sh --demo          # además datos de demostración
#   devtools/install-panel.sh --username admin --no-seed
#
# No arranca el panel: al terminar imprime cómo hacerlo (./panel/run.sh).
# Es idempotente: si el entorno o el .env ya existen, no los toca.
# ---------------------------------------------------------------------------
set -e

SEED=1
DEMO=0
SEED_USER="admin"

while [ $# -gt 0 ]; do
	case "$1" in
		--username) SEED_USER="${2:?falta el nombre de usuario}"; shift 2 ;;
		--no-seed)  SEED=0; shift ;;
		--demo)     DEMO=1; shift ;;
		-h|--help)
			sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
	esac
done

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
panel="$repo_root/panel"

if [ ! -f "$panel/requirements.txt" ]; then
	echo "error: no se encontró $panel/requirements.txt" >&2
	exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
	echo "error: falta python3 (instala python3, python3-venv y python3-pip)" >&2
	exit 1
fi

cd "$panel"

# 1. entorno virtual (se crea en panel/.venv)
if [ ! -x ".venv/bin/python" ]; then
	echo "creando entorno virtual : $panel/.venv"
	python3 -m venv .venv || {
		echo "error: no se pudo crear el entorno virtual." >&2
		echo "       ¿instalaste python3-venv?  sudo apt install python3-venv" >&2
		exit 1
	}
else
	echo "entorno virtual        : $panel/.venv (ya existía)"
fi

# 2. dependencias
echo "instalando dependencias: fastapi + uvicorn"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python -c "import fastapi, uvicorn; print('  fastapi', fastapi.__version__, '| uvicorn', uvicorn.__version__)"

# 3. .env (a partir del ejemplo) con secreto generado
if [ -f .env ]; then
	echo ".env                   : $panel/.env (ya existía, no se toca)"
else
	cp .env.example .env
	echo ".env                   : $panel/.env (creado desde .env.example)"
fi

if grep -q '^NCAM_PANEL_SECRET=$' .env 2>/dev/null; then
	secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
	# compatible con GNU sed y con BSD/macOS
	sed -i.bak "s|^NCAM_PANEL_SECRET=$|NCAM_PANEL_SECRET=$secret|" .env && rm -f .env.bak
	echo "secreto de firma       : generado en .env"
fi

# 4. super administrador (y datos de demostración si se piden)
if [ "$SEED" = "1" ]; then
	echo
	echo "creando el super administrador ($SEED_USER)..."
	PYTHONPATH=backend .venv/bin/python -m app.seed --username "$SEED_USER" || {
		echo "aviso: la semilla falló; puedes repetirla con:" >&2
		echo "       cd $panel && PYTHONPATH=backend .venv/bin/python -m app.seed --username $SEED_USER" >&2
	}
fi
if [ "$DEMO" = "1" ]; then
	PYTHONPATH=backend .venv/bin/python -m app.seed --demo
fi

echo
echo "Panel preparado. Arranque y uso:"
echo "  cd $panel && . .venv/bin/activate && ./run.sh          # http://TU_IP:8080"
echo "  (o sin activar el entorno:  $panel/run.sh )"
echo
echo "Revisa antes $panel/.env (NCAM_WEBIF_URL y credenciales del WebIf del daemon)."
