#!/bin/sh
# Arranca el panel NCam-NG (API + frontend) en el puerto indicado.
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/backend:${PYTHONPATH}"
exec python3 -m uvicorn app.main:app --host "${NCAM_PANEL_HOST:-0.0.0.0}" --port "${NCAM_PANEL_PORT:-8080}"
