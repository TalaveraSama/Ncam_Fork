# NCPanel

Panel de gestión web (parte del proyecto **NCam-NG**) con dos roles principales:
**super administrador** (control total) y **reseller** (revendedor con saldo de
créditos). Incluye además un rol de **usuario final** de solo lectura.

* Backend: **FastAPI + SQLite** (biblioteca estándar para la base de datos,
  JWT HS256 y hash PBKDF2 implementados sin dependencias externas).
* Frontend: **SPA en JavaScript puro** (sin CDN, sin build, funciona offline).
* Integración: lee las métricas del **motor de caché v2** del daemon NCam a
  través de `/ncamapi.json?part=cachestats` y genera los bloques de
  configuración (`ncam.conf`, `ncam.user`, `ncam.server`).
* Autenticación contra el WebIf: **Digest MD5** (la que usa NCam cuando se define
  `httpuser`/`httppwd`) con Basic como alternativa.

---

## 1. Instalación

> Guía completa (daemon + panel, systemd y problemas frecuentes) en
> [`../INSTALL.md`](../INSTALL.md). La pantalla **Ajustes** está explicada campo
> por campo en [`../docs/ajustes.md`](../docs/ajustes.md).

**Con paquete `.deb`** (recomendado en un servidor): instala el panel en
`/opt/ncam-ng-panel` con su servicio systemd, crea `/opt/ncam-ng-panel/.env` y la
base de datos en `/var/lib/ncam-ng-panel/panel.db`, y arranca solo:

```bash
sudo sh install-deb.sh --panel-only         # desde la release
sudo systemctl status ncam-panel
sudo ncam-ng-panel-setup --online           # reinstalar dependencias de Python
```

**Desde el código:**

```bash
# desde la raíz del repositorio (requirements.txt está en panel/)
devtools/install-panel.sh --demo      # venv + dependencias + .env + super admin

cd panel && ./run.sh                  # http://localhost:8080
```

A mano: `cd panel && python3 -m venv .venv && . .venv/bin/activate && pip install
-r requirements.txt && cp .env.example .env && ./run.sh`.

Crear el **super administrador** (la contraseña se muestra una única vez):

```bash
PYTHONPATH=backend python3 -m app.seed --username admin
# datos de demostración (reseller, usuario, líneas y un peer de caché):
PYTHONPATH=backend python3 -m app.seed --demo
# ¿perdiste la contraseña? genera otra (imprime la nueva una única vez):
PYTHONPATH=backend python3 -m app.seed --username admin --reset-password
```

**Más administradores** (todos con control total), sin volver a instalar nada:

```bash
# en el servidor, con el paquete .deb instalado:
sudo ncam-ng-ctl admin add maria                  # super admin (clave aleatoria)
sudo ncam-ng-ctl admin add luis reseller          # otro rol
sudo ncam-ng-ctl admin role maria reseller        # cambia el rol de una cuenta
sudo ncam-ng-ctl admin                            # lista las cuentas

# desde el código (mismo programa que usa el comando anterior):
PYTHONPATH=backend python3 -m app.seed --create --username maria --role super_admin
PYTHONPATH=backend python3 -m app.seed --list
PYTHONPATH=backend python3 -m app.seed --set-role maria reseller
PYTHONPATH=backend python3 -m app.seed --delete maria
```

También desde la web: **Revendedores y usuarios** → *Nueva cuenta* → **Rol →
Administrador**; en la ficha de una cuenta puedes cambiarle el rol. Reglas:

* solo un **super admin** puede crear o ascender a otro super admin (un reseller
  recibe `403`), y nadie puede cambiarse el rol a sí mismo;
* el panel **nunca se queda sin administrador activo**: no se puede degradar,
  suspender ni borrar al último (la API responde `400` y la web esconde el botón);
* cambiar de rol no borra las líneas de la cuenta.

Todo esto, con ejemplos y preguntas frecuentes, en
[`../docs/administradores.md`](../docs/administradores.md).

### Variables de entorno principales

