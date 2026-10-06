#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: instalador de los paquetes .deb
#
#   sudo ncam-ng-install-deb                    # última release publicada
#   sudo ncam-ng-install-deb --release v2.0.0   # una release concreta
#   sudo ncam-ng-install-deb --local dist/      # .deb ya descargados
#   sudo ncam-ng-install-deb --panel-only       # solo el panel
#   ncam-ng-install-deb --download-only         # solo descargar (sin root)
#   ncam-ng-install-deb --list-assets           # ver los adjuntos de la release
#
# Repositorio de las releases:
#   https://github.com/TalaveraSama/Ncam_Fork/releases
#
# En un clon del repositorio este mismo script está en devtools/install-deb.sh.
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
LIST_ASSETS=0

ARCH="$(dpkg --print-architecture 2>/dev/null || dpkg-architecture -qDEB_HOST_ARCH 2>/dev/null || echo amd64)"

usage() {
	awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

abs_path() {   # ruta absoluta (apt exige rutas que empiecen por / o ./)
	case "$1" in
		/*) printf '%s' "$1" ;;
		*) printf '%s/%s' "$(pwd)" "$1" ;;
	esac
}

self_path() {   # ruta absoluta de este script (para poder re-ejecutarlo con sudo)
	case "$0" in
		*/*) printf '%s' "$0" ;;
		*) command -v -- "$0" 2>/dev/null || printf '%s/%s' "$(pwd)" "$0" ;;
	esac
}

# ---------------------------------------------------------------------------
# 0. validación de las opciones
#
# Se hace ANTES de pedir sudo: así una errata (--relase) avisa al momento en
# lugar de lanzar una petición de contraseña y un error confuso.
# ---------------------------------------------------------------------------
validate_args() {
	while [ $# -gt 0 ]; do
		case "$1" in
			--release|--local|--repo|--arch|--dir)
				[ -n "$2" ] || { echo "error: $1 necesita un valor (usa --help)" >&2; exit 2; }
				shift 2 ;;
			--daemon-only|--panel-only|--download-only|--keep|-y|--yes|--list-assets|-h|--help)
				shift ;;
			*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
		esac
	done
}
validate_args "$@"

# ---------------------------------------------------------------------------
# 0b. permisos
#
# El re-lanzamiento con sudo tiene que ocurrir ANTES de leer las opciones: si no,
# se perderían al ejecutar de nuevo el script.
# ---------------------------------------------------------------------------
NEED_ROOT=1
for arg in "$@"; do
	case "$arg" in
		--download-only|--list-assets|-h|--help) NEED_ROOT=0 ;;
	esac
done

if [ "$NEED_ROOT" = "1" ] && [ "$(id -u)" != "0" ]; then
	if command -v sudo >/dev/null 2>&1; then
		say "==> se necesitan permisos de root; reintentando con sudo"
		if sudo -- sh "$(self_path)" "$@"; then
			exit 0
		fi
		die "no se pudo completar con sudo; ejecútalo como root:  sudo sh $(self_path)"
	else
		die "ejecuta este instalador como root:  sudo sh $(self_path)"
	fi
fi

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
		--list-assets)   LIST_ASSETS=1; shift ;;
		--keep)          KEEP=1; shift ;;
		-y|--yes)        ASSUME_YES=1; shift ;;
		-h|--help)       usage; exit 0 ;;
		*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
	esac
done

command -v dpkg-deb >/dev/null 2>&1 || die "falta dpkg-deb (¿seguro que es Debian/Ubuntu?)"

# ---------------------------------------------------------------------------
# 1. descarga
# ---------------------------------------------------------------------------
AUTO_DIR=0
if [ -z "$DL_DIR" ]; then
	DL_DIR="$(mktemp -d /tmp/ncam-ng-deb.XXXXXX)"
	AUTO_DIR=1
fi
mkdir -p "$DL_DIR"

verify_sha256() {   # verify_sha256 <fichero> <nombre>
	file="$1"; name="$2"
	[ -f "$DL_DIR/SHA256SUMS" ] || return 0
	command -v sha256sum >/dev/null 2>&1 || return 0
	expected=$(awk -v n="$name" '$2 == n || $2 == "./" n {print $1}' "$DL_DIR/SHA256SUMS" | head -n 1)
	[ -n "$expected" ] || return 0
	actual=$(sha256sum "$file" | awk '{print $1}')
	if [ "$expected" != "$actual" ]; then
		rm -f "$file"
		die "la suma SHA-256 de $name no coincide (descarga defectuosa)"
	fi
	say "    SHA-256 correcto"
}

fetch_url() {   # fetch_url <url> <destino> [cabecera]
	url="$1"; dest="$2"
	if command -v curl >/dev/null 2>&1; then
		curl -fL --retry 3 --retry-all-errors --connect-timeout 20 \
			${3:+-H "$3"} -o "$dest.part" "$url" 2>/dev/null
	elif command -v wget >/dev/null 2>&1; then
		wget -q --tries=3 -O "$dest.part" "$url" 2>/dev/null
	else
		die "necesito curl o wget para descargar los paquetes"
	fi
}

