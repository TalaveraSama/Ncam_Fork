# Instalación de NCam-NG desde GitHub

Guía probada paso a paso sobre un clon limpio de
`https://github.com/TalaveraSama/Ncam_Fork.git` (Ubuntu/Debian y similares).

Hay **dos partes independientes**:

| Parte | Qué es | Dónde se instala |
| --- | --- | --- |
| **A. Daemon NCam-NG** | El servidor de tarjetas/caché en C (motor de caché v2 y WebIf con la página del motor). | `/usr/local/bin` + `/usr/local/etc` |
| **B. Panel NCam-NG** | La web de gestión (FastAPI + SQLite) con super admin, reseller, avisos y facturación. | La carpeta `panel/` |

---

## 0. Qué rama usar

El código nuevo (motor de caché v2, página `cacheengine.html`, avisos de
caducidad y facturación por ECM) está en la rama
**`arena/01a10b7f-ncam-fork`**, publicada en el **PR #1**.

Dos formas de usarlo:

```bash
# Opción 1: trabajar directamente con la rama
git clone https://github.com/TalaveraSama/Ncam_Fork.git
cd Ncam_Fork
git checkout arena/01a10b7f-ncam-fork

# Opción 2: fusionar el PR en main y usar main (recomendado a la larga)
#   en GitHub: abrir el PR #1 -> "Merge pull request"
git clone https://github.com/TalaveraSama/Ncam_Fork.git
cd Ncam_Fork
```

---

## A. Daemon NCam-NG

### 1. Dependencias

```bash
sudo apt update
sudo apt install -y build-essential git cmake pkg-config

# Solo si vas a compilar con TODOS los extras (incluye SSL y libdvbcsa):
sudo apt install -y libssl-dev libdvbcsa-dev libusb-1.0-0-dev libpcsclite-dev
```

### 2. Clonar y compilar

```bash
git clone https://github.com/TalaveraSama/Ncam_Fork.git
cd Ncam_Fork

# Opción simple (usa la configuración que trae el repositorio, sin extras):
make -j"$(nproc)"
```

El binario queda en `Distribution/`:

```
Distribution/ncam-Unofficial-gitXXXXXXX-x86_64-linux-gnu
```

Si prefieres elegir opciones (lectores, protocolos, SSL, etc.):

```bash
./config.sh --enable all      # o ./config.sh  (menú interactivo, requiere consola)
make -j"$(nproc)"
```

> `--enable all` activa SSL (`libssl-dev`) y libdvbcsa (`libdvbcsa-dev`): sin esos
> paquetes la compilación falla con `openssl/aes.h: No such file or directory`.
> Si no los necesitas, compila sin `./config.sh` y listo.

### 3. Instalar el binario

La forma más simple (elige solo el binario final, nunca el `.debug`, y no
sobrescribe configuraciones existentes):

```bash
sudo devtools/install-daemon.sh --with-config
```

Equivale a copiar el binario a `/usr/local/bin/ncam` y los ejemplos
(`ncam.conf`, `ncam.server`, `ncam.user`, `ncam.services`) a `/usr/local/etc`.
Opciones: `--help`, y variables `PREFIX=` y `CONFDIR=` para otros destinos.

Instalación manual (ojo: **no** uses `Distribution/ncam-*`, el comodín también
captura el `.debug` y falla con *"is not a directory"*):

```bash
ls -1 Distribution/ncam-Unofficial-*-x86_64-linux-gnu | grep -v '\.debug$'
sudo install -m 0755 Distribution/ncam-Unofficial-gitXXXXXXX-x86_64-linux-gnu /usr/local/bin/ncam
sudo mkdir -p /usr/local/etc
sudo cp Distribution/doc/example/ncam.conf     /usr/local/etc/
sudo cp Distribution/doc/example/ncam.server   /usr/local/etc/   # readers (opcional)
sudo cp Distribution/doc/example/ncam.user     /usr/local/etc/   # cuentas  (opcional)
sudo cp Distribution/doc/example/ncam.services /usr/local/etc/   # opcional
```

### 4. Configurar el motor de caché y el WebIf

Edita `/usr/local/etc/ncam.conf`:

```ini
[webif]
httpport    = 8181                 # puerto del WebIf (JSON API + página del motor)
httpuser    = admin                # cámbialo siempre
httppwd     = TU_CLAVE_WEBIF       # obliga a autenticarse (Digest MD5)
httpallowed = 127.0.0.1,192.168.0.0-192.168.255.255

[cache]                            # motor de caché v2 (nuevo)
max_time        = 15               # segundos que vive un CW en caché
max_entries     = 1000             # límite de contenedores (0 = ilimitado) + expulsión LRU
max_hit_time    = 15
delay           = 120
```

### 5. Arrancar y comprobar

