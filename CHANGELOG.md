# Changelog

## [2.6.0] - 2026-10-08 — un puerto newcamd sirve varios CAID

* **Nuevo: filtros multi-CAID por puerto newcamd.**
  `port = 12000@1802:000000,1861:000000,0B00:000000` sirve los tres CAID en
  un solo puerto (hasta 16 filtros por puerto; el exceso se ignora con un
  aviso en el log). Cada CAID necesita su `:provid` explícito; los clientes
  mgcamd piden cualquiera de los listados y los no listados se rechazan
  igual que antes. Se anuncia el primer CAID de la lista.
* **Nuevo: mapeo de clientes estilo oscam (CAID 0).** Si el ECM trae CAID 0,
  el daemon adivina el CAID por el patrón del ECM y lo mapea al CAID del
  puerto antes de extraer el provider; si el CAID adivinado no está en el
  puerto, el ECM se rechaza con `no card support`. Sin cambios en puertos
  de un solo CAID ni en puertos planos (verificado byte a byte).
* El WebIf muestra y guarda el puerto múltiple completo (antes perdía los
  CAID extra al guardar), y `caid =` en la cuenta anuncia solo el primer
  CAID permitido del puerto.
* Corregida la documentación: `examples/ncam.conf` y
  `docs/configuracion-optima.md` usaban `@1801,1861,0B00`, que NO son tres
  CAID (queda CAID 0 con tres provids); ahora muestran la sintaxis explícita
  `caid:provid`.
* Pruebas: nuevo `devtools/test-newcamd-multicaid.sh` (23 comprobaciones:
  multi-CAID, CAID 0, puerto único, cuenta limitada, WebIf y límite de 16)
  con cliente de pruebas `devtools/ncd_test_client.c`, enganchado al CI.
  (`config.sh` solo edita `config.h`, no lo crea: sigue versionado como
  plantilla por defecto, igual que en NCam original.)

## [2.5.0] - 2026-10-08 — el panel ya controla el daemon

* **Nuevo: aplicar líneas, peers y ajustes en caliente, sin reiniciar.**
  El super admin puede pulsar **Aplicar** en una línea (crea/actualiza la
  cuenta en el daemon y guarda `ncam.user`), en un peer (crea/actualiza el
  reader, lo reinicia y guarda `ncam.server`) o **Guardar y aplicar** en los
  ajustes `[cache]`; la nueva vista **Daemon NCam** muestra el estado y
  permite reiniciar el proceso. Todo queda en la auditoría y cada línea/peer
  recuerda su última aplicación (fecha y resultado).
* **Nuevo API** (control solo para super admin): `POST /lines/{id}/apply`,
  `POST /cache/servers/{id}/apply`, `POST /cache/settings/apply`,
  `GET /daemon/status`, `POST /daemon/restart`.
* **Arregladas las claves de configuración generadas**: los bloques `[reader]`
  emitían `cachex`/`cachex_mode`/`cachex_maxhop` y `priority`, que no existen
  en el daemon (se ignoraban en silencio); ahora emiten
  `cacheex = 3` / `cacheex_maxhop = 2`. Los bloques `[account]` ya no emiten
  `cacheex_disable`, que tampoco existe. `priority` sigue ordenando en el
  panel, pero solo ahí.
* Las acciones de control no dan 500: si el daemon no está accesible, las
  credenciales no coinciden (`httppwd`), está en `httpreadonly` o no puede
  escribir su configuración, devuelven `{ok: false, message}` con el motivo.
* El simulador del WebIf (`panel/tools/mock_ncam_webif.py`) ahora imita
  también el control (guardar usuarios/readers, ejecutar `[cache]`, reiniciar)
  con los marcadores del daemon real, y se puede levantar en proceso para las
  pruebas (`start_server`).
* Pruebas: 11 nuevas del panel (109 en total) contra el simulador y 4
  comprobaciones nuevas del frontend (botones Aplicar, vista del daemon,
  reinicio con confirmación).

## [2.4.9] - 2026-10-08 — desinstalador