| Variable | Por defecto | Descripción |
|---|---|---|
| `NCAM_PANEL_HOST` / `NCAM_PANEL_PORT` | `0.0.0.0` / `8080` | Escucha del panel. |
| `NCAM_PANEL_SECRET` | generado en `panel/.secret_key` | Clave de firma de los JWT. |
| `NCAM_PANEL_DB` | `panel/backend/data/panel.db` (`.deb`: `/var/lib/ncam-ng-panel/panel.db`) | Ruta de SQLite. |
| `NCAM_WEBIF_URL` | `http://127.0.0.1:8181` | WebIf del daemon NCam. |
| `NCAM_WEBIF_USER` / `NCAM_WEBIF_PASSWORD` | vacío | Si el WebIf pide autenticación. |
| `NCAM_PANEL_CACHE_POLL` / `_INTERVAL` | `1` / `60` | Muestreo periódico de métricas de caché. |
| `NCAM_PANEL_LINE_COST` / `_RENEW_COST` | `10` / `10` | Coste en créditos de alta/renovación. |
| `NCAM_PANEL_CORS_ORIGINS` | `*` | Orígenes permitidos si integra el panel desde otro dominio. |

## 2. Roles y reglas de negocio

### Super administrador
* Crea, edita y elimina **resellers** y usuarios; fija límites de líneas.
* **Emite créditos** (recargas) y ajusta saldos; ve el libro mayor completo.
* Define ajustes globales, del panel y del **motor de caché** (`max_time`,
  `max_entries`, cacheex) y exporta la configuración para el daemon.
* Ve la auditoría completa y puede purgar el histórico de métricas.

### Reseller
* Gestiona **sus** líneas y **sus** usuarios finales — nunca los de otro reseller.
* Su saldo se descuenta al crear (`billing.line_cost`) y renovar
  (`billing.renew_cost`) líneas; si no hay saldo, la operación se rechaza con
  400 y no deja rastro.
* Puede **transferir créditos** a sus usuarios finales.
* Gestiona sus propios **peers de caché**, con prueba de conectividad TCP.
* Dispone de **API key** (`X-API-Key`) para integrar sus sistemas.
* Solo ve su parte de la auditoría.

### Usuario final
* Solo lectura: sus líneas (credenciales, caducidad, estado) y su saldo.

### Permisos por CAID de cada línea
Cada línea tiene el campo **CAIDs permitidos**, que se exporta como la línea
`caid = …` del bloque `[account]` en `ncam.user`:

| Valor en el panel | Efecto en el daemon |
| --- | --- |
| vacío | sin restricción: el cliente ve todos los CAID de sus grupos |
| `1801` | solo ese CAID (`invalid caid` para el resto) |
| `1801,1861,0B00` | los tres |

Se normaliza y valida al guardar (`1801`, `1801&FFFF`, `1861:01`, separados por
comas; los CAID inválidos se rechazan con `422`). La tabla de líneas muestra los
CAID de cada una bajo el protocolo.

Cada línea tiene además:

* **Conexiones máximas** → `max_connections = N` del `[account]`: conexiones
  simultáneas que admite esa cuenta (`1` por defecto).
* **Saltos CCcam** (`cccmaxhops`, por defecto `1`) → cuántos saltos de tarjeta ve
  el cliente. `1` = solo tus tarjetas directas; `-1` = el cliente no ve ninguna
  tarjeta (bloqueo); valores mayores para revendedores.

## 3. API REST (resumen)

