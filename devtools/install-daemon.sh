#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: instala el daemon compilado en este repositorio
#
#   sudo devtools/install-daemon.sh                  # binario -> /usr/local/bin/ncam
#   sudo devtools/install-daemon.sh --with-config    # y copia los ejemplos de config
#   sudo PREFIX=/opt/ncam devtools/install-daemon.sh # otro prefijo
#   sudo CONFDIR=/etc/ncam devtools/install-daemon.sh
#
# Selecciona siempre el binario SIN depurar (nunca el *.debug) y no sobrescribe
# ninguna configuración existente.
# ---------------------------------------------------------------------------
set -e

PREFIX="${PREFIX:-/usr/local}"
BINDIR="$PREFIX/bin"
CONFDIR="${CONFDIR:-$PREFIX/etc}"
WITH_CONFIG=0

case "$1" in
	--with-config) WITH_CONFIG=1 ;;
	-h|--help)
		sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
		exit 0
		;;
	"") ;;
	*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
esac

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dist="$repo_root/Distribution"

# el binario final más reciente, excluyendo siempre el *.debug
binary=$(ls -1t "$dist"/ncam-Unofficial-*-x86_64-linux-gnu 2>/dev/null | grep -v '\.debug$' | head -n 1 || true)

# si existe, se prefiere el binario del commit actual (evita instalar uno antiguo)
rev=""
if command -v git >/dev/null 2>&1 && [ -d "$repo_root/.git" ]; then
	rev=$(git -C "$repo_root" rev-parse --short HEAD 2>/dev/null || true)
	if [ -n "$rev" ]; then
		exact=$(ls -1t "$dist"/ncam-Unofficial-git"$rev"-*-x86_64-linux-gnu 2>/dev/null | grep -v '\.debug$' | head -n 1 || true)
		[ -n "$exact" ] && binary="$exact"
	fi
fi
if [ -z "$binary" ] || [ ! -f "$binary" ]; then
	echo "error: no se encontró ningún binario compilado en $dist" >&2
	echo "       compílalo primero con: make -j\"\$(nproc)\"" >&2
	exit 1
fi

# permisos
if [ -d "$BINDIR" ]; then
	[ -w "$BINDIR" ] || { echo "error: $BINDIR no es escribible (¿te falta sudo?)" >&2; exit 1; }
elif [ ! -w "$PREFIX" ] && [ ! -w "$(dirname -- "$PREFIX")" ]; then
	echo "error: no se puede crear $BINDIR (¿te falta sudo?)" >&2
	exit 1
fi

install -d "$BINDIR"
install -m 0755 "$binary" "$BINDIR/ncam"
echo "binario instalado : $BINDIR/ncam  <- $(basename -- "$binary")"

if [ -n "$rev" ]; then
	case "$(basename -- "$binary")" in
		*"git$rev"*) ;;
		*) echo "aviso: el binario instalado no es del commit actual ($rev);" >&2
		   echo "       recompila con 'make -j\"\$(nproc)\"' para actualizarlo" >&2 ;;
	esac
fi

if [ "$WITH_CONFIG" = "1" ]; then
	install -d "$CONFDIR"
	for file in ncam.conf ncam.server ncam.user ncam.services; do
		source="$repo_root/Distribution/doc/example/$file"
		[ -f "$source" ] || continue
		if [ -e "$CONFDIR/$file" ]; then
			echo "conservado        : $CONFDIR/$file (ya existía)"
		else
			install -m 0644 "$source" "$CONFDIR/$file"
			echo "configuración     : $CONFDIR/$file"
		fi
	done
fi

echo
echo "Siguientes pasos:"
echo "  1) revisa [webif] y [cache] en $CONFDIR/ncam.conf"
echo "  2) arranca:  $BINDIR/ncam -c $CONFDIR -b -B /var/run/ncam.pid"
echo "  3) comprueba: curl --digest -u admin:TU_CLAVE http://127.0.0.1:8181/cacheengine.html"