* Nuevo `devtools/uninstall.sh`: detecta instalaciones por paquetes `.deb`
  (`ncam-ng`, `ncam-ng-panel`) y desde el código (`/usr/local/bin/ncam`,
  unidades de systemd manuales), detiene y deshabilita los servicios y quita
  los programas. Sin opciones **conserva** la configuración (`/etc/ncam`),
  los logs, la base de datos del panel y el `.env`, y lista lo que queda;
  `--purge` borra también todo eso y el usuario `ncam-panel`.
  Opciones `--daemon-only` / `--panel-only`, confirmación interactiva
  (`--yes` para scripts) y `--dry-run` para ver el plan sin tocar nada.
* Se publica como adjunto `uninstall.sh` en cada release y además viaja
  dentro del paquete del daemon como `ncam-ng-uninstall` (se re-ejecuta desde
  un temporal para poder borrar su propio paquete).
* Pruebas: 10 nuevas de los instaladores (77 en total), con una instalación
  simulada en raíz temporal (`NCAM_UNINSTALL_ROOT`) que comprueba el plan del
  `--dry-run` sin root y sin tocar el sistema.
* Documentado en [`INSTALL.md`](INSTALL.md) (§D2) y en el texto de la release.

## [2.4.8] - 2026-10-08 — los peers de caché ya no dan «Error 500»

* **Arreglado: un clic en «Probar» disparaba muchas peticiones a la vez.** La
  vista *Caché y peers* añadía un manejador de clics nuevo cada vez que se
  pintaba, sin quitar el anterior: tras visitar la vista varias veces, un solo
  clic en Probar/Config/Editar/Borrar lanzaba tantas peticiones como visitas,
  con su cascada de avisos. Ahora la vista instala un único manejador que se
  sustituye en cada pintado, y `renderView()` lo limpia al cambiar de vista.
* **Arreglado: `POST /cache/servers/{id}/test` devolvía 500 con peticiones
  simultáneas** (`sqlite3.OperationalError: database is locked`). La petición
  mantenía abierta la transacción SQLite durante el sondeo TCP (red, hasta
  3 s) y después intentaba escribir; dos sondeos solapados chocaban al
  confirmar. Ahora el sondeo corre fuera de la transacción (nuevo contexto
  `db.without_transaction`, con el sondeo y el guardado separados en
  `ncam.probe_tcp` + `ncam.record_cache_server_check`) y la escritura
  posterior es corta: 12 sondeos a la vez devuelven los 12 un `200` (antes, 11
  de 12 daban 500).
* Pruebas: 1 nueva del panel (98 en total) con 10 sondeos concurrentes y
  sondeo simulado lento, y 2 comprobaciones nuevas del frontend (un clic en
  «Probar» envía una sola petición aunque la vista se haya pintado dos veces).

## [2.4.7] - 2026-10-07 — «sin respuesta» con el motivo delante

* `ncam-ng-ctl panel port` imprime ahora, cuando el panel no responde, **por qué**:
  los últimos mensajes de `ncam-panel`, el estado del servicio, si se está
  reiniciando en bucle y **qué hay escuchando en los puertos vecinos** (8080, 8082,
  8090). Antes solo decía que no había respuesta y había que ir a mirar el registro
  uno mismo.
* `ncam-ng-ctl panel port NUEVO` deja la clave `NCAM_PANEL_PORT` **una sola vez** en
  el `.env`: si estaba repetida, la primera aparición se sustituye y las demás se
  eliminan, avisando de cuántas había («la clave estaba 3 veces; ahora queda
  una»). Antes podía quedar la clave duplicada y, como el panel usa la primera, el
  cambio parecía no aplicarse.
* Pruebas: 2 nuevas del instalador (73 en total).

## [2.4.6] - 2026-10-07 — «activo pero sin respuesta»: el diagnóstico que faltaba