Autenticación (`/api/v1/auth`)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/auth/login` | Devuelve `access_token` (30 min) y `refresh_token` (7 días). |
| POST | `/auth/refresh` | Rotación de refresh token (el anterior se revoca). |
| POST | `/auth/logout` | Revoca el refresh token. |
| GET | `/auth/me` | Datos de la sesión. |
| POST | `/auth/password` | Cambio de contraseña (invalida sesiones). |

Cuentas (`/api/v1/accounts`)

```
GET    /accounts?search=&role=            listado según el rol
POST   /accounts                          crear reseller (super) o usuario (reseller)
GET    /accounts/{id}                     detalle
PATCH  /accounts/{id}                     editar (contraseña, estado, créditos*, límite*)
DELETE /accounts/{id}
POST   /accounts/{id}/credits             emitir créditos         (solo super admin)
POST   /accounts/{id}/transfer            transferir créditos     (reseller/super)
POST   /accounts/{id}/api-key             rotar API key           (devuelve la clave 1 vez)
GET    /accounts/transactions             libro mayor
```

Líneas (`/api/v1/lines`)

```
GET    /lines?owner_id=&protocol=&search=
POST   /lines                             alta (descuenta créditos)
GET    /lines/{id}
PATCH  /lines/{id}
DELETE /lines/{id}
POST   /lines/{id}/renew                  +N días (descuenta créditos)
POST   /lines/{id}/reset-password
GET    /lines/{id}/password               consulta explícita (auditada)
GET    /lines/{id}/export?format=         ncam | cccam | newcamd | camd35 | json
```

Avisos de caducidad (`/api/v1/notifications`)

```
GET    /notifications/expiring?days=      líneas por caducar visibles para el usuario
POST   /notifications/run                 envía los avisos (dry_run para simular)
GET    /notifications/log                 histórico de avisos enviados
GET    /notifications/config              configuración activa (sin secretos)
POST   /notifications/test                mensaje de prueba (super admin)
```

Caché (`/api/v1/cache`)

```
GET    /cache/stats                       estado del motor (en vivo) + histórico + peers
POST   /cache/stats/snapshot              guardar una muestra de métricas
GET    /cache/stats/history?metric=&hours=
GET    /cache/limits                      límites configurados para NCam
GET    /cache/config                      bloques ncam.conf / ncam.user / ncam.server
GET    /cache/config/download?file=
GET    /cache/servers                     CRUD de peers cacheex
POST   /cache/servers/{id}/test           prueba TCP real (latencia/error)
GET    /cache/servers/{id}/config         bloque [reader] para ncam.server
```

Estadísticas, administración y metadatos

```
GET    /stats/overview      GET /stats/expiring?days=     GET /stats/timeseries?metric=
GET    /settings            PATCH /settings               (super admin, lista blanca)
GET    /audit-logs?action=&actor_id=&limit=
POST   /maintenance/purge?days=
GET    /meta                GET /health
```

### Ejemplos

```bash
# login
TOKEN=$(curl -s -X POST localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"TU_CLAVE"}' | jq -r .access_token)

# crear un reseller con 500 créditos
curl -s -X POST localhost:8080/api/v1/accounts -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"rev1","password":"Rev1!Segura","role":"reseller","credits":500,"max_lines":100}'

# crear una línea para él
curl -s -X POST localhost:8080/api/v1/lines -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Cliente 01","protocol":"cccam","owner_id":2,"days":30,"cacheex_mode":1}'

# ver la línea como la vería el cliente
curl -s "localhost:8080/api/v1/lines/1/export?format=cccam" -H "Authorization: Bearer $TOKEN"

# estado del motor de caché de NCam
curl -s localhost:8080/api/v1/cache/stats -H "Authorization: Bearer $TOKEN" | jq
```

### Integración con sistemas propios (API key)

```bash
curl -s localhost:8080/api/v1/lines -H "X-API-Key: ng_xxxxxxxxxxxx"
```

## 3.1 Avisos de caducidad (email / Telegram)

El panel revisa las líneas activas y avisa cuando están a punto de expirar.
El envío se controla desde **Ajustes** (super admin) con estos valores:

| Ajuste | Descripción |
| --- | --- |
| `notify.enabled` | activa el planificador automático (`1`/`0`) |
| `notify.days_before` | días de antelación por defecto |
| `notify.interval_seconds` | cada cuánto revisa (por defecto 3600) |
| `notify.channel.email` / `notify.channel.telegram` | canales activos |
| `notify.smtp.*` | host, puerto, usuario, contraseña, remitente y STARTTLS |
| `notify.telegram.bot_token` / `notify.telegram.chat_id` | bot y chat por defecto |

Cada línea puede sobrescribir el destino (`notify_email`, `notify_telegram`) y
la antelación (`notify_days`) en su propio formulario; si se dejan vacíos se usa
el email del propietario y el chat por defecto del panel.

Endpoints:

```
GET  /api/v1/notifications/expiring?days=7   líneas a punto de caducar
POST /api/v1/notifications/run               envía los avisos (o simula con dry_run)
GET  /api/v1/notifications/log?limit=100     histórico de avisos
GET  /api/v1/notifications/config            resumen de la configuración (sin secretos)
POST /api/v1/notifications/test              mensaje de prueba (super admin)
```

Reglas anti-spam: nunca se repite un aviso para la misma línea y canal con los
mismos días restantes, ni dos veces en 20 horas; los envíos fallidos se
reintentan en la siguiente pasada y quedan registrados con su error.

## 3.2 Facturación por consumo de ECM

El daemon publica en `part=userstats` el contador de ECM servidas por cada cuenta
(`cwok`). El panel cruza ese dato con sus líneas (mismo usuario) y factura por
**bloques completos**, nunca por adelantado:

| Ajuste | Descripción |
| --- | --- |
| `billing.ecm.enabled` | facturación automática periódica (`1`/`0`; por defecto manual) |
| `billing.ecm.block` | ECM por bloque facturable (por defecto 1000) |
| `billing.ecm.price` | créditos por bloque |
| `billing.ecm.interval_seconds` | cada cuánto mide y factura (por defecto 900) |
| `billing.ecm.suspend_on_debt` | suspender la línea si acumula consumo impagado |

```
GET  /api/v1/billing/ecm                 consumo y pendiente por línea
GET  /api/v1/billing/ecm/history         mediciones y cargos
POST /api/v1/billing/ecm/run             mide y factura (dry_run para simular)
POST /api/v1/billing/ecm/refresh         solo mide (super admin)
```

Detalles:

* El contador del daemon se reinicia si el daemon se reinicia: el panel lo
  detecta, anota «reinicio del daemon» y no inventa consumo.
* Si el saldo del propietario no cubre todos los bloques, se cobran los que
  alcance y el resto queda pendiente para la siguiente pasada.
* Las cuentas **super admin** no se facturan a sí mismas.
* Cada cargo queda en el libro mayor con el detalle (`Consumo de N ECM de la
  línea X`) y cada medición en `ecm_usage`.

Para probarlo sin daemon: `python3 tools/mock_ncam_webif.py --port 8181
--users msh1b1lz4n,demo_linea` y apunte `panel.ncam_webif_url` al simulador.

## 4. Integración con el daemon NCam

1. En `ncam.conf` habilite el WebIf e **incluya el motor de caché v2**:

```ini
[webif]
httpport    = 8181
httpuser    = panel
httppwd     = una_clave_larga
# IPs (de quien se conecta) que pueden entrar; 127.0.0.1 basta si el panel
# va en la misma máquina. Para un panel remoto: ncam-ng-ctl webif add TU_IP
httpallowed = 127.0.0.1