download_asset() {   # download_asset <nombre> <url> [<url-api>]
	name="$1"; url="$2"; apiurl="${3:-}"; dest="$DL_DIR/$name"
	if [ -s "$dest" ] && dpkg-deb --info "$dest" >/dev/null 2>&1; then
		say "    ya descargado: $name"
		verify_sha256 "$dest" "$name"
		return 0
	fi
	say "    descargando $name"

	if [ -n "$url" ] && fetch_url "$url" "$dest"; then
		:
	elif [ -n "$apiurl" ] && fetch_url "$apiurl" "$dest" "Accept: application/octet-stream"; then
		# si la red bloquea el servidor de adjuntos (release-assets.*), la API
		# de GitHub sirve el mismo fichero con esta cabecera
		say "    (descargado a través de la API de GitHub)"
	else
		rm -f "$dest.part"
		die "no pude descargar $name.
       Si tu red bloquea las descargas de GitHub, prueba:
         gh release download --repo $REPO --pattern '$name' --dir .
       o descarga el paquete a mano desde:
         https://github.com/$REPO/releases"
	fi

	mv "$dest.part" "$dest"
	dpkg-deb --info "$dest" >/dev/null 2>&1 || die "$name no es un paquete .deb válido"
	verify_sha256 "$dest" "$name"
}

fetch_sums() {   # descarga SHA256SUMS de la release, si existe
	url="$1"
	[ -n "$url" ] || return 0
	command -v sha256sum >/dev/null 2>&1 || return 0
	fetch_url "$url" "$DL_DIR/SHA256SUMS" 2>/dev/null || true
	if [ -s "$DL_DIR/SHA256SUMS.part" ]; then
		mv "$DL_DIR/SHA256SUMS.part" "$DL_DIR/SHA256SUMS"
		say "    SHA256SUMS de la release descargado"
	else
		rm -f "$DL_DIR/SHA256SUMS.part" "$DL_DIR/SHA256SUMS"
	fi
	return 0
}

# tabla de adjuntos de la release: "nombre<TAB>url-descarga<TAB>url-api"
asset_table() {
	printf '%s' "$ASSETS" | tr ',' '\n' \
		| sed -n 's/^[[:space:]]*"\(url\|name\|browser_download_url\)"[[:space:]]*:[[:space:]]*"\([^"]*\)"[[:space:]]*$/\1 \2/p' \
		| awk '
			$1 == "url" { api = $2 }
			$1 == "name" { name = $2 }
			$1 == "browser_download_url" {
				if (name != "") { print name "\t" $2 "\t" api }
				name = ""; api = ""
			}'
}

asset_of() {   # asset_of <patrón> -> primera fila cuyo nombre encaje
	asset_table | awk -v pat="$1" -F'\t' '$1 ~ pat { print; exit }'
}

if [ -n "$LOCAL_DIR" ]; then
	say "==> usando paquetes locales de $LOCAL_DIR"
	deb_daemon=$(ls -1 "$LOCAL_DIR"/ncam-ng_*_"$ARCH".deb 2>/dev/null | head -n 1 || true)
	deb_panel=$(ls -1 "$LOCAL_DIR"/ncam-ng-panel_*_"$ARCH".deb 2>/dev/null | head -n 1 || true)
	[ -n "$deb_daemon" ] || [ -n "$deb_panel" ] || die "no encontré ncam-ng*_<version>_$ARCH.deb en $LOCAL_DIR"
	[ -n "$deb_daemon" ] && deb_daemon="$(abs_path "$deb_daemon")"
	[ -n "$deb_panel" ] && deb_panel="$(abs_path "$deb_panel")"
	if [ -f "$LOCAL_DIR/SHA256SUMS" ] && command -v sha256sum >/dev/null 2>&1; then
		( cd "$LOCAL_DIR" && sha256sum -c --ignore-missing SHA256SUMS >/dev/null 2>&1 ) \
			|| die "la suma SHA-256 de los paquetes de $LOCAL_DIR no coincide (usa --local solo con paquetes íntegros)"
		say "    SHA-256 correcto"
	fi
