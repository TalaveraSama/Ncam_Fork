# Changelog

## [2.2.1] - 2026-10-06 — guía de la pantalla Ajustes

* Nuevo documento **[docs/ajustes.md](docs/ajustes.md)**: explica *campo por campo*
  la pantalla **Ajustes → Configuración global y mantenimiento** (panel, WebIf del
  daemon, motor de caché, créditos y facturación de ECM, avisos de caducidad y
  mantenimiento), con qué hace cada valor, valores admitidos, qué se aplica al
  guardar, cuándo hay que reiniciar, recetas paso a paso, problemas frecuentes y
  la referencia completa. Se incluye en el paquete del panel
  (`/opt/ncam-ng-panel/docs/ajustes.md`) y se abre desde el botón *Guía de
  configuración* de la propia pantalla.
* La pantalla **Ajustes** ahora agrupa los campos por secciones (Panel, Daemon
  NCam, Motor de caché, Créditos y facturación, Avisos de caducidad) y cada campo
  lleva su etiqueta legible y una ayuda con la clave interna. Antes, la mitad de
  los campos se mostraban con la clave técnica (`panel.port.cccam`, …).
* El **muestreo automático** (`ncam.cache.panel_poll`) ya se aplica de verdad: a 0
  el panel deja de guardar muestras del histórico sin reiniciar el servicio (antes
  el ajuste se guardaba pero no hacía nada).
* Vaciar un campo ya se guarda como vacío (antes se ignoraba en silencio): sirve
  para quitar, por ejemplo, un servidor SMTP. Los campos de contraseña siguen
  mostrándose como `***` y solo cambian si escribes otro valor.

## [2.2.0] - 2026-10-06 — el panel pasa a llamarse NCPanel

* El panel de gestión se llama ahora **NCPanel**: así aparece en la interfaz
  (título, pantalla de acceso y barra lateral), en la documentación, en la
  descripción del paquete y del servicio `ncam-panel`, y en los avisos de
  caducidad (asunto `[NCPanel] …`).
* El rename se aplica solo a los nombres visibles: **no cambian** el paquete
  `ncam-ng-panel`, el servicio `ncam-panel`, las rutas (`/opt/ncam-ng-panel`,
  `/var/lib/ncam-ng-panel`) ni las variables `NCAM_PANEL_*`, para que las
  actualizaciones sigan funcionando sin tocar nada.
* Las instalaciones existentes se actualizan solas: al arrancar, la base de datos
  cambia el ajuste `panel.name` si aún tiene el valor por defecto antiguo (si lo
  personalizaste, se respeta), y el `postinst` hace lo mismo con
  `NCAM_PANEL_NAME` en `/opt/ncam-ng-panel/.env`.

## [2.1.0] - 2026-10-06 — comandos de consola

### Gestor de servicios `ncam-ng-ctl`

El paquete del daemon instala ahora `ncam-ng-ctl` y tres atajos (enlaces al mismo
script), para no tener que recordar `systemctl`:

```bash
restart-ncam                     # reinicia el daemon
restart-ncam-panel               # reinicia el panel
ncam-ng-status                    # estado, puertos y comprobación HTTP
```

Y el gestor completo:

| Comando | Para qué |
| --- | --- |
| `ncam-ng-ctl status` | estado de los dos servicios, puertos (los lee de la configuración real) y comprobación HTTP |
| `ncam-ng-ctl restart [ncam\|panel]` | reinicia uno o los dos y comprueba que levantan (con reintentos, `health ok`) |
| `ncam-ng-ctl start` / `stop [ncam\|panel]` | arranca o detiene |
| `ncam-ng-ctl logs [ncam\|panel] [-f] [-n N]` | registro con journald, en vivo con `-f` |
| `ncam-ng-ctl config ncam\|panel` | abre la configuración con `$EDITOR` (o nano/vi) y recuerda el reinicio |
| `ncam-ng-ctl passwd [usuario]` | genera una contraseña nueva del panel (la ejecuta como el usuario del servicio y se muestra una vez) |
| `ncam-ng-ctl version` | versiones de los paquetes, del panel y del binario |

Detalles: se re-ejecuta solo con `sudo` cuando hace falta (status no), `--dry-run`
muestra lo que haría, valida las opciones antes de pedir permisos y, si un
servicio no arranca, enseña las últimas líneas del registro con el motivo.

## [2.0.2] - 2026-10-06 — paquetes .deb

* El instalador crea su carpeta temporal con permisos de lectura para el usuario
  de apt (`_apt`); antes apt avisaba de que la descarga se hacía sin sandbox
  («N: Download is performed unsandboxed as root…»).