[cache]
max_time    = 15
# p. ej. 200000 en servidores con memoria limitada
max_entries = 0
```

> Los comentarios van en su propia línea: NCam solo ignora las líneas que
> **empiezan** por `#`, así que un `#` detrás de un valor se toma como parte del
> valor. Ojo también con la clave: es `httpport`, no `http_port`.

2. En el panel, **Ajustes**: fije `panel.ncam_webif_url`,
   `panel.ncam_webif_user` y `panel.ncam_webif_password`.
3. La vista **Caché y peers** mostrará en vivo: aciertos, entradas, memoria,
   CW nuevas/actualizadas, expulsiones por TTL/LRU, rechazos por ciclo CW, las
   entradas más servidas y el histórico de aciertos (una muestra cada 60 s).
4. El botón **Generar bloques de configuración** produce `ncam.conf`,
   `ncam.user` y `ncam.server` listos para copiar o descargar.

Si el daemon no está accesible, el panel **no falla**: muestra el error y
ofrece el último histórico guardado.

## 5. Pruebas

```bash
cd panel/backend
python3 -m pytest          # 64 pruebas: auth, RBAC, líneas, créditos, caché,
                           # ajustes, auditoría, API keys y suspensión de cuentas
```

## 6. Desarrollo del frontend sin daemon

```bash
python3 panel/tools/mock_ncam_webif.py --port 8181   # simulador del WebIf de NCam
```

Sirve el mismo contrato JSON (`part=cachestats` y `part=status`) con valores
dinámicos, para trabajar en la interfaz sin compilar NCam.

## 7. Seguridad

* Contraseñas con **PBKDF2-SHA256** (260 000 iteraciones, sal por usuario).
* JWT **HS256** firmados con `NCAM_PANEL_SECRET`; rotación y revocación de
  refresh tokens en base de datos.
* Bloqueo temporal tras `NCAM_PANEL_MAX_LOGIN_ATTEMPTS` intentos fallidos.
* RBAC en cada endpoint (`require_super_admin`, `require_manager`) y
  comprobación de propiedad de los recursos.
* Las credenciales del WebIf no se devuelven nunca en claro (`***`).
* Las consultas de contraseñas de línea y los cambios sensibles quedan en la
  **auditoría** con usuario, IP y detalles.
* Las peticiones que escriben van dentro de una transacción: si algo falla, no
  quedan movimientos de créditos a medias.

> Recomendación de despliegue: ponga el panel detrás de HTTPS (nginx/caddy) y
> restrinja el acceso al WebIf de NCam a la red interna.
