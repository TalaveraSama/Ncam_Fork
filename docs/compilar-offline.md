# Compilar NCam-NG sin conexión (offline)

Guía para compilar el **daemon NCam-NG** en una máquina que **no tiene conexión
a internet**. Todo lo que se necesite (fuente, compilador, librerías de
desarrollo) se prepara en una máquina con conexión y se traslada a la máquina
offline (por USB, SCP, rsync...).

La compilación offline **no cambia el proceso de build**: el mismo `config.sh`
y el mismo `make` que se usan con conexión. Lo único que cambia es cómo
llegamos al punto de tener el compilador y las dependencias installed.

> La guía cubre **solo el daemon** (el servidor de tarjetas en C). El panel
> NCPanel (Python) no se compila; para instalarlo offline ver `INSTALL.md`.

---

## 1. Requisitos de la máquina offline

- **Sistema**: Debian/Ubuntu (o derivado) con `dpkg` y `apt`.
- **Compilador**: `gcc` + `make` (paquete `build-essential`).
- **Librerías de desarrollo** (solo según la configuración que se elija,
  ver [§5 Opcionales](#5-opcionales-dependencias-según-la-configuracion)):
  - `libssl-dev` — solo si se compila con `WITH_SSL` o `USE_SSL=1`
  - `libcurl4-openssl-dev` — solo con `USE_LIBCURL=1`
  - `libusb-1.0-0-dev` — solo con `USE_LIBUSB=1`
  - `libpcsclite-dev` — solo con `USE_PCSC=1`
- **libdvbcsa** — **opcional**; no está en los repositorios de Debian/Ubuntu,
  se compila desde fuente si se quiere usar (ver [§5](#5-opcionales-dependencias-según-la-configuracion)).

**Build mínimo (configuración por defecto): solo `build-essential`.** La
configuración por defecto de `config.h` (que viene commiteada en el repositorio)
ya tiene todo lo necesario activado: WebIf, motor de caché v2 (`CS_CACHEEX`,
`CS_CACHEEX_AIO`), `MODULE_NEWCAMD` (con soporte **multi-CAID**), etc.

---

## 2. Plano A: preparar todo en una máquina con conexión

Hacer esto en una máquina con internet **de la misma distro y versión** que la
máquina offline (así los paquetes son binariamente compatibles).

### 2.1 Descargar la fuente

```bash
# Opción 1: clonar el repositorio
git clone https://github.com/TalaveraSama/Ncam_Fork.git

# Opción 2: tarball sin git (más ligero para transportar)
curl -fsSL -o ncam-fork.tar.gz \
  https://codeload.github.com/TalaveraSama/Ncam_Fork/tar.gz/refs/heads/arena/d81e6546-ncam-fork
```

Empaquetar para transportar:

```bash
tar czf ncam-fork-offline.tar.gz Ncam_Fork        # si se clonó
# o directamente usar el ncam-fork.tar.gz descargado
```

> **Importante:** `config.h` **viene dentro del repositorio** (es el template
> por defecto). `config.sh` lo *edita*, no lo *crea*. Nunca lo borres: sin él
> el `make` falla con `fatal error: config.h: No such file or directory`.

### 2.2 Descargar los paquetes .deb (dependencias)

Con `--download-only` se traen **todos los .deb necesarios, incluidos los
dependientes**, sin instalar nada:

```bash
mkdir -p ~/offline-debs
sudo apt-get install -y --download-only -o Dir::Cache::archives=/home/usuario/offline-debs \
  build-essential
```

Si se quiere SSL (recomendado para cccam y otros módulos):

```bash
sudo apt-get install -y --download-only -o Dir::Cache::archives=/home/usuario/offline-debs \
  build-essential libssl-dev
```

También se pueden añadir las opcionales de una vez
(`libcurl4-openssl-dev libusb-1.0-0-dev libpcsclite-dev`).

Empaquetar para transportar:

```bash
tar czf offline-debs.tar.gz -C /home/usuario offline-debs
```

### 2.3 Transferir a la máquina offline

Por USB, o si hay red local:

```bash
# desde la máquina con conexión
scp ncam-fork-offline.tar.gz offline-debs.tar.gz usuario@offline:~/
```

---

## 3. Instalar las dependencias en la máquina offline

```bash
cd ~
tar xzf offline-debs.tar.gz
sudo apt install ./offline-debs/*.deb
```

`apt install ./...` resuelve el orden de instalación entre los paquetes locales
y, si falta alguna dependencia, lo dice claramente. Si se usa `dpkg -i`
directamente, puede pedir dependencias en orden; en ese caso correr después:

```bash
sudo apt-get -f install   # solo si la máquina offline tiene repositorios locales
```

Comprobar que el toolchain está disponible:

```bash
gcc --version && make --version
```

---

## 4. Compilar

```bash
cd Ncam_Fork        # o el directorio del tarball extraído

# 1) (opcional) configuración. Por defecto config.h ya trae una buena
#    configuración; para mantenerla intacta se puede ejecutar con una
#    opción válida (config.sh sin argumentos muestra la ayuda y termina con
#    error, no es un error del build):
./config.sh --enable WITH_SOFTCAM

# 2) compilar
make -j"$(nproc)"
```

Notas:

- `config.sh` **edita `config.h` en el árbol**; si la máquina offline no tiene
  ninguna preferencia, se puede saltar el paso 1 y compilar directamente
  (`config.h` ya está commiteado con los valores por defecto).
- Si se quiere ver qué tiene activado el binario: `./config.sh --show-enabled`
  (o `-s`).
- Si se cambia la configuración y luego se quiere volver al default:
  `git checkout config.h` (si se usó git) o re-descargar la fuente.

---

## 5. Opcionales: dependencias según la configuración

### 5.1 SSL (libssl-dev) — recomendado

Activar `WITH_SSL` y compilar con `USE_SSL=1`:

```bash
sudo apt install ./offline-debs/*.deb   # con libssl-dev ya descargada
./config.sh --enable WITH_SSL
make -j"$(nproc)" USE_SSL=1
```

Sin SSL el build por defecto no necesita `libssl-dev` (los headers de OpenSSL
solo se incluyen cuando `WITH_SSL` está definido).

### 5.2 libcurl, libusb y PCSC

Se activan con flags de `make` (no con `config.sh`):

```bash
# necesita: libcurl4-openssl-dev, libusb-1.0-0-dev, libpcsclite-dev
make -j"$(nproc)" USE_LIBCURL=1 USE_LIBUSB=1 USE_PCSC=1
```

### 5.3 libdvbcsa (opcional, desde fuente)

No está en los repositorios oficiales. Para usarlo, compilar su versión
estática en la máquina offline (también se puede hacer en la máquina con
conexión y transportar la librería):

Requisitos extra: `autoconf`, `automake`, `libtool` (se pueden descargar
igualmente con `--download-only`).

```bash
# si se clona desde la máquina con conexión y se transporta el directorio:
cd libdvbcsa
./bootstrap && ./configure --disable-shared --enable-static --enable-avx2
make && sudo make install        # instalara /usr/local/lib/libdvbcsa.a

# compilar ncam usándolo
make -j"$(nproc)" USE_LIBDVBCSA=1
```

**No es necesario** para un build por defecto: sin `USE_LIBDVBCSA` el Makefile
compila sin ella.

---

## 6. Verificar el binario

```bash
BIN=$(ls -1t Distribution/ncam-Unofficial-*-x86_64-linux-gnu | grep -v '\.debug$' | head -n1)
"$BIN" -V          # muestra la versión y la revisión
readelf -d "$BIN" | grep NEEDED    # librerías dynamicas que necesita
ldd "$BIN"                         # comprobar que todo se resuelve
```

El binario sale en `Distribution/ncam-Unofficial-<versión>-<rev>-x86_64-linux-gnu`.

**Soporte multi-CAID:** está incluido por defecto (`MODULE_NEWCAMD=y` en
`config.h`). Con un puerto newcamd se pueden servir varios CAID a la vez, por
ejemplo:

```ini
[newcamd]
port = 12000@1802:000000,1861:000000,0B00:000000
```

(comas entre filtros del mismo puerto, hasta 16 CAID por puerto; cada filtro
lleva su `caid:provid` explícito. Documentación completa:
[`docs/configuracion-optima.md`](configuracion-optima.md)).

---

## 7. Notas importantes

- **glibc:** un binario compilado en una distro **más antigua** corre en
  distros más nuevas (Ubuntu 22.04 → 24.04/Debian 12+), pero al revés no.
  Si la máquina offline y la de preparación son la misma distro, no hay
  problema. Si se prepara en 24.04 para instalar en 22.04, el binario
  **no arrancaría**: en ese caso preparar los paquetes y la compilación en
  22.04 (o una base igual o más antigua).
- **`config.h` es un archivo del repositorio.** `config.sh` lo modifica con
  `sed`; no lo crea. Si aparece el error
  `globals.h: fatal error: config.h: No such file or directory`, el archivo
  se borró o no se descargó: restaurarlo del repositorio.
- **Sin red no hay `apt update`:** todos los `.deb` deben venir de la máquina
  de preparación; el paso [§3](#3-instalar-las-dependencias-en-la-máquina-offline)
  no necesita conexión.
- **Pruebas:** el repositorio incluye `devtools/test-newcamd-multicaid.sh`
  (E2E de 23 comprobaciones del soporte multi-CAID). Para ejecutarlo se
  necesita el binario ya compilado y `bash`/`sh`; no necesita red:
  `sh devtools/test-newcamd-multicaid.sh`.