* El `postinst` del panel avisa de que `panel.db` es una base de datos SQLite y
  **no se debe abrir con un editor de textos** (nano, vi…), e indica cómo
  consultarla con `sqlite3`; mismo consejo añadido a los problemas frecuentes de
  [INSTALL.md](INSTALL.md).
* `devtools/build-deb.sh` usa 2.0.2 como versión por defecto.

## [2.0.1] - 2026-10-06 — paquetes .deb

### Instalación más ligera

* El paquete `ncam-ng-panel` ya no recomienda `python3-pip`. Ese paquete
  recomienda a su vez `build-essential` y `python3-dev`, así que `apt` instalaba
  ~280 MB de compiladores y cabeceras que el panel no necesita (el `pip` del
  entorno virtual lo aporta `python3-venv`, que sí es dependencia). En una
  instalación limpia el panel añade ahora 0 MB de dependencias extra.

### Dependencias de Python sin conexión, para todas las versiones soportadas

* El paquete incluye las dependencias en ruedas (`--with-wheels`) para **Python
  3.10, 3.11 y 3.12**, que son las de Ubuntu 22.04, Debian 12 y Ubuntu 24.04.
  Antes solo se incluían las de la versión con la que se construía el paquete
  (3.10 en el CI), así que en Ubuntu 24.04 (3.12) la instalación sin conexión
  fallaba con `Could not find a version that satisfies the requirement
  httptools>=0.8.0` y tenía que recurrir a PyPI. Ahora `ncam-ng-panel-setup`
  instala desde el propio paquete y, si la versión de Python no está cubierta,
  lo dice claramente antes de usar PyPI.
* `devtools/build-deb.sh --wheels-python "3.10 3.12"` permite elegir qué
  versiones se empaquetan para instalar sin conexión.

### Coherencia de versiones

* El panel informa la versión del paquete instalado: `ncam-ng-panel` deja un
  fichero `VERSION` y `GET /api/v1/health` (y `GET /api/v1/admin/meta`) lo
  devuelven, en lugar de la versión fija del código.
* El `postinst` pasa la ruta de las ruedas al instalador del entorno, de forma
  que las pruebas con `PKGROOT` ejercitan la misma ruta que una instalación real.

## [2.0.0] - 2026-10-05 — NCam-NG

### Motor de caché v2 (`ncam-cache.c`, `ncam-cache.h`)

* **Estadísticas internas** (`struct s_cache_stats`): consultas, aciertos, fallos,
  control words nuevas/actualizadas, rechazos por ciclo CW, expulsiones por TTL y
  por capacidad y estimación de memoria. Nuevas funciones públicas
  `cache_get_stats()`, `cache_reset_stats()` y `cache_get_top_entries()`.
* **Límite de capacidad con expulsión LRU**: nueva opción `[cache] max_entries`
  (0 = ilimitado, comportamiento anterior). La selección de víctimas se hace en
  una sola pasada sobre la lista de contenedores, en lotes de `max_entries/32`
  acotados a `[8, 64]` para no alargar el bloqueo de escritura.
* **Refactor**: `cache_free_ecmhash()` comparte la liberación de contenedores
  entre la limpieza periódica y la expulsión LRU; `cleanup_cache()` usa una sola
  marca de tiempo por barrido y contabiliza las expulsiones.
* **Instrumentación** de los caminos de lectura/escritura sin locks adicionales
  (un único punto de salida en `check_cache()`).

### WebIf / API

* Nuevo endpoint `GET /ncamapi.json?part=cachestats` con todo el estado del motor
  (límites, contadores, hit ratio, caché de CW, entradas más servidas) y
  `&action=reset` para reiniciar los contadores.
* Plantillas `webif/api.json/cachestats.json` y `cachestats_hotbit.json`.
* **Página del WebIf clásico** `cacheengine.html`: contadores, hit ratio, límites,
  memoria estimada, CW más servidas, caché de CW de cacheex y peers online/total.
  Acciones `?action=reset`, `?action=snapshot`; el histórico en memoria se
  auto-alimenta (`cache_history_sample_if_due(30)`) y `cache_human_size()`
  formatea los tamaños.
* Nuevo ítem de menú `CACHE ENGINE` (`MNU_CACHEENGINE`); `setActiveMenu()` añade
  `CACHEENGINEMENUITEM`/`CACHEEXMENUITEM`, con lo que el menú funciona también
  en compilaciones sin cacheex.
* Opción `max_entries` añadida al ejemplo de configuración
  (`Distribution/doc/example/ncam.conf`).

