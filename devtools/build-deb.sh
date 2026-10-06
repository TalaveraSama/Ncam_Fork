#!/bin/sh
# ---------------------------------------------------------------------------
# NCam-NG :: construye los paquetes .deb (daemon y panel)
#
#   devtools/build-deb.sh                    # versión 2.0.0, compila si hace falta
#   devtools/build-deb.sh --version 2.1.0    # otra versión
#   devtools/build-deb.sh --no-build         # usa el binario ya compilado
#   devtools/build-deb.sh --with-wheels      # incluye las dependencias de Python
#   devtools/build-deb.sh --wheels-python "3.10 3.12"   # versiones cubiertas sin conexión
#   devtools/build-deb.sh --arch amd64
#
# Resultado en dist/:
#   ncam-ng_<version>_<arch>.deb          daemon + configuración + servicio systemd
#   ncam-ng-panel_<version>_<arch>.deb    panel + servicio systemd + ajustes
# ---------------------------------------------------------------------------
set -e

VERSION="2.2.1"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
DO_BUILD=1
WITH_WHEELS=0
WHEELS_PYTHONS="3.10 3.11 3.12"
MAINTAINER="TalaveraSama <108017945+TalaveraSama@users.noreply.github.com>"

while [ $# -gt 0 ]; do
	case "$1" in
		--version)     VERSION="${2:?falta la versión}"; shift 2 ;;
		--arch)        ARCH="${2:?falta la arquitectura}"; shift 2 ;;
		--no-build)    DO_BUILD=0; shift ;;
		--with-wheels) WITH_WHEELS=1; shift ;;
		--wheels-python) WHEELS_PYTHONS="${2:?falta la lista de versiones}"; shift 2 ;;
		-h|--help)
			awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
			exit 0
			;;
		*) echo "opción no reconocida: $1 (usa --help)" >&2; exit 2 ;;
	esac
done

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

packaging="$repo_root/packaging"
dist="$repo_root/dist"
work="$repo_root/build/deb"

say() { printf '%s\n' "$*"; }
command -v dpkg-deb >/dev/null 2>&1 || { echo "error: falta dpkg-deb (paquete dpkg-dev)" >&2; exit 1; }

install_doc() {   # install_doc <origen> <destino>
	[ -f "$1" ] && install -m 0644 "$1" "$2" || true
}

# ---------------------------------------------------------------------------
# 1. binario del daemon
# ---------------------------------------------------------------------------
if [ "$DO_BUILD" = "1" ]; then
	say "==> compilando el daemon"
	make -j"$(nproc)" >/dev/null
fi

binary=$(ls -1t Distribution/ncam-Unofficial-*-x86_64-linux-gnu 2>/dev/null | grep -v '\.debug$' | head -n 1 || true)
if [ -z "$binary" ] || [ ! -f "$binary" ]; then
	echo "error: no hay binario compilado (ejecuta 'make -j\$(nproc)' o quita --no-build)" >&2
	exit 1
fi
say "    binario: $binary"

# versión mínima de glibc que necesita el binario (para el campo Depends)
glibc_req=$(objdump -T "$binary" 2>/dev/null | grep -o 'GLIBC_[0-9.]*' \
	| sed 's/^GLIBC_//' | sort -V | tail -n 1)
[ -n "$glibc_req" ] || glibc_req="2.28"
say "    requiere glibc >= $glibc_req"

rm -rf "$work"
mkdir -p "$dist" "$work"

# ---------------------------------------------------------------------------
# 2. paquete del daemon: ncam-ng
# ---------------------------------------------------------------------------
say "==> empaquetando el daemon"
pkg="$work/ncam-ng"
mkdir -p "$pkg/DEBIAN" "$pkg/usr/bin" "$pkg/etc/ncam" "$pkg/lib/systemd/system" \
         "$pkg/usr/share/doc/ncam-ng/examples"

install -m 0755 "$binary" "$pkg/usr/bin/ncam"
# el instalador de releases, para poder actualizar con un solo comando
install -m 0755 "$repo_root/devtools/install-deb.sh" "$pkg/usr/bin/ncam-ng-install-deb"
# gestor de servicios y atajos de consola (restart-ncam, restart-ncam-panel...)
install -m 0755 "$packaging/ncam-ng-ctl.sh" "$pkg/usr/bin/ncam-ng-ctl"
for alias in restart-ncam restart-ncam-panel ncam-ng-status; do
	ln -sf ncam-ng-ctl "$pkg/usr/bin/$alias"
done
install -m 0644 "$packaging/ncam.conf" "$pkg/etc/ncam/ncam.conf"
install -m 0644 "$packaging/ncam.service" "$pkg/lib/systemd/system/ncam.service"

for file in ncam.conf ncam.server ncam.user ncam.services ncam.srvid2; do
	install_doc "Distribution/doc/example/$file" "$pkg/usr/share/doc/ncam-ng/examples/$file"
done
install_doc README.md    "$pkg/usr/share/doc/ncam-ng/README.md"
install_doc CHANGELOG.md "$pkg/usr/share/doc/ncam-ng/CHANGELOG.md"
install_doc INSTALL.md   "$pkg/usr/share/doc/ncam-ng/INSTALL.md"

install -m 0755 "$packaging/ncam-ng.postinst" "$pkg/DEBIAN/postinst"
install -m 0755 "$packaging/ncam-ng.prerm"    "$pkg/DEBIAN/prerm"
install -m 0755 "$packaging/ncam-ng.postrm"   "$pkg/DEBIAN/postrm"
printf '%s\n' /etc/ncam/ncam.conf > "$pkg/DEBIAN/conffiles"

