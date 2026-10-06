#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: instalador de los paquetes .deb
#
#   sudo devtools/install-deb.sh                    # última release publicada
#   sudo devtools/install-deb.sh --release v2.0.0   # una release concreta
#   sudo devtools/install-deb.sh --local dist/      # .deb ya descargados
#   sudo devtools/install-deb.sh --panel-only       # solo el panel
#   devtools/install-deb.sh --download-only --dir /tmp/ncam  # solo descargar
#
# Repositorio de las releases:
#   https://github.com/TalaveraSama/Ncam_Fork/releases
# ---------------------------------------------------------------------------
set -e

REPO="TalaveraSama/Ncam_Fork"
RELEASE="latest"
LOCAL_DIR=""
ONLY=""
DL_ONLY=0
DL_DIR=""
ASSUME_YES=0
KEEP=0

ARCH="$(dpkg --print-architecture 2>/dev/null || dpkg-architecture -qDEB_HOST_ARCH 2>/dev/null || echo amd64)"

usage() {
	awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

while [ $# -gt 0 ]; do
	case "$1" in
		--release)       RELEASE="${2:?falta la versión}"; shift 2 ;;
		--local)         LOCAL_DIR="${2:?falta la carpeta}"; shift 2 ;;
		--repo)          REPO="${2:?falta owner/repo}"; shift 2 ;;
		--arch)          ARCH="${2:?falta la arquitectura}"; shift 2 ;;
		--dir)           DL_DIR="${2:?falta la carpeta}"; shift 2 ;;
		--daemon-only)   ONLY="daemon"; shift ;;
		--panel-only)    ONLY="panel"; shift ;;
		--download-only) DL_ONLY=1; shift ;;
		--keep)          KEEP=1; shift ;;
		-y|--yes)        ASSUME_YES=1; shift ;;
		-h|--help)       usage; exit 0 ;;
		*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
	esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. permisos (para instalar hace falta root)
# ---------------------------------------------------------------------------
if [ "$DL_ONLY" = "0" ] && [ "$(id -u)" != "0" ]; then
	if command -v sudo >/dev/null 2>&1; then
		say "==> se necesitan permisos de root; reintentando con sudo"
		exec sudo -- "$0" "$@"
	else
		die "ejecuta este instalador como root (sudo $0)"
	fi
fi

command -v dpkg-deb >/dev/null 2>&1 || die "falta dpkg-deb (no parece un sistema Debian/Ubuntu)"

# ---------------------------------------------------------------------------
# 1. conseguir los .deb
# ---------------------------------------------------------------------------
if [ -z "$DL_DIR" ]; then
	DL_DIR="$(mktemp -d /tmp/ncam-ng-deb.XXXXXX)"
	KEEP=1
fi
mkdir -p "$DL_DIR"

download_asset() {   # download_asset <nombre> <url>
	name="$1"; url="$2"; dest="$DL_DIR/$name"
	if [ -s "$dest" ] && dpkg-deb --info "$dest" >/dev/null 2>&1; then
		say "    ya descargado: $name"
		return 0
	fi
	say "    descargando $name"
	if command -v curl >/dev/null 2>&1; then
		curl -fL --retry 3 --connect-timeout 15 -o "$dest.part" "$url" || return 1
	elif command -v wget >/dev/null 2>&1; then
		wget -q -O "$dest.part" "$url" || return 1
	else
		die "necesito curl o wget para descargar los paquetes"
	fi
	mv "$dest.part" "$dest"
	dpkg-deb --info "$dest" >/dev/null 2>&1 || die "$name no es un paquete .deb válido"

	# comprobación de integridad si la release publica SHA256SUMS
	if [ -f "$DL_DIR/SHA256SUMS" ] && command -v sha256sum >/dev/null 2>&1; then
		expected=$(awk -v n="$name" '$2 == n || $2 == "./" n {print $1}' "$DL_DIR/SHA256SUMS" | head -n 1)
		if [ -n "$expected" ]; then
			actual=$(sha256sum "$dest" | awk '{print $1}')
			if [ "$expected" != "$actual" ]; then
				rm -f "$dest"
				die "la suma SHA-256 de $name no coincide (descarga defectuosa)"
			fi
			say "    SHA-256 correcto"
		fi
	fi
}

fetch_sums() {   # descarga SHA256SUMS de la release, si existe
	url="$1"
	[ -n "$url" ] || return 0
	command -v sha256sum >/dev/null 2>&1 || return 0
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL --connect-timeout 15 -o "$DL_DIR/SHA256SUMS" "$url" 2>/dev/null || rm -f "$DL_DIR/SHA256SUMS"
	else
		wget -q -O "$DL_DIR/SHA256SUMS" "$url" 2>/dev/null || rm -f "$DL_DIR/SHA256SUMS"
	fi
	[ -s "$DL_DIR/SHA256SUMS" ] && say "    SHA256SUMS de la release descargado"
	return 0
}

if [ -n "$LOCAL_DIR" ]; then
	say "==> usando paquetes locales de $LOCAL_DIR"
	deb_daemon=$(ls -1 "$LOCAL_DIR"/ncam-ng_*_"$ARCH".deb 2>/dev/null | head -n 1 || true)
	deb_panel=$(ls -1 "$LOCAL_DIR"/ncam-ng-panel_*_"$ARCH".deb 2>/dev/null | head -n 1 || true)
	[ -n "$deb_daemon" ] || [ -n "$deb_panel" ] || die "no encontré ncam-ng*_<version>_$ARCH.deb en $LOCAL_DIR"
	if [ -f "$LOCAL_DIR/SHA256SUMS" ] && command -v sha256sum >/dev/null 2>&1; then
		( cd "$LOCAL_DIR" && sha256sum -c --ignore-missing SHA256SUMS >/dev/null 2>&1 ) \
			|| die "la suma SHA-256 de los paquetes de $LOCAL_DIR no coincide (usa --local solo con paquetes íntegros)"
		say "    SHA-256 correcto"
	fi
