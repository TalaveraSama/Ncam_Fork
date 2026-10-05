#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: instala los servicios systemd del daemon y del panel
#
#   sudo devtools/install-systemd.sh                 # crea, habilita y arranca ambos
#   sudo devtools/install-systemd.sh --panel-only    # solo el panel
#   sudo devtools/install-systemd.sh --daemon-only   # solo el daemon
#   sudo devtools/install-systemd.sh --no-start      # no arrancar ahora
#
# Con los servicios instalados el panel y el daemon siguen funcionando al cerrar
# la terminal, arrancan solos con el servidor y se reinician si fallan.
#
# Rutas detectadas automáticamente (se pueden forzar con variables):
#   NCAM_BIN       binario del daemon        (por defecto /usr/local/bin/ncam)
#   NCAM_CONFDIR   configuración del daemon  (por defecto /usr/local/etc)
#   PANEL_DIR      carpeta del panel         (por defecto <repo>/panel)
#   PANEL_HOST/PANEL_PORT  escucha del panel (0.0.0.0 / 8080)
# ---------------------------------------------------------------------------
set -e

DO_DAEMON=1
DO_PANEL=1
DO_START=1

while [ $# -gt 0 ]; do
	case "$1" in
		--daemon-only) DO_PANEL=0; shift ;;
		--panel-only)  DO_DAEMON=0; shift ;;
		--no-start)    DO_START=0; shift ;;
		-h|--help)
			sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
	esac
done

if [ "$(id -u)" != "0" ]; then
	echo "error: ejecútalo con sudo (hay que escribir en /etc/systemd/system)" >&2
	exit 1
fi

if ! command -v systemctl >/dev/null 2>&1 || [ ! -d /run/systemd/system ]; then
	echo "error: este sistema no está arrancado con systemd; no puedo instalar servicios." >&2
	echo "       alternativas: 'nohup ./run.sh &' o un supervisor (supervisord, tmux/screen)." >&2
	exit 1
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
UNIT_DIR=/etc/systemd/system
STAMP=$(date +%Y%m%d-%H%M%S)

NCAM_BIN="${NCAM_BIN:-/usr/local/bin/ncam}"
NCAM_CONFDIR="${NCAM_CONFDIR:-/usr/local/etc}"
PANEL_DIR="${PANEL_DIR:-$repo_root/panel}"
PANEL_HOST="${PANEL_HOST:-0.0.0.0}"
PANEL_PORT="${PANEL_PORT:-8080}"

panel_python="$PANEL_DIR/.venv/bin/python"
[ -x "$panel_python" ] || panel_python=$(command -v python3)

write_unit() {
	# $1 = ruta destino, resto = contenido
	dest="$1"; shift
	if [ -f "$dest" ]; then
		cp -a "$dest" "$dest.bak-$STAMP"
		echo "  (respaldo) $dest.bak-$STAMP"
	fi
	cat > "$dest"
	echo "  creado     $dest"
}

# ---------------------------------------------------------------------------
# 1. daemon NCam
# ---------------------------------------------------------------------------
if [ "$DO_DAEMON" = "1" ]; then
	echo "Servicio del daemon:"
	if [ ! -x "$NCAM_BIN" ]; then
		echo "  aviso: no existe $NCAM_BIN; instálalo con 'sudo devtools/install-daemon.sh'"
	fi
	if [ ! -f "$NCAM_CONFDIR/ncam.conf" ]; then
		echo "  aviso: no existe $NCAM_CONFDIR/ncam.conf (copia el ejemplo de Distribution/doc/example/)"
	fi

	# ¿el binario necesita -f para quedarse en primer plano?
	#   builds sin STAPI: primer plano por defecto (no acepta -f)
	#   builds con STAPI: demonizan por defecto y sí aceptan -f
	FG_FLAG=""
	if [ -x "$NCAM_BIN" ] && "$NCAM_BIN" --help 2>&1 | grep -q -- "-f, --foreground"; then
		FG_FLAG=" -f"
		echo "  binario con STAPI: se usará -f (primer plano)"
	else
		echo "  binario estándar: ya arranca en primer plano"
	fi

	write_unit "$UNIT_DIR/ncam.service" <<EOF