sed "s/@VERSION@/$VERSION/; s/@ARCH@/$ARCH/; s|@SIZE@|$(du -sk "$pkg" | cut -f1)|; \
     s|@MAINTAINER@|$MAINTAINER|; s|@GLIBC@|$glibc_req|" \
	"$packaging/ncam-ng.control.in" > "$pkg/DEBIAN/control"

dpkg-deb --build --root-owner-group "$pkg" "$dist/ncam-ng_${VERSION}_${ARCH}.deb" >/dev/null
say "    dist/ncam-ng_${VERSION}_${ARCH}.deb"

# ---------------------------------------------------------------------------
# 3. paquete del panel: ncam-ng-panel
# ---------------------------------------------------------------------------
say "==> empaquetando el panel"
pkg="$work/ncam-ng-panel"
mkdir -p "$pkg/DEBIAN" "$pkg/opt/ncam-ng-panel" "$pkg/lib/systemd/system" \
         "$pkg/usr/bin" "$pkg/usr/share/doc/ncam-ng-panel" "$pkg/opt/ncam-ng-panel/docs"

for item in backend frontend tools requirements.txt run.sh; do
	[ -e "panel/$item" ] || continue
	cp -a "panel/$item" "$pkg/opt/ncam-ng-panel/"
done
find "$pkg/opt/ncam-ng-panel" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$pkg/opt/ncam-ng-panel" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$pkg/opt/ncam-ng-panel/backend/data" "$pkg/opt/ncam-ng-panel/.venv" "$pkg/opt/ncam-ng-panel/.env" 2>/dev/null || true

printf '%s\n' "$VERSION" > "$pkg/opt/ncam-ng-panel/VERSION"
install -m 0644 "$packaging/ncam-panel.service" "$pkg/lib/systemd/system/ncam-panel.service"
install -m 0755 "$packaging/ncam-panel-setup.sh" "$pkg/usr/bin/ncam-ng-panel-setup"
install -m 0755 "$packaging/ncam-panel-setup.sh" "$pkg/opt/ncam-ng-panel/setup-install.sh"
install_doc panel/README.md "$pkg/usr/share/doc/ncam-ng-panel/README.md"
install_doc INSTALL.md      "$pkg/usr/share/doc/ncam-ng-panel/INSTALL.md"
install_doc CHANGELOG.md    "$pkg/usr/share/doc/ncam-ng-panel/CHANGELOG.md"
install_doc docs/ajustes.md "$pkg/usr/share/doc/ncam-ng-panel/ajustes.md"
install_doc docs/ajustes.md "$pkg/opt/ncam-ng-panel/docs/ajustes.md"

if [ "$WITH_WHEELS" = "1" ]; then
	# Las ruedas con código compilado (httptools, uvloop, pydantic-core…) son
	# específicas de cada versión de Python, así que se descargan para todas las
	# versiones soportadas: Ubuntu 22.04 (3.10), Debian 12 (3.11), Ubuntu 24.04
	# (3.12). En otras versiones el instalador usa PyPI automáticamente.
	wheels_dir="$pkg/usr/lib/ncam-ng-panel/wheels"
	mkdir -p "$wheels_dir"
	say "    descargando dependencias de Python para: $WHEELS_PYTHONS"
	have=0
	for pyver in $WHEELS_PYTHONS; do
		if python3 -m pip download -q --only-binary=:all: --python-version "$pyver" \
				-r panel/requirements.txt -d "$wheels_dir"; then
			have=1
		else
			echo "    aviso: sin ruedas para Python $pyver (usará PyPI)" >&2
		fi
	done
	if [ "$have" = "1" ]; then
		printf '%s\n' "$WHEELS_PYTHONS" > "$wheels_dir/PYTHONS"
		say "    ruedas incluidas: $(du -sh "$wheels_dir" | cut -f1) ($(ls "$wheels_dir" | wc -l) ficheros)"
	else
		echo "    aviso: no se pudieron descargar las ruedas; el panel usará PyPI" >&2
		rm -rf "$wheels_dir"
	fi
fi

install -m 0755 "$packaging/ncam-ng-panel.postinst" "$pkg/DEBIAN/postinst"
install -m 0755 "$packaging/ncam-ng-panel.prerm"    "$pkg/DEBIAN/prerm"
install -m 0755 "$packaging/ncam-ng-panel.postrm"   "$pkg/DEBIAN/postrm"

sed "s/@VERSION@/$VERSION/; s/@ARCH@/$ARCH/; s|@SIZE@|$(du -sk "$pkg" | cut -f1)|; s|@MAINTAINER@|$MAINTAINER|" \
	"$packaging/ncam-ng-panel.control.in" > "$pkg/DEBIAN/control"

dpkg-deb --build --root-owner-group "$pkg" "$dist/ncam-ng-panel_${VERSION}_${ARCH}.deb" >/dev/null
say "    dist/ncam-ng-panel_${VERSION}_${ARCH}.deb"

# ---------------------------------------------------------------------------
# 4. resumen
# ---------------------------------------------------------------------------
say ""
say "Paquetes en dist/:"
for file in "$dist"/*.deb; do
	say "  $(basename "$file")  ($(du -h "$file" | cut -f1))"
done
say ""
say "Instalar:  sudo apt install ./dist/ncam-ng_${VERSION}_${ARCH}.deb ./dist/ncam-ng-panel_${VERSION}_${ARCH}.deb"
say "Revisar:   dpkg-deb --info dist/ncam-ng_${VERSION}_${ARCH}.deb"