* **Arreglado un fallo sutil que desincronizaba la herramienta y el panel.** Si el
  `.env` define `NCAM_PANEL_PORT` dos veces (típico al añadir una línea con `nano`
  sin borrar la anterior), el panel arranca con la **primera** —así lo leen
  `run.sh` y `config.py`— mientras `ncam-ng-ctl panel port` usaba la última: la
  herramienta hablaba del puerto 8090, el panel escuchaba en 8080 y el reinicio
  terminaba en «panel: sin respuesta en /api/v1/health (HTTP 000)». Ahora lee la
  misma que el panel y, si la clave está repetida, lo avisa.
* `ncam-ng-ctl panel port` además avisa si la línea lleva un **comentario detrás**
  (se toma como parte del valor y el servicio no arranca), si el valor no es un
  puerto válido, y muestra **dónde escucha de verdad** (`127.0.0.1:8090
  [python, pid N]`), no solo lo que dice el `.env`.
* **`restart-ncam-panel` ya no se queda en «sin respuesta».** Cuando el panel está
  activo pero no contesta, imprime los últimos mensajes del servicio y qué hay
  escuchando en el puerto del `.env` (y en 8080), que es lo que permite ver si el
  panel está en otro puerto o si el puerto lo ocupa otra cosa.
* Aviso cuando la unidad está `disabled`/`masked`: «arranca ahora, pero NO lo hará
  solo al reiniciar el servidor», con el `sudo systemctl enable` para arreglarlo.
* Pruebas: 3 nuevas del instalador (71 en total).

## [2.4.5] - 2026-10-07 — cambiar el puerto del panel de verdad

* **Arreglado: `NCAM_PANEL_PORT` del `.env` no cambiaba nada.** La unidad systemd
  traía el puerto fijado (`ExecStart=… --port 8080`), así que editar el `.env` y
  reiniciar dejaba el panel en 8080: parecía que el cambio se ignoraba. Ahora el
  servicio arranca con `run.sh` —el mismo que se usa a mano— y el `.env` es la
  única fuente de verdad para la dirección y el puerto.
* **Nuevo `ncam-ng-ctl panel port`**: muestra el puerto actual, si el panel
  responde y a qué puerto apunta el túnel de Cloudflare; y
  `sudo ncam-ng-ctl panel port NUEVO` cambia el puerto (valida el número, avisa si
  está ocupado, edita el `.env` con copia de seguridad, reinicia, comprueba la
  salud del panel y recuerda actualizar `cloudflared` y `ufw`).
* **`run.sh` valida el puerto** antes de arrancar: si el `.env` tiene algo que no
  es un número entre 1 y 65535, avisa y no arranca (antes uvicorn fallaba con un
  error críptico). Además deja en el registro la dirección con la que arranca.
* `devtools/install-systemd.sh` genera la unidad del panel de la misma forma
  (arranque por `run.sh`), y avisa de que `PANEL_HOST`/`PANEL_PORT` se ponen ahora
  en el `.env`.
* Documentación: [`docs/ajustes.md`](docs/ajustes.md) (§8, receta nueva y
  problemas frecuentes), [`INSTALL.md`](INSTALL.md) (unidad de ejemplo, tabla de
  comandos y dos filas nuevas), [`panel/README.md`](panel/README.md),
  [`README.md`](README.md) y la guía del túnel (si cambias el puerto, el túnel
  tiene que apuntar al nuevo).
* Pruebas: 12 nuevas del instalador (68 en total) que arrancan `run.sh` con un
  Python de mentira para comprobar que el puerto sale del `.env`, que la unidad
  systemd ya no lo fija y que `panel port` edita, avisa y verifica.

## [2.4.4] - 2026-10-06 — el panel ya no se queda «sin conexión» sin decir por qué

* **Diagnóstico claro del `HTTP 403` del WebIf.** Cuando el daemon rechaza al panel
  (la dirección desde la que se conecta no está en `httpallowed`), el panel ya no
  dice «sin conexión» a secas: indica qué dirección hay que permitir y la orden
  exacta para hacerlo. El caso más habitual es tener el panel y el daemon en la
  misma máquina: NCPanel consulta el WebIf desde `127.0.0.1`, y esa IP tiene que
  estar en `httpallowed` (el daemon solo mira la IP de **quien se conecta**, no la
  del servidor).