else
	say "==> buscando la release ($RELEASE) en https://github.com/$REPO/releases"
	API_URL="https://api.github.com/repos/$REPO/releases/$RELEASE"
	ASSETS="$(curl -fsSL --connect-timeout 15 -H 'Accept: application/vnd.github+json' "$API_URL" 2>/dev/null || true)"
	[ -n "$ASSETS" ] || die "no pude consultar la API de GitHub ($API_URL).
       comprueba que la release existe y que tienes conexión"

	if [ "$RELEASE" = "latest" ]; then
		TAG="$(printf '%s' "$ASSETS" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
		say "    última release: ${TAG:-?}"
	fi

	url_of() {   # primer asset cuyo nombre encaje con el patrón dado
		printf '%s' "$ASSETS" \
			| tr ',' '\n' \
			| sed -n 's/.*"browser_download_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
			| grep -E "$1" | head -n 1
	}

	fetch_sums "$(url_of 'SHA256SUMS$')"

	deb_daemon=""; deb_panel=""
	if [ "$ONLY" != "panel" ]; then
		url="$(url_of "ncam-ng_[^/]*_${ARCH}\.deb")"
		[ -n "$url" ] || url="$(url_of "ncam-ng_[^/]*\.deb")"
		[ -n "$url" ] || die "la release no trae el paquete ncam-ng para $ARCH"
		name="$(basename "$url")"
		download_asset "$name" "$url"
		deb_daemon="$DL_DIR/$name"
	fi
	if [ "$ONLY" != "daemon" ]; then
		url="$(url_of "ncam-ng-panel_[^/]*_${ARCH}\.deb")"
		[ -n "$url" ] || url="$(url_of "ncam-ng-panel_[^/]*\.deb")"
		[ -n "$url" ] || die "la release no trae el paquete ncam-ng-panel para $ARCH"
		name="$(basename "$url")"
		download_asset "$name" "$url"
		deb_panel="$DL_DIR/$name"
	fi
fi

if [ "$DL_ONLY" = "1" ]; then
	if [ -n "$LOCAL_DIR" ]; then
		SHOW_DIR="$LOCAL_DIR"
	else
		SHOW_DIR="$DL_DIR"
	fi
	say ""
	say "Paquetes en $SHOW_DIR:"
	ls -1 "$SHOW_DIR"/ncam-ng*.deb 2>/dev/null | sed 's/^/  /'
	say ""
	say "Instalar:  sudo apt install $SHOW_DIR/ncam-ng*.deb"
	exit 0
fi

# ---------------------------------------------------------------------------
# 2. instalar
# ---------------------------------------------------------------------------
files=""
[ -n "$deb_daemon" ] && files="$files $deb_daemon"
[ -n "$deb_panel" ] && files="$files $deb_panel"
[ -n "$files" ] || die "no hay nada que instalar"

say "==> instalando$( [ -n "$deb_daemon" ] && printf ' ncam-ng' )$( [ -n "$deb_panel" ] && printf ' ncam-ng-panel' )"

APT_OPTS="-o Dpkg::Options::=--force-confold"
if command -v apt-get >/dev/null 2>&1; then
	if [ "$ASSUME_YES" = "1" ]; then
		DEBIAN_FRONTEND=noninteractive apt-get install -y $APT_OPTS $files
	else
		apt-get install $APT_OPTS $files
	fi
else
	# sin apt: dpkg y, si falta alguna dependencia, se avisa
	dpkg -i $files || {
		say "==> faltan dependencias; intentando resolverlas"
		command -v apt-get >/dev/null 2>&1 && apt-get -f install -y || \
			die "instala a mano las dependencias que faltan y repite: dpkg -i $files"
	}
fi

# ---------------------------------------------------------------------------
# 3. resumen
# ---------------------------------------------------------------------------
say ""
command -v dpkg-query >/dev/null 2>&1 && dpkg-query -W -f='  instalado: ${Package} ${Version}\n' ncam-ng ncam-ng-panel 2>/dev/null || true
say ""
if [ "$ONLY" != "panel" ]; then
	say "Daemon:   systemctl status ncam     |  journalctl -u ncam -f"
	say "          WebIf:    http://TU_IP:8181   (usuario admin, contraseña en /etc/ncam/ncam.conf)"
	say "          Caché:    http://TU_IP:8181/cacheengine.html"
fi
if [ "$ONLY" != "daemon" ]; then
	say "Panel:    systemctl status ncam-panel  |  journalctl -u ncam-panel -f"
	say "          Web:      http://TU_IP:8080"
	say "          Config:   /opt/ncam-ng-panel/.env"
	say "          Datos:    /var/lib/ncam-ng-panel/panel.db"
	say "          Ajustes:  sudo ncam-ng-panel-setup --online"
fi
if [ "$KEEP" = "0" ]; then
	rm -f "$files"
	say ""
	say "Paquetes temporales borrados (usa --keep para conservarlos)"
else
	say ""
	say "Paquetes en: $DL_DIR"
fi
exit 0