```bash
sudo ncam -b -B /var/run/ncam.pid          # segundo plano
sudo ncam -c /usr/local/etc                # o en primer plano para ver el log
```

Comprobaciones rápidas (el WebIf usa autenticación **Digest**, por eso `--digest`):

```bash
# página nueva del motor de caché en el WebIf clásico
curl --digest -u admin:TU_CLAVE_WEBIF http://127.0.0.1:8181/cacheengine.html | head

# API JSON del motor
curl --digest -u admin:TU_CLAVE_WEBIF "http://127.0.0.1:8181/ncamapi.json?part=cachestats"
```

> Si **no** define `httpuser`/`httppwd`, el WebIf queda abierto sin contraseña
> (útil solo para pruebas en local: entonces omita `--digest`).

### 6. Servicio systemd (muy recomendado)

Con esto el daemon y el panel **siguen funcionando al cerrar la terminal**, arrancan
solos con el servidor y se reinician si fallan:

```bash
sudo devtools/install-systemd.sh              # daemon + panel
sudo devtools/install-systemd.sh --panel-only # solo el panel
```

Crea `/etc/systemd/system/ncam.service` y `ncam-panel.service` con las rutas
detectadas, los habilita y los arranca. Avisa si el binario o el entorno virtual
faltan y guarda copia de las unidades anteriores (`.bak-fecha`).

> Antes de arrancar el servicio, **para el panel manual** (`Ctrl+C`) o el puerto
> 8080 estará ocupado. Igual con el daemon si lo lanzaste a mano.

Si prefieres hacerlo a mano, el contenido generado es este:

```ini
# /etc/systemd/system/ncam.service
[Unit]
Description=NCam-NG daemon (cardserver + motor de caché)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# los binarios estándar arrancan en primer plano; los compilados con STAPI
# demonizan y necesitan -f (el instalador lo añade solo)
ExecStart=/usr/local/bin/ncam -c /usr/local/etc
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ncam
sudo systemctl status ncam
```

---

## B. Panel NCam-NG

### 1. Dependencias

```bash
sudo apt install -y python3 python3-venv python3-pip
```

### 2. Instalar y configurar

Desde la **raíz** del repositorio (el `requirements.txt` está en `panel/`, no en
la raíz; si lo ejecutas desde el sitio equivocado verás
`Could not open requirements file`):

```bash
sudo apt install -y python3-venv python3-pip      # si falta
devtools/install-panel.sh                          # venv + dependencias + .env + super admin
devtools/install-panel.sh --demo                   # además, datos de demostración
```

El script crea `panel/.venv`, instala `fastapi`/`uvicorn`, copia
`.env.example` a `panel/.env`, **genera el `NCAM_PANEL_SECRET`** y crea el super
administrador (imprime la contraseña una sola vez). Es idempotente.

A mano (equivalente):

```bash
cd Ncam_Fork/panel
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Ajusta `.env` como mínimo:

```ini
NCAM_WEBIF_URL=http://127.0.0.1:8181      # WebIf del daemon (paso A)
NCAM_WEBIF_USER=admin                     # httpuser del daemon
NCAM_WEBIF_PASSWORD=TU_CLAVE_WEBIF        # httppwd del daemon (Digest MD5)
NCAM_PANEL_SECRET=...                     # python3 -c "import secrets;print(secrets.token_urlsafe(48))"
NCAM_PANEL_PORT=8080
```

> También puedes fijar la URL y las credenciales del WebIf desde la propia web
> del panel (vista **Ajustes**: `panel.ncam_webif_url`, `panel.ncam_webif_user`,
> `panel.ncam_webif_password`), sin tocar el `.env`. El panel negocia Digest MD5
> automáticamente, igual que el WebIf del daemon.

### 3. Crear el super administrador

```bash
PYTHONPATH=backend python3 -m app.seed --username admin
#   -> imprime la contraseña UNA sola vez: guárdala