* **`ncam-ng-ctl webif check`**: comprobación corta (pensada para scripts) de si el
  panel puede consultar el WebIf; devuelve `1` y explica el arreglo cuando falta
  `127.0.0.1`. Además, `ncam-ng-ctl status` muestra el `403` con su causa, y
  `ncam-ng-ctl webif` avisa cuando el panel está instalado y la lista no incluye
  `127.0.0.1`.
* **El paquete del panel avisa al instalarse o actualizarse**: si `/etc/ncam/ncam.conf`
  existe y `httpallowed` no permite `127.0.0.1`, el instalador termina con un aviso
  y la orden para arreglarlo (no modifica el fichero del daemon por su cuenta).
* `ncam-ng-ctl` acepta `NCAM_CONF` en el entorno, para poder comprobar otro fichero
  de configuración sin tocar el del sistema.
* Documentación: nota en §12 de [`docs/configuracion-optima.md`](docs/configuracion-optima.md),
  aviso en [`docs/panel-sin-exponer-ip.md`](docs/panel-sin-exponer-ip.md) y en
  [`panel/README.md`](panel/README.md), y fila nueva en *Problemas frecuentes* de
  [`INSTALL.md`](INSTALL.md).
* Pruebas: 2 nuevas del panel (97 en total) y 7 nuevas del instalador (55 en total).

## [2.4.3] - 2026-10-06 — publicar el panel sin exponer tu IP (Cloudflare Tunnel)

* **Guía nueva** [`docs/panel-sin-exponer-ip.md`](docs/panel-sin-exponer-ip.md):
  cómo publicar NCPanel por un dominio con HTTPS **sin abrir puertos** y sin que la
  IP del servidor aparezca en el DNS ni en un escaneo, usando Cloudflare Tunnel
  (gratis), con los dos caminos (túnel con token desde la web y `config.yml`),
  Cloudflare Access (login extra con MFA, gratis hasta 50 usuarios), cierre de
  puertos en `ufw`, y comprobaciones (`dig`, `nc`, `ss`) para verificar que la IP
  está oculta.
* **Lo que no se puede ocultar, explicado claro:** las líneas de CCcam/Newcamd
  (puertos 12000/50000) son TCP propio de CAM, y el proxy de Cloudflare solo cubre
  HTTP/HTTPS (80, 443, 8080, 8443, 2052/2053, 2082/2083, 2086/2087, 2095/2096,
  8880). El plan gratis no las puede proteger: o relé TCP en otro VPS, o VPN
  (Tailscale/WireGuard), o Spectrum (Enterprise). También se avisa de que el WebIf
  del daemon filtra por la IP del socket y no lee `CF-Connecting-IP`, así que
  detrás de un túnel `httpallowed` deja de distinguir clientes: lo mejor es no
  publicarlo (SSH) o ponerle Access delante.
* **Panel: IP real del cliente detrás de un proxy de confianza.** Nueva variable
  `NCAM_PANEL_TRUSTED_PROXIES` (por defecto `127.0.0.1,::1`, admite rangos CIDR).
  Solo si la conexión llega desde un proxy de confianza se usan `CF-Connecting-IP`
  / `X-Forwarded-For` (última entrada) / `X-Real-IP`; así la **auditoría** y el
  **bloqueo por intentos fallidos** funcionan con la IP real detrás de
  cloudflared, nginx o Caddy.
* **Arreglo de seguridad:** `client_ip()` se fiaba de `X-Forwarded-For` viniera de
  donde viniera, de modo que cualquiera podía falsear su IP en la auditoría y, peor,
  esquivar el bloqueo por intentos fallidos rotando esa cabecera. Ahora, en
  conexiones directas, esas cabeceras **se ignoran** y se usa la IP del socket.