[Unit]
Description=NCam-NG daemon (cardserver + motor de caché)
Documentation=file://$repo_root/INSTALL.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# primer plano, para que systemd controle el proceso (ncam lo hace así por defecto;
# los binarios con STAPI demonizan y necesitan -f, que se añade automáticamente)
ExecStart=$NCAM_BIN$FG_FLAG -c $NCAM_CONFDIR
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
# el daemon necesita permisos sobre tarjetas/lectores si los usas:
# ambient capabilities para tarjetas USB/serial en lugar de correr como root
AmbientCapabilities=CAP_SYS_RAWIO CAP_SYS_ADMIN
LimitNOFILE=16384

[Install]
WantedBy=multi-user.target
EOF
fi

# ---------------------------------------------------------------------------
# 2. panel NCam-NG
# ---------------------------------------------------------------------------
if [ "$DO_PANEL" = "1" ]; then
	echo "Servicio del panel:"
	if [ ! -d "$PANEL_DIR/backend/app" ]; then
		echo "  error: no encuentro el panel en $PANEL_DIR (usa PANEL_DIR=/ruta/al/panel)" >&2
		exit 1
	fi
	if [ ! -x "$PANEL_DIR/.venv/bin/python" ]; then
		echo "  aviso: no hay entorno virtual en $PANEL_DIR/.venv"
		echo "         prepáralo con: devtools/install-panel.sh"
	fi

	write_unit "$UNIT_DIR/ncam-panel.service" <<EOF
[Unit]
Description=NCam-NG Panel (API + web de gestión)
Documentation=file://$repo_root/INSTALL.md
After=network-online.target
Wants=network-online.target
# el panel arranca aunque el daemon esté caído (solo muestra "WebIf no disponible")

[Service]
Type=simple
WorkingDirectory=$PANEL_DIR
Environment=PYTHONPATH=$PANEL_DIR/backend
Environment=NCAM_PANEL_HOST=$PANEL_HOST
Environment=NCAM_PANEL_PORT=$PANEL_PORT
ExecStart=$panel_python -m uvicorn app.main:app --host $PANEL_HOST --port $PANEL_PORT
Restart=on-failure
RestartSec=5
# el panel lee panel/.env por su cuenta, pero las variables de arriba mandan

[Install]
WantedBy=multi-user.target
EOF
fi

# ---------------------------------------------------------------------------
# 3. activar
# ---------------------------------------------------------------------------
echo
echo "Recargando systemd..."
systemctl daemon-reload

if [ "$DO_DAEMON" = "1" ]; then
	systemctl enable ncam.service >/dev/null 2>&1 && echo "  habilitado ncam.service (arranca con el servidor)"
fi
if [ "$DO_PANEL" = "1" ]; then
	systemctl enable ncam-panel.service >/dev/null 2>&1 && echo "  habilitado ncam-panel.service (arranca con el servidor)"
fi

if [ "$DO_START" = "1" ]; then
	echo
	echo "Arrancando servicios..."
	for svc in ncam ncam-panel; do
		[ "$svc" = "ncam" ] && [ "$DO_DAEMON" != "1" ] && continue
		[ "$svc" = "ncam-panel" ] && [ "$DO_PANEL" != "1" ] && continue
		if systemctl is-active --quiet "$svc"; then
			systemctl restart "$svc" || true
			echo "  reiniciado $svc"
		else
			# si había un proceso manual escuchando en el mismo puerto, avisamos
			systemctl start "$svc" || {
				echo "  error al arrancar $svc:" >&2
				systemctl --no-pager -l status "$svc" | head -20 >&2
				echo "  ¿tienes un proceso manual usando el mismo puerto? detállo con:" >&2
				echo "     sudo ss -ltnp | grep -E '8080|8181'" >&2
			}
		fi
	done
fi

echo
echo "Estado:"
systemctl --no-pager --lines=0 status ncam.service ncam-panel.service 2>/dev/null | grep -E "●|Active:" || true

cat <<'EOF'

Comandos útiles:
  sudo systemctl status ncam ncam-panel      # estado
  sudo journalctl -u ncam -f                 # log del daemon en vivo
  sudo journalctl -u ncam-panel -f           # log del panel en vivo
  sudo systemctl restart ncam-panel          # tras cambiar panel/.env
  sudo systemctl stop ncam ncam-panel        # detener

Ya puedes cerrar la terminal: los dos siguen funcionando y arrancan con el servidor.
EOF