### Compatibilidad

* El panel ahora negocia **autenticación Digest MD5** (la que usa el WebIf de NCam
  cuando se define `httpuser`/`httppwd`): antes solo enviaba Basic y, con el WebIf
  protegido, no podía leer el motor de caché. Incluye mensajes de error claros para
  credenciales rechazadas y `GET /api/v1/health` informa la URL del WebIf realmente
  en uso (la de los ajustes, no solo la del entorno).
* Nueva guía [`INSTALL.md`](INSTALL.md) con la instalación completa (compilación,
  configuración, systemd, actualizaciones y problemas frecuentes).
* Nuevo `devtools/install-systemd.sh`: instala `/etc/systemd/system/ncam.service` y
  `ncam-panel.service` con las rutas detectadas, los habilita y arranca, de modo
  que daemon y panel sobreviven al cierre de la terminal. Detecta si el binario
  necesita `-f` (los builds con STAPI demonizan por defecto; los estándar ya
  arrancan en primer plano), avisa si el puerto está ocupado por un proceso manual
  y guarda copia de las unidades previas.
* Nuevo `devtools/install-panel.sh`: prepara el panel desde la raíz del repositorio
  (entorno virtual en `panel/.venv`, dependencias, `.env` con secreto generado y
  super administrador) de forma idempotente.
* `panel/run.sh` usa el entorno virtual si existe (sin tener que activarlo), carga
  `panel/.env` con un analizador tolerante (comentarios y valores con espacios) y
  respeta las variables del entorno por encima del `.env`.
* Nuevo `devtools/install-daemon.sh`: instala el binario final (excluye siempre el
  `.debug`), prefiere el del commit actual, avisa si el binario está desfasado y
  copia los ejemplos de configuración sin sobrescribir los existentes.

### Paquetes .deb y releases (primera release pública)

* `devtools/build-deb.sh` construye los paquetes **`ncam-ng`** (binario en
  `/usr/bin/ncam`, configuración en `/etc/ncam/ncam.conf`, ejemplos y unidad
  systemd `ncam`) y **`ncam-ng-panel`** (panel en `/opt/ncam-ng-panel`, unidad
  `ncam-panel`, usuario de sistema `ncam-panel`, datos en
  `/var/lib/ncam-ng-panel`). Admite `--version`, `--arch`, `--no-build` y
  `--with-wheels` (incluye las dependencias de Python para instalar sin conexión).
* `devtools/install-deb.sh`: instalador de releases. Descarga los `.deb` de la
  última release (o de una concreta con `--release`), **verifica el SHA-256**,
  los instala con `apt` (`--force-confold`, así no pisa la configuración del
  usuario) y admite `--local`, `--daemon-only`, `--panel-only`, `--download-only`
  y `--keep`. El paquete del daemon lo instala como `ncam-ng-install-deb`.
* Scripts de mantenimiento de los paquetes (`packaging/`): `postinst`, `prerm` y
  `postrm` de ambos paquetes (usuario de sistema, directorios de datos, `.env`
  con secreto aleatorio, semilla del super administrador y arranque del servicio;
  `purge` borra los datos del panel).
* `ncam-ng-panel-setup` (dentro del paquete): crea o repara el entorno virtual y
  las dependencias del panel, sin conexión si hay ruedas y con PyPI si no.
* Instalación verificada de punta a punta en un sistema con systemd: los dos
  servicios quedan activos y habilitados al arranque, el panel responde y lee el
  motor de caché del daemon, y el ciclo de purga/reinstalación deja los datos
  intactos. Fruto de esas pruebas se corrigieron los permisos del entorno virtual
  (el usuario `ncam-panel` no podía ejecutarlo y el servicio no arrancaba), el
  propietario de la base de datos, el re-lanzamiento con `sudo` del instalador
  (perdía las opciones) y la reinstalación de la misma versión.
* La dependencia `libc6` se calcula del propio binario (`objdump`) en lugar de
  fijarla a mano, y la release se compila en Ubuntu 22.04 con la configuración
  por defecto de `config.sh` (SoftCam.Key integrado incluido), de modo que los
  `.deb` funcionan en Ubuntu 22.04/24.04 y Debian 12/13.
* Nuevo workflow [`.github/workflows/release.yml`](.github/workflows/release.yml):
  al empujar una etiqueta `v*` compila el daemon en un runner de GitHub, ejecuta
  las pruebas del motor de caché y del panel, construye ambos `.deb`, genera
  `SHA256SUMS` y publica la release en este repositorio con los paquetes y el
  instalador adjuntos.