# datos de demostración (reseller, cliente, líneas y un peer de caché)
PYTHONPATH=backend python3 -m app.seed --demo
```

### 4. Arrancar

```bash
cd Ncam_Fork/panel
./run.sh                 # http://TU_IP:8080
```

`run.sh` usa `panel/.venv` si existe (no hace falta activarlo), carga `panel/.env`
(dejando mandar a las variables que ya estén en el entorno) y arranca uvicorn.

Entra con el super admin y revisa:

* **Ajustes** → `panel.ncam_webif_url`, tarifas de créditos y del motor de caché.
* **Consumo ECM** → `billing.ecm.block` / `billing.ecm.price` (facturación apagada por defecto).
* **Avisos de caducidad** → SMTP/Telegram y días de antelación.
* **Caché y peers** → métricas en vivo del motor de caché v2.

### 5. Servicio systemd (muy recomendado)

El panel solo vive mientras la terminal esté abierta si lo lanzas a mano. Para que
quede como servicio (arranca solo, sobrevive al cierre de sesión y se reinicia):

```bash
sudo devtools/install-systemd.sh --panel-only
sudo systemctl status ncam-panel
```

El instalador escribe `/etc/systemd/system/ncam-panel.service` con la ruta real de
tu `panel/`, usando el entorno virtual y cargando `panel/.env` (lo lee la propia
aplicación). Si prefieres hacerlo a mano:

```ini
# /etc/systemd/system/ncam-panel.service
[Unit]
Description=NCam-NG Panel (API + web de gestión)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/ruta/a/Ncam_Fork/panel
Environment=PYTHONPATH=/ruta/a/Ncam_Fork/panel/backend
Environment=NCAM_PANEL_HOST=0.0.0.0
Environment=NCAM_PANEL_PORT=8080
ExecStart=/ruta/a/Ncam_Fork/panel/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ncam-panel
```

Comandos del día a día:

```bash
sudo systemctl status ncam ncam-panel
sudo journalctl -u ncam-panel -f          # log del panel en vivo
sudo systemctl restart ncam-panel         # tras cambiar panel/.env
```

> El panel guarda la base de datos en `panel/backend/data/panel.db` (configurable
> con `NCAM_PANEL_DB`). Haz copia de seguridad de ese fichero.

---

## C. Actualizar a una versión nueva

```bash
cd Ncam_Fork
git pull                                   # o git pull origin main tras fusionar el PR
make -j"$(nproc)"
sudo devtools/install-daemon.sh            # avisa si el binario no es del commit actual
sudo systemctl restart ncam

cd panel
. .venv/bin/activate
pip install -r requirements.txt
./run.sh                                   # o sudo systemctl restart ncam-panel
```

El panel **migra la base de datos solo** al arrancar (por ejemplo, al pasar al
esquema v4 añade las columnas de avisos y de consumo de ECM).

---

## D. Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| `install: target '/usr/local/bin/ncam' is not a directory` | El comodín coincidió con dos ficheros (el binario y el `.debug`). Usa el nombre exacto o `sudo devtools/install-daemon.sh`. |
| `openssl/aes.h: No such file or directory` | Compilaste con `--enable all` sin SSL: `sudo apt install libssl-dev libdvbcsa-dev` o compila sin `./config.sh`. |
| El panel dice *WebIf de NCam rechazó las credenciales* | Usuario/contraseña incorrectos: deben coincidir con `httpuser`/`httppwd` del daemon. |
| El panel dice *WebIf de NCam no disponible* | Revisa `NCAM_WEBIF_URL`/`panel.ncam_webif_url`, que el daemon esté escuchando (`ss -ltnp | grep 8181`) y que `httpallowed` incluya la IP del panel. |
| `database is locked` en el log del panel | Dos procesos usando la misma `panel.db`: detén el duplicado o usa otra ruta con `NCAM_PANEL_DB`. |
| El WebIf no responde en la red local | Ajusta `httpallowed` y `httpport` en `[webif]`, y abre el puerto en el cortafuegos. |
| Los avisos de caducidad no se envían | Activa `notify.enabled`, el canal (`notify.channel.email` / `notify.channel.telegram`) y rellena `notify.smtp.*` o el token del bot. |
| La facturación por ECM no cobra | Debe haber **bloques completos** servidos (`billing.ecm.block`), saldo del propietario y las líneas exportadas al daemon como cuentas. |
| Cierro la terminal y el panel deja de responder | está lanzado a mano: instálalo como servicio con `sudo devtools/install-systemd.sh`. |
| El servicio no arranca y el puerto está ocupado | tienes un proceso manual usando el mismo puerto: páralo (`Ctrl+C` o `sudo kill`) y `sudo systemctl restart ncam-panel`. |
| `Could not open requirements file: requirements.txt` | Estás en la raíz del repo: `pip install -r panel/requirements.txt`, o mejor `cd panel` (o usa `devtools/install-panel.sh`). |
| `.venv` creado en la raíz del repo por error | El entorno del panel va en `panel/.venv`: borra el de la raíz (`rm -rf .venv`) y ejecuta `devtools/install-panel.sh`. |
| `ModuleNotFoundError: No module named 'app'` | Ejecuta siempre desde `panel/` con `PYTHONPATH=backend` (o usa `./run.sh`). |

Para probar el panel **sin daemon**: `python3 panel/tools/mock_ncam_webif.py
--port 8181 --users demo_linea` y apunta `panel.ncam_webif_url` a ese puerto.

## E. Pruebas (opcional)

```bash
devtools/run-cache-test.sh                 # motor de caché en C: 37 comprobaciones
cd panel/backend && python3 -m pytest      # panel: 60 pruebas
```