* Pruebas: 22 nuevas del panel (95 en total) que cubren la normalización de IPs, el
  proxy de confianza (Cloudflare, nginx, rangos CIDR), el rechazo de cabeceras
  falseadas y que rotar `X-Forwarded-For` no evita el bloqueo por intentos fallidos.

## [2.4.2] - 2026-10-06 — guía de administradores

* Nueva guía [`docs/administradores.md`](docs/administradores.md): los tres roles
  y sus límites, crear administradores desde la web y desde la consola
  (`ncam-ng-ctl admin add|role|del|passwd` y `app.seed --create/--list/--set-role/--delete`),
  las reglas que protegen al panel (nunca sin administrador activo, sin
  auto-cambio de rol, auditoría) y preguntas frecuentes (suspender, recuperar
  contraseña, revendedor degradado). Se publica también como archivo adjunto en la
  release.

## [2.4.1] - 2026-10-06 — varios administradores en NCPanel

* **Más de un super administrador.** Todos tienen el mismo control total y se
  pueden crear desde la web (**Revendedores y usuarios** → *Nueva cuenta* → rol
  *Administrador*) o desde la consola:

  ```bash
  sudo ncam-ng-ctl admin add maria              # administrador (clave aleatoria, una vez)
  sudo ncam-ng-ctl admin add luis reseller      # revendedor
  sudo ncam-ng-ctl admin add pepe user Clave.Pepe1
  sudo ncam-ng-ctl admin role luis reseller     # cambia el rol de una cuenta
  sudo ncam-ng-ctl admin del viejo              # elimina una cuenta
  sudo ncam-ng-ctl admin passwd maria           # nueva contraseña para esa cuenta
  sudo ncam-ng-ctl admin                        # lista las cuentas y sus roles
  ```

* **El panel nunca se queda sin administrador activo**: no se puede degradar,
  suspender ni eliminar al último super admin (ni desde la API, ni desde la web,
  ni desde la consola). Cuentan solo los **activos**, porque una cuenta suspendida
  no puede iniciar sesión. Nadie puede cambiarse el rol a sí mismo y un revendedor
  no puede ascender a nadie (`403`).
* Cada cambio de rol queda en la **auditoría** (`role: reseller -> super_admin`).
* Pruebas: 7 nuevas del panel (73 en total) y 10 nuevas de los instaladores
  (48 en total), más 5 del frontend que comprueban el alta de administradores.

## [2.4.0] - 2026-10-06 — acceso al WebIf desde tu IP pública o VPN

* Nuevo comando para no editar `ncam.conf` a mano:

  ```bash
  ncam-ng-ctl webif                              # quién puede entrar y su tipo
  ncam-ng-ctl webif add 191.103.121.243          # permite esa IP (y reinicia)
  ncam-ng-ctl webif add 10.0.0.0-10.0.0.255      # permite un rango
  ncam-ng-ctl webif add micasa.dyndns.org        # dominio (httpdyndns, se resuelve solo)
  ncam-ng-ctl webif del 192.6.154.19             # quita el acceso
  ```

  Escribe la lista en `httpallowed` (y los dominios en `httpdyndns`, máximo 3),
  deja una **copia de seguridad** del fichero (`ncam.conf.bak-*`), comprueba los
  datos (una IP mal escrita se rechaza antes de tocar nada), reinicia el daemon y
  enseña las URL para probar. Con `--dry-run` no toca nada y con `--no-restart`
  solo edita la configuración.
* `ncam-ng-ctl status` muestra ahora la lista de acceso del WebIf.
* Documentado en detalle (con el aviso de que la IP permitida es la de **quien se
  conecta**, no la del servidor, más el cortafuegos y `httpdyndns` para IPs
  cambiantes) en [docs/configuracion-optima.md](docs/configuracion-optima.md).
* Recordatorio útil: el WebIf usa autenticación **Digest**, así que para
  comprobarlo desde la consola hay que usar `curl --digest -u usuario:clave`.
  Si la IP no está permitida, el WebIf responde `403 Access denied` y el registro
  del daemon anota `unauthorized access from <ip> - invalid ip or dyndns`.