* Corregido un fallo del instalador que impedía usarlo en un sistema limpio
  («Maximum function recursion depth reached» y después «la release no trae el
  paquete ncam-ng»): al analizar los adjuntos de la release, la función de la
  tabla se llamaba a sí misma. Además, `--release <etiqueta>` consultaba un
  endpoint equivocado de la API (`/releases/<etiqueta>` en vez de
  `/releases/tags/<etiqueta>`) y los patrones de búsqueda generaban avisos de
  `awk`. Nueva prueba `devtools/run-install-tests.sh` (18 comprobaciones, en el
  CI) que detecta funciones recursivas, valida la sintaxis y comprueba que el
  instalador localiza los paquetes de una release real; nueva opción
  `--list-assets` para diagnosticar.
* `app.seed --reset-password`: genera una contraseña nueva para un usuario
  existente (útil para recuperar el acceso al panel si se perdió la del super
  administrador impresa durante la instalación).

### Compilación

* `Makefile`: al compilar con SoftCam.Key (configuración por defecto) el enlace
  podía fallar con «undefined reference to `_binary_SoftCam_Key_start`». Eran dos
  causas: el método de incrustación (`-Wl,--format=binary -Wl,SoftCam.Key`)
  depende de la versión de binutils, y el bloque se saltaba por completo si el
  entorno definía `ANDROID_NDK` —cosa que hacen los runners de GitHub aunque se
  compile para escritorio—. Ahora se embebe con `ld -r -b binary` + `objcopy` en
  todas las plataformas y la condición mira el compilador de destino, no las
  variables de entorno. El emulador sigue leyendo además `/etc/ncam/SoftCam.Key`
  en tiempo de ejecución.

### Pruebas

* `devtools/cache-engine-test.c` + `devtools/run-cache-test.sh`: compilan el motor
  de caché real con stubs y verifican 37 comportamientos (inserciones, aciertos,
  contabilidad, entradas calientes, capacidad con LRU, histórico de muestras,
  formateo de tamaños y expiración). No requiere cross-compilar el daemon.
* Panel: `cd panel/backend && python3 -m pytest` -> 64 pruebas (auth, RBAC,
  líneas, créditos, caché, avisos, facturación por ECM, Digest y API keys).

### Panel de gestión (`panel/`)

* Nuevo panel web (FastAPI + SQLite + SPA en JavaScript puro) con roles
  **super administrador**, **reseller** y **usuario final**.
* Jerarquía de cuentas, límites de líneas, API keys por cuenta.
* Créditos: emisión (super admin), transferencias reseller → usuario, libro mayor
  con saldo resultante y bloqueo por saldo insuficiente.
* Gestión de líneas (alta con coste en créditos, renovación, reset de contraseña,
  suspensión) y exportación en formatos `ncam`, `cccam`, `newcamd`, `camd35`, `json`.
* Peers de caché con prueba de conectividad TCP real y generación de bloques
  `[reader]` para `ncam.server`.
* Visualización del motor de caché: hit ratio en vivo, entradas, memoria,
  expulsiones, entradas calientes e histórico de muestras.
* Generación de configuración (`ncam.conf`, `ncam.user`, `ncam.server`) desde los
  datos del panel.
* Auditoría de todas las acciones sensibles, ajustes con lista blanca y
  mantenimiento del histórico.
* **Avisos de caducidad** de líneas por email (SMTP con STARTTLS opcional) y
  Telegram (Bot API), con antelación configurable por línea o global, destinos
  propios o heredados del propietario, planificador automático
  (`notify.interval_seconds`), simulación de envío, mensaje de prueba, histórico
  en `notification_log` y reglas anti-spam (mismo umbral / 20 h por línea y canal).
* **Facturación por consumo real de ECM**: el panel lee `part=userstats` del
  daemon, guarda el avance de cada línea (`ecm_usage`) y cobra al propietario los
  bloques completos servidos (`billing.ecm.block` / `billing.ecm.price`), con
  libro mayor, saldo pendiente si no alcanzan los créditos, detección de reinicio
  del daemon y suspensión opcional por deuda.
* El simulador `panel/tools/mock_ncam_webif.py` implementa también
  `part=userstats` con contadores crecientes, para probar la facturación sin daemon.
* 64 pruebas automatizadas (`pytest`) de roles, líneas, créditos, caché, auditoría,
  notificaciones, consumo y autenticación Digest del WebIf.
* `panel/tools/mock_ncam_webif.py`: simulador del WebIf para desarrollar sin daemon.
