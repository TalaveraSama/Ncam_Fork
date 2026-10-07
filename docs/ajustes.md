# Ajustes de NCPanel — guía de configuración

Esta guía explica **campo por campo** la pantalla **Ajustes → Configuración global y
mantenimiento** de NCPanel: qué hace cada valor, qué se puede poner, qué pasa al
guardarlo y cuándo hay que reiniciar algo.

> Solo el **super administrador** ve el menú ⚙ **Ajustes**. Un reseller no puede
> abrirlo ni cambiar estos valores (la API le responde `403`).

---

## 1. Cómo funciona esta pantalla

* **Dónde se guarda:** en la tabla `settings` de la base de datos del panel
  (`/var/lib/ncam-ng-panel/panel.db`, SQLite). **No es un fichero de texto: no lo
  abras con `nano`.** Si necesitas consultarlo a mano:
  `sqlite3 /var/lib/ncam-ng-panel/panel.db 'select key, value from settings;'`
* **Cuándo se aplica:** al pulsar **Guardar ajustes**, al instante. El panel lee
  estos valores en cada operación, así que no hay que reiniciar el servicio para
  el panel. (Ojo: los ajustes de *estilo* `[cache]` son una **plantilla** para el
  daemon; ver [§4](#4-motor-de-caché).)
* **Secretos:** la contraseña del WebIf, la del SMTP y el token de Telegram se
  muestran como `***`. Si dejas el campo como está, no se toca; si escribes otro
  valor, se reemplaza; si lo **vacías**, se borra.
* **Campos vacíos en el resto:** se guardan vacíos (sirve para quitar, por
  ejemplo, un servidor SMTP que ya no uses).
* **Historial:** cada cambio queda en la auditoría (menú *Auditoría*, acción
  `settings.update`) con la lista de claves modificadas.

Los ajustes están agrupados por para qué sirven: **Panel**, **Daemon NCam
(WebIf)**, **Motor de caché**, **Créditos y facturación** y **Avisos de
caducidad**.

---

## 2. Panel (identidad y datos que se publican)

| Campo | Clave interna | Por defecto | Qué hace |
| --- | --- | --- | --- |
| Nombre del panel | `panel.name` | `NCPanel` | Es el nombre que acompaña a todo: el asunto de los avisos (`[NCPanel] La línea…`) y el encabezado de la interfaz. |
| Host público | `panel.public_host` | `TU_SERVIDOR` | La IP o el dominio que se escriben en **las líneas que exportas** para tus clientes. |
| Puerto CCcam | `panel.port.cccam` | `12000` | Puerto que aparece en las líneas exportadas en formato CCcam / NCam. |
| Puerto Newcamd | `panel.port.newcamd` | `50000` | Puerto para el formato Newcamd (`N:`). |
| Puerto Camd35 | `panel.port.camd35` | `33333` | Puerto para el formato Camd35. |
| Puerto Cacheex | `panel.port.cacheex` | `8181` | Puerto para líneas de intercambio de caché (cacheex). |

Qué conviene saber:

* **`panel.public_host` es el error más típico**: si lo dejas en `TU_SERVIDOR`,
  tus clientes recibirán literalmente `TU_SERVIDOR`. Pon tu IP pública o, mejor,
  un dominio (`tu-dominio.com`).
* **Estos puertos no cambian nada en el daemon.** Son los que el panel escribe al
  exportar una línea (botón *Exportar / Config* de cada línea). Tienen que
  **coincidir** con los puertos reales de `/etc/ncam/ncam.conf`:

  ```ini
  [cccam]    port = 12000
  [newcamd]  port = 50000@1B2C3D4E:0102030405060708091011121314
  [camd35]   port = 33333
  [cache]    port = 8181
  ```

  Si cambias un puerto en el daemon, cámbialo también aquí y vuelve a exportar
  las líneas de los clientes afectados, o sus decodificadores seguirán apuntando
  al puerto viejo.

---

## 3. Daemon NCam (WebIf)

Es la conexión entre el panel y el daemon. De aquí sale **todo** lo que el panel
muestra en vivo: estado, estadísticas del motor de caché, peers y los contadores
de ECM del daemon.

| Campo | Clave interna | Por defecto | Qué hace |
| --- | --- | --- | --- |
| URL del WebIf | `panel.ncam_webif_url` | `http://127.0.0.1:8181` | Dirección del WebIf de NCam, con puerto. |
| Usuario del WebIf | `panel.ncam_webif_user` | (el de `.env`) | Usuario para consultar el WebIf. |
| Contraseña del WebIf | `panel.ncam_webif_password` | (el de `.env`) | Contraseña de ese usuario (se guarda y se muestra como `***`). |

Notas prácticas:

* Si el panel y el daemon están en la misma máquina, deja `127.0.0.1`. Si el
  daemon está en otro servidor, usa su IP o dominio: `http://10.0.0.5:8181`.
* Estos tres valores se aplican **en el momento**, sin reiniciar nada. Si te
  equivocas, el panel lo dice en el aviso de caché (`ncam_reachable: false`).
* Para comprobar la conexión desde la consola:

  ```bash
  ncam-ng-ctl status            # estados, puertos y comprobación HTTP
  curl -s --digest -u USUARIO:CLAVE http://127.0.0.1:8181/ncamapi.json?part=status
  ```

* **Recomendado:** crea una cuenta WebIf solo de lectura para el panel (el panel
  no necesita escribir en el daemon) y guarda esa cuenta aquí. La contraseña
  queda cifrada en la base de datos del panel y la API nunca la devuelve.
* Si dejas usuario/contraseña vacíos, el panel usa los del fichero `.env`
  (`NCAM_WEBIF_USER` / `NCAM_WEBIF_PASSWORD`). Los valores de esta pantalla,
  cuando existen, tienen prioridad.

---

## 4. Motor de caché

Estos cuatro ajustes alimentan el bloque `[cache]` **que el panel genera para
NCam-NG**. Ojo: son la plantilla de configuración, **no cambian el daemon por sí
solos** (ver *cómo aplicarlos* abajo).

| Campo | Clave interna | Por defecto | Qué hace |
| --- | --- | --- | --- |
| `max_time` | `ncam.cache.max_time` | `15` | Segundos que una entrada se considera válida. Si no llegan CWs nuevos para una entrada en ese tiempo, se descarta. |
| `max_entries` | `ncam.cache.max_entries` | `0` | Número máximo de entradas ECM en la caché. **`0` = sin límite**; con un límite, el motor expulsa primero las menos usadas (LRU). |
| Cacheex activado | `ncam.cache.cacheex_enable` | `1` | Añade al bloque generado las opciones de caché compartida (`cacheex_dropdiffs`, `cacheex_localgenerated_only`). |
| Muestreo automático | `ncam.cache.panel_poll` | `1` | Si está a `1`, el panel guarda una muestra de métricas **cada 60 s** para los gráficos históricos. A `0`, solo se guardan cuando pulsas *Guardar muestra de métricas*. |

**Cómo aplicarlos al daemon** (no basta con guardar aquí):

1. Menú **Caché y peers** → botón **Exportar configuración** (o *Descargar
   ncam.conf* en Ajustes → Mantenimiento).
2. Copia el bloque `[cache]` dentro de `/etc/ncam/ncam.conf`:

   ```bash
   sudo ncam-ng-ctl config ncam      # abre /etc/ncam/ncam.conf con tu editor
   ```

3. Reinicia el daemon: `sudo restart-ncam`.

Los tres primeros también aparecen en **Caché y peers → Límites** (es el mismo
valor; cambia el que prefieras). El intervalo del muestreo automático (60 s) se
cambia en el `.env` del panel (`NCAM_PANEL_CACHE_POLL_INTERVAL`), no aquí.

---

## 5. Créditos y facturación

### 5.1 Créditos de las líneas

| Campo | Clave interna | Por defecto | Qué hace |
| --- | --- | --- | --- |
| Nombre de la moneda | `billing.currency` | `créditos` | Solo es la etiqueta que se muestra en saldos y movimientos. |
| Coste por línea | `billing.line_cost` | `10` | Créditos que se descuentan al **crear** una línea (se los cobra el panel al propietario, reseller o super admin). |
| Coste por renovación | `billing.renew_cost` | `10` | Créditos que cuesta **renovar** (+días) una línea. |

El super admin puede repartir créditos a un reseller (menú *Revendedores y
usuarios* → *Créditos*) y el reseller a sus usuarios. Todo movimiento queda en el
libro mayor (**Créditos**).

### 5.2 Facturación por consumo real de ECM

| Campo | Clave interna | Por defecto | Qué hace |
| --- | --- | --- | --- |
| Facturar consumo de ECM | `billing.ecm.enabled` | `0` | Activa el cobro automático por ECM servidas. |
| Créditos por bloque | `billing.ecm.price` | `10` | Precio de cada bloque completo. |
| ECM por bloque | `billing.ecm.block` | `1000` | Cuántas ECM (respondidas correctamente, `cwok`) forman un bloque facturable. |
| Segundos entre mediciones | `billing.ecm.interval_seconds` | `900` | Cada cuánto mide y factura (mínimo 60; por defecto cada 15 min). |
| Suspender con deuda | `billing.ecm.suspend_on_debt` | `0` | Si el propietario se queda sin saldo, suspende la línea hasta que recargue. |

Cómo funciona (importante para que no haya sorpresas):

* El panel lee del daemon el **contador acumulado de ECM servidas** de cada
  cuenta y calcula el avance desde la última medición.
* **Solo se cobran bloques completos y nunca por adelantado**: si hay 1 250 ECM
  con bloque de 1 000, se cobra un bloque y las 250 restantes quedan pendientes
  para la siguiente facturación.
* Si el propietario no tiene saldo, lo pendiente **no se pierde ni se cobra de
  más**: se cobrará cuando tenga crédito (o la línea se suspende si activaste
  *Suspender con deuda*).
* Si reinicias el daemon, sus contadores vuelven a cero: el panel lo detecta y
  **no inventa consumo**.
* Ejemplo de cálculo: bloque = `1000`, precio = `10` → 0,01 crédito por ECM. Una
  línea que ha servido 250 000 ECM = 250 bloques = **2 500 créditos**.

Para probarlo: menú **Consumo de ECM** → *Simular* (calcula sin cobrar) →
*Medir ahora* (solo refresca contadores) → *Facturar ahora* (cobra de verdad).

---

## 6. Avisos de caducidad

### 6.1 Interruptores generales

| Campo | Clave interna | Por defecto | Qué hace |
| --- | --- | --- | --- |
| Avisos de caducidad activados | `notify.enabled` | `0` | Interruptor maestro: sin esto no se envía nada, aunque el canal esté activo. |
| Días de antelación | `notify.days_before` | `3` | Con cuántos días de antelación avisar. Cada línea puede tener sus propios días (*Avisos de caducidad* → columna *Aviso*); si está vacío, se usa este valor. |
| Segundos entre revisiones | `notify.interval_seconds` | `3600` | Cada cuánto se comprueba si hay líneas por caducar (mínimo 60; 3600 = cada hora). |

### 6.2 Email

| Campo | Clave interna | Ejemplo |
| --- | --- | --- |
| Enviar por email | `notify.channel.email` | `1` |
| Servidor SMTP | `notify.smtp.host` | `smtp.gmail.com` |
| Puerto SMTP | `notify.smtp.port` | `587` |
| Usuario SMTP | `notify.smtp.user` | `tucorreo@gmail.com` |
| Contraseña SMTP | `notify.smtp.password` | contraseña **de aplicación** |
| Remitente | `notify.smtp.from` | `NCPanel <tucorreo@gmail.com>` |
| Usar STARTTLS | `notify.smtp.starttls` | `1` |

Ejemplo completo con Gmail:

1. Activa la verificación en dos pasos en tu cuenta de Google.
2. Crea una **contraseña de aplicación** (Cuenta de Google → Seguridad →
   Contraseñas de aplicaciones) y úsala en *Contraseña SMTP* — la contraseña
   normal de Gmail **no** funciona.
3. Rellena: `smtp.gmail.com`, `587`, tu correo, la contraseña de aplicación,
   remitente `NCPanel <tucorreo@gmail.com>`, STARTTLS `1`.
4. Guarda y pulsa *Probar email* en el menú **Avisos de caducidad**.

> El panel usa SMTP normal con STARTTLS: el puerto **465 (SSL directo) no está
> soportado**. Usa 587 (o 25 si tu servidor lo permite).

### 6.3 Telegram

| Campo | Clave interna | Ejemplo |
| --- | --- | --- |
| Enviar por Telegram | `notify.channel.telegram` | `1` |
| Token del bot | `notify.telegram.bot_token` | `123456789:AAF...` |
| Chat por defecto | `notify.telegram.chat_id` | `123456789` |

Cómo obtener token y chat:

1. Habla con **@BotFather** en Telegram → `/newbot` → copia el **token**.
2. Escríbele algo a tu bot (necesario para que exista el chat) y abre
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`: el `chat.id` que aparece
   es el valor de *Chat por defecto*.
3. Guarda y pulsa *Probar Telegram*.

### 6.4 Qué se envía y cuándo

* Se avisa **una vez por línea y canal cada 20 horas** como máximo, y nunca dos
  veces con los mismos días restantes (así no recibes el mismo aviso en bucle).
* Destino: el email/chat de la línea si lo tiene; si no, el del propietario y el
  chat por defecto del panel.
* Todo intento queda registrado (enviado, fallido u omitido) en **Avisos de
  caducidad → historial**, con el motivo del fallo si lo hubo.
* Ejemplo de asunto: `[NCPanel] La línea 'cliente-juan' caduca en 3 días`.

---

## 7. Mantenimiento

Debajo de los ajustes hay tres acciones:

| Acción | Qué hace | Cuándo usarla |
| --- | --- | --- |
| **Guardar muestra de métricas** | Guarda ahora mismo una foto de las métricas de caché (`cache.hit_ratio`, entradas, hits, misses…). | Si desactivaste el muestreo automático, o antes/después de un cambio para comparar en los gráficos. |
| **Purgar histórico (30 días)** | Borra las muestras de métricas y los intentos de login con más de 30 días. | De vez en cuando, para que `panel.db` no crezca sin control. No afecta a líneas, créditos ni usuarios. |
| **Descargar ncam.user** | Fichero con el bloque `[account]` de todas las líneas activas, listo para el daemon. | Para (re)generar de golpe las cuentas del daemon: pegar en `/etc/ncam/ncam.user` y recargar NCam. |
| **Descargar ncam.server** | Bloque con los peers de caché activos. | Igual, para `/etc/ncam/ncam.server`. |

Tras copiar `ncam.user` / `ncam.server` / `[cache]` en el daemon, recarga NCam
(`sudo restart-ncam`) para que los cambios entren en vigor.

Un reseller también puede descargar **sus** bloques (solo sus líneas y peers),
desde **Caché y peers → Exportar configuración**.

---

## 8. Lo que no está en Ajustes: el `.env` del panel

Estos valores son de **arranque** del servicio, no de la configuración viva, y se
editan en `/opt/ncam-ng-panel/.env` (o con `sudo ncam-ng-ctl config panel`).
Después hay que reiniciar el panel: `sudo restart-ncam-panel`.

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `NCAM_PANEL_HOST` / `NCAM_PANEL_PORT` | `0.0.0.0` / `8080` | En qué dirección y puerto escucha el panel. El puerto se cambia con `sudo ncam-ng-ctl panel port NUEVO` (o editando esta línea y `restart-ncam-panel`). Cada clave **una sola vez** y sin comentario detrás: si está repetida manda la primera; un `#` al final se toma como parte del valor. |
| `NCAM_PANEL_SECRET` | generado al instalar | Clave que firma los tokens de sesión. Si la cambias, se cierran todas las sesiones. |
| `NCAM_PANEL_DB` | `/var/lib/ncam-ng-panel/panel.db` | Ruta de la base de datos SQLite. |
| `NCAM_PANEL_CACHE_POLL` / `NCAM_PANEL_CACHE_POLL_INTERVAL` | `1` / `60` | Muestreo automático del histórico y cada cuántos segundos (luego se puede apagar desde Ajustes con *Muestreo automático*). |
| `NCAM_PANEL_NAME` | `NCPanel` | Nombre por defecto del panel; el valor que manda es el de Ajustes (`panel.name`). |
| `NCAM_PANEL_NOTIFY` | `1` | Arranca el planificador de avisos; el envío real lo decide `notify.enabled` en Ajustes. |
| `NCAM_PANEL_LINE_COST`, `NCAM_PANEL_RENEW_COST`, `NCAM_PANEL_LINE_DAYS`, `NCAM_PANEL_RESELLER_CREDITS`, `NCAM_PANEL_DEFAULT_GROUP` | `10`, `10`, `30`, `100`, `1` | Valores **iniciales** de las reglas de negocio; una vez instalado, manda lo que pongas en Ajustes. |
| `NCAM_PANEL_CORS_ORIGINS` | `*` | Solo si integras el panel desde otro dominio. |
| `NCAM_PANEL_ACCESS_TTL`, `NCAM_PANEL_REFRESH_TTL`, `NCAM_PANEL_MAX_LOGIN_ATTEMPTS`, `NCAM_PANEL_LOGIN_LOCKOUT`, `NCAM_PANEL_PASSWORD_MIN` | 1800, 604800, 8, 300, 10 | Seguridad de sesiones y política de contraseñas. |

Regla para no equivocarse: **¿afecta a cómo arranca el panel (puerto, base de
datos, secreto)?** → `.env` + `restart-ncam-panel`. **¿Es negocio, avisos, caché o
lo que se publica a los clientes?** → pantalla Ajustes, se aplica al guardar.

---

## 9. Recetas rápidas

**Quiero que las líneas exportadas muestren mi dominio**

1. Ajustes → *Host público* = `midominio.com` → Guardar.
2. Comprueba que los 4 puertos coinciden con `/etc/ncam/ncam.conf`.
3. Vuelve a exportar las líneas de los clientes afectados.

**Quiero cambiar el puerto del panel (por ejemplo al 8090)**

1. ```bash
   ncam-ng-ctl panel port             # qué puerto usa ahora y si responde
   sudo ncam-ng-ctl panel port 8090   # cambiarlo y reiniciar el panel
   ```
2. Si el panel se publica por un túnel de Cloudflare, apunta al puerto nuevo:

   ```bash
   sudo nano /etc/cloudflared/config.yml     # service: http://127.0.0.1:8090
   sudo systemctl restart cloudflared
   ```
3. Si no usas túnel y entras por IP, abre el puerto nuevo y cierra el viejo:

   ```bash
   sudo ufw allow 8090/tcp && sudo ufw delete allow 8080/tcp
   ```
4. La URL nueva es `http://TU_IP:8090`. El WebIf del daemon (8181) no cambia.

**Quiero limitar la memoria de la caché a 50 000 entradas**

1. Ajustes → *`max_entries`* = `50000` → Guardar.
2. *Caché y peers* → *Exportar configuración* → copia el bloque `[cache]` en
   `/etc/ncam/ncam.conf`.
3. `sudo restart-ncam` (o WebIf → *Restart*).

**Quiero cobrar por consumo real**

1. Ajustes → *ECM por bloque* = `1000`, *Créditos por bloque* = `10`,
   *Facturar consumo de ECM* = `1` → Guardar.
2. Asegúrate de que los resellers tienen saldo.
3. Menú **Consumo de ECM** → *Simular* para ver lo que se cobraría → *Facturar
   ahora*.

**Quiero avisos por Telegram**

1. BotFather → token; escrito al bot; `getUpdates` → `chat.id`.
2. Ajustes → *Token del bot*, *Chat por defecto*, *Enviar por Telegram* = `1`,
   *Avisos de caducidad activados* = `1` → Guardar.
3. **Avisos de caducidad** → *Probar Telegram* → *Enviar ahora* (o *Simular* para
   ver qué se enviaría sin enviar).

**Cambié el nombre del panel**

Ajustes → *Nombre del panel* → Guardar. Aparecerá en la interfaz y en el asunto
de los avisos.

---

## 10. Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| «Caché no accesible» / `ncam_reachable: false` | URL o credenciales del WebIf mal, o el daemon parado. Prueba `ncam-ng-ctl status` y `curl --digest -u usuario:clave http://127.0.0.1:8181/ncamapi.json?part=status`. |
| Guardé los límites de caché y el daemon no cambia | Son la plantilla de `ncam.conf`: exporta el bloque, cópialo en `/etc/ncam/ncam.conf` y `sudo restart-ncam`. |
| Los avisos no llegan | Revisa que `notify.enabled` = `1` **y** el canal = `1`; usa *Probar*; mira el historial (ahí está el error del SMTP/Telegram). Gmail necesita contraseña de aplicación y puerto 587. |
| El consumo de ECM no sube | La línea tiene que existir en el daemon (exportada y recargada) y haber servido ECM con OK. Pulsa *Medir ahora* en **Consumo de ECM** y mira si `ecm_ok` aparece en el WebIf (`userstats`). |
| Cambié el puerto del panel y ya no responde | Comprueba cuál está usando de verdad: `ncam-ng-ctl panel port`. Cámbialo con `sudo ncam-ng-ctl panel port NUEVO` (o edita `NCAM_PANEL_PORT` con `sudo ncam-ng-ctl config panel` y `sudo restart-ncam-panel`) y abre el puerto nuevo en el cortafuegos. Si el panel se publica por el túnel, actualiza también `cloudflared`. |
| El panel sale «activo» pero no responde en su puerto | Mira primero dónde escucha de verdad (`ncam-ng-ctl panel port`): si el `.env` tiene `NCAM_PANEL_PORT` **repetida**, el panel usa la primera y la herramienta te lo avisa; si la línea lleva un comentario detrás, el valor incluye el `#` y el servicio no arranca. Con eso limpio, `sudo restart-ncam-panel`. El registro (`ncam-ng-ctl logs panel -n 30`) dice el motivo exacto si el puerto estaba ocupado. |
| Quiero mover el panel a otro puerto (el 8080 está ocupado) | `sudo ncam-ng-ctl panel port 8090`: valida el número, avisa si el puerto está ocupado, lo escribe en el `.env` (con copia de seguridad), reinicia y comprueba que el panel responde en el nuevo. Si lo publicas por Cloudflare, apunta el túnel al puerto nuevo y `sudo systemctl restart cloudflared`. |
| Un campo de contraseña muestra `***` | Es normal: significa que hay un valor guardado y que no se devuelve en claro. Escribe encima para cambiarlo o vacíalo para borrarlo. |
| ¿Puedo editar `panel.db` con `nano`? | **No.** Es SQLite; editarlo a mano lo corrompe. Usa la interfaz o `sqlite3`. |

---

## 11. Referencia completa

| Clave | Por defecto | Valores |
| --- | --- | --- |
| `panel.name` | `NCPanel` | texto |
| `panel.public_host` | `TU_SERVIDOR` | IP o dominio |
| `panel.port.cccam` | `12000` | 1–65535 |
| `panel.port.newcamd` | `50000` | 1–65535 |
| `panel.port.camd35` | `33333` | 1–65535 |
| `panel.port.cacheex` | `8181` | 1–65535 |
| `panel.ncam_webif_url` | `http://127.0.0.1:8181` | URL |
| `panel.ncam_webif_user` | (`.env`) | texto |
| `panel.ncam_webif_password` | (`.env`) | texto (secreto) |
| `ncam.cache.max_time` | `15` | segundos |
| `ncam.cache.max_entries` | `0` | entero, `0` = sin límite |
| `ncam.cache.cacheex_enable` | `1` | `1` / `0` |
| `ncam.cache.panel_poll` | `1` | `1` / `0` |
| `billing.currency` | `créditos` | texto |
| `billing.line_cost` | `10` | entero ≥ 0 |
| `billing.renew_cost` | `10` | entero ≥ 0 |
| `billing.ecm.enabled` | `0` | `1` / `0` |
| `billing.ecm.price` | `10` | entero ≥ 0 |
| `billing.ecm.block` | `1000` | entero ≥ 1 |
| `billing.ecm.interval_seconds` | `900` | ≥ 60 |
| `billing.ecm.suspend_on_debt` | `0` | `1` / `0` |
| `notify.enabled` | `0` | `1` / `0` |
| `notify.days_before` | `3` | entero ≥ 0 |
| `notify.interval_seconds` | `3600` | ≥ 60 |
| `notify.channel.email` | `0` | `1` / `0` |
| `notify.smtp.host` | — | hostname |
| `notify.smtp.port` | `587` | 1–65535 |
| `notify.smtp.user` | — | texto |
| `notify.smtp.password` | — | texto (secreto) |
| `notify.smtp.from` | — | email / `Nombre <email>` |
| `notify.smtp.starttls` | `1` | `1` / `0` |
| `notify.channel.telegram` | `0` | `1` / `0` |
| `notify.telegram.bot_token` | — | token (secreto) |
| `notify.telegram.chat_id` | — | id numérico o `@canal` |

### Cambiar ajustes desde la API (para scripts)

```bash
# sesión de super admin
TOKEN=$(curl -s -X POST http://127.0.0.1:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"TU_CLAVE"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# cambiar valores (solo claves de la tabla de referencia)
curl -s -X PATCH http://127.0.0.1:8080/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"values":{"panel.public_host":"midominio.com","billing.ecm.enabled":"1"}}'
```

---

*Ver también: [`../INSTALL.md`](../INSTALL.md) (instalación y problemas
frecuentes), [`cache-engine.md`](cache-engine.md) (motor de caché NCam-NG) y
[`../panel/README.md`](../panel/README.md) (API del panel).*