* Documentación revisada para que se pueda **copiar y pegar sin sorpresas**:
  * NCam solo ignora las líneas que **empiezan** por `#` (así lo hace
    `ncam-config-global.c`): un `#` o `;` detrás de un valor se toma como parte
    del valor. Todos los ejemplos de las guías llevan ya los comentarios en su
    propia línea, y se explica por qué (con la prueba de `logfile = /tmp/x.log # hola`).
  * `panel/README.md` usaba `http_port` (no existe: la clave es `httpport`) y un
    `httplocale = 1` que no es un idioma válido. Corregido, con `httpallowed`
    explicado y el atajo `ncam-ng-ctl webif add`.
  * Los ejemplos de `[cache]` de `README.md` e `INSTALL.md` recomendaban
    `delay = 120` (120 ms añadidos a cada respuesta de caché); ahora usan
    `delay = 0`, que es el valor por defecto del daemon y el más rápido.
  * `examples/ncam.conf` explica en `[webif]` que `httpallowed` son las IPs de
    quien se conecta y añade el ejemplo comentado de `httpdyndns`.

## [2.3.0] - 2026-10-06 — configuración óptima y permisos por CAID

### Configuración óptima para 3 CAID (1801, 1861, 0B00)

* Nueva guía **[docs/configuracion-optima.md](docs/configuracion-optima.md)**: cómo
  dejar NCam lo más rápido posible guardando **todas** las respuestas de los
  lectores en el motor de caché, con explicación de cada ajuste de `[global]`,
  `[cache]`, `[cccam]` y `[newcamd]`, la puesta en marcha en 5 minutos, la
  verificación del ratio de aciertos y una tabla de problemas frecuentes.
* Nuevos ficheros de ejemplo listos para copiar:
  [`examples/ncam.conf`](examples/ncam.conf),
  [`examples/ncam.server`](examples/ncam.server) (lector CCcam y lector Newcamd,
  tarjeta local y peer de cachex) y [`examples/ncam.user`](examples/ncam.user).
  Se instalan en `/usr/share/doc/ncam-ng/examples/optimo/` y se adjuntan a la
  release.
* Valores clave recomendados: `preferlocalcards = 2`, `fallbacktimeout = 2000`,
  `dropdups = 1`, `nice = -10`, `disablecrccws = 1`; y en `[cache]`:
  `max_time = 15`, `max_entries = 0` (sin límite, expira por tiempo),
  `max_hit_time = 15`, `cacheexenablestats = 1`. El `ncam.conf` que instala el
  paquete también estrena la caché sin límite y las estadísticas activadas.

### Permisos por CAID de los usuarios (NCPanel)

* El campo **CAIDs permitidos** de cada línea ya se aplica: se escribe como
  `caid = …` en el bloque `[account]` que el panel genera para `ncam.user`
  (`1801` = solo ese CAID; `1801,1861,0B00` = los tres; vacío = sin restricción).
  Antes el panel guardaba ese dato pero no lo exportaba, así que todos los
  clientes veían todos los CAID.
* El formulario de línea incorpora el campo (con botones rápidos 1801 / 1861 /
  0B00 / Todos) y la tabla muestra los CAID de cada línea; los valores se
  normalizan (mayúsculas, sin espacios) y se validan: un CAID mal escrito se
  rechaza con un mensaje claro en vez de llegar así al daemon.
* Con `caid` restringido, el daemon rechaza el ECM de otro CAID en el acto
  (`invalid caid 0x…`) sin molestar al proveedor.
* El campo **Conexiones máximas** ahora se exporta como `max_connections` del
  `[account]` (el ajuste real de NCam para conexiones simultáneas), que antes no
  se escribía nunca.
* Nuevo campo **Saltos CCcam** (`cccmaxhops`) por línea, con `1` por defecto:
  antes ese valor se deducía del campo "conexiones máximas" (que no tiene nada
  que ver), así que ahora se controla a propósito cuántos saltos ve cada cliente
  (`-1` = ninguna tarjeta, `1` = solo las directas, más para revendedores).

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