else
	say "==> buscando la release ($RELEASE) en https://github.com/$REPO/releases"
	API="https://api.github.com/repos/$REPO/releases"
	if [ "$RELEASE" = "latest" ]; then
		API_URL="$API/latest"
	else
		# por etiqueta (v2.0.0) o por identificador numérico
		API_URL="$API/tags/$RELEASE"
	fi
	fetch_json() {
		curl -fsSL --connect-timeout 20 -H 'Accept: application/vnd.github+json' "$1" 2>/dev/null || true
	}
	ASSETS="$(fetch_json "$API_URL")"
	if [ -z "$ASSETS" ] && [ "$RELEASE" != "latest" ]; then
		ASSETS="$(fetch_json "$API/$RELEASE")"   # por si es un id numérico
	fi
	[ -n "$ASSETS" ] || die "no pude consultar la API de GitHub ($API_URL).
       comprueba que la release existe (etiqueta $RELEASE) y que hay conexión"

	if [ "$RELEASE" = "latest" ]; then
		TAG="$(printf '%s' "$ASSETS" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
		say "    última release: ${TAG:-?}"
	fi

	if [ "$LIST_ASSETS" = "1" ]; then
		say ""
		say "Adjuntos de la release ${TAG:-$RELEASE}:"
		asset_table | cut -f1,2 | sed 's/^/  /'
		exit 0
	fi

	fetch_sums "$(asset_of 'SHA256SUMS$' | cut -f2)"

	deb_daemon=""; deb_panel=""
	if [ "$ONLY" != "panel" ]; then
		line="$(asset_of "ncam-ng_[^/]*_${ARCH}[.]deb")"
		[ -n "$line" ] || line="$(asset_of "ncam-ng_[^/]*[.]deb")"
		[ -n "$line" ] || die "la release no trae el paquete ncam-ng para $ARCH"
		name="$(printf '%s' "$line" | cut -f1)"
		download_asset "$name" "$(printf '%s' "$line" | cut -f2)" "$(printf '%s' "$line" | cut -f3)"
		deb_daemon="$DL_DIR/$name"
	fi
	if [ "$ONLY" != "daemon" ]; then
		line="$(asset_of "ncam-ng-panel_[^/]*_${ARCH}[.]deb")"
		[ -n "$line" ] || line="$(asset_of "ncam-ng-panel_[^/]*[.]deb")"
		[ -n "$line" ] || die "la release no trae el paquete ncam-ng-panel para $ARCH"
		name="$(printf '%s' "$line" | cut -f1)"
		download_asset "$name" "$(printf '%s' "$line" | cut -f2)" "$(printf '%s' "$line" | cut -f3)"
		deb_panel="$DL_DIR/$name"
	fi
fi

if [ "$DL_ONLY" = "1" ]; then
	SHOW_DIR="$DL_DIR"
	[ -n "$LOCAL_DIR" ] && SHOW_DIR="$LOCAL_DIR"
	say ""
	say "Paquetes en $SHOW_DIR:"
	ls -1 "$SHOW_DIR"/ncam-ng*.deb 2>/dev/null | sed 's/^/  /'
	say ""
	say "Instalar:  sudo apt install $SHOW_DIR/ncam-ng*.deb"
	exit 0
fi

# ---------------------------------------------------------------------------
# 2. instalación
# ---------------------------------------------------------------------------
files=""
[ -n "$deb_daemon" ] && files="$files $deb_daemon"
[ -n "$deb_panel" ] && files="$files $deb_panel"
[ -n "$files" ] || die "no hay nada que instalar"

say "==> instalando$( [ -n "$deb_daemon" ] && printf ' ncam-ng' )$( [ -n "$deb_panel" ] && printf ' ncam-ng-panel' )"

# --force-confold: nunca pisa la configuración existente del usuario.
# --reinstall: si ya está instalada la misma versión, apt la reinstalaría sin
# hacer nada; con esta opción se vuelven a ejecutar los scripts del paquete y el
# servicio queda reparado (útil si algo se estropeó tras una actualización).
APT_OPTS="-o Dpkg::Options::=--force-confold"
REINSTALL=""
apt-get --version >/dev/null 2>&1 && REINSTALL="--reinstall"
if command -v apt-get >/dev/null 2>&1; then
	if [ "$ASSUME_YES" = "1" ]; then
		DEBIAN_FRONTEND=noninteractive apt-get install -y $REINSTALL $APT_OPTS $files
	else
		apt-get install $REINSTALL $APT_OPTS $files
	fi
else
	dpkg -i $files || {
		say "==> faltan dependencias; intentando resolverlas"
		apt-get -f install -y || die "instala a mano lo que falte y repite:  dpkg -i $files"
	}
fi

# ---------------------------------------------------------------------------
# 3. resumen
# ---------------------------------------------------------------------------
say ""
command -v dpkg-query >/dev/null 2>&1 && \
	dpkg-query -W -f='  instalado: ${Package} ${Version}\n' ncam-ng ncam-ng-panel 2>/dev/null || true
say ""
if [ "$ONLY" != "panel" ]; then
	say "Daemon:   systemctl status ncam   |  journalctl -u ncam -f"
	say "          WebIf:  http://TU_IP:8181   (usuario admin; contraseña en /etc/ncam/ncam.conf)"
	say "          Caché:  http://TU_IP:8181/cacheengine.html"
fi
if [ "$ONLY" != "daemon" ]; then
	say "Panel:    systemctl status ncam-panel   |  journalctl -u ncam-panel -f"
	say "          Web:     http://TU_IP:8080"
	say "          Ajustes: /opt/ncam-ng-panel/.env   |   Datos: /var/lib/ncam-ng-panel/panel.db"
	say "          Entorno: sudo ncam-ng-panel-setup --online"
fi
say ""
if [ -n "$LOCAL_DIR" ]; then
	say "Paquetes: $LOCAL_DIR"
elif [ "$KEEP" = "1" ] || [ "$AUTO_DIR" = "0" ]; then
	say "Paquetes: $DL_DIR"
else
	rm -rf "$DL_DIR"
	say "Descargas temporales borradas (usa --keep para conservarlas)"
fi
exit 0
