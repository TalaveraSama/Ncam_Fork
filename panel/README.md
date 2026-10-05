# NCam-NG Panel

Panel de gestión web para **NCam-NG** con dos roles principales:
**super administrador** (control total) y **reseller** (revendedor con saldo de
créditos). Incluye además un rol de **usuario final** de solo lectura.

* Backend: **FastAPI + SQLite** (biblioteca estándar para la base de datos,
  JWT HS256 y hash PBKDF2 implementados sin dependencias externas).
* Frontend: **SPA en JavaScript puro** (sin CDN, sin build, funciona offline).
* Integración: lee las métricas del **motor de caché v2** del daemon NCam a
  través de `/ncamapi.json?part=cachestats` y genera los bloques de
  configuración (`ncam.conf`, `ncam.user`, `ncam.server`).

---

## 1. Instalación

```bash
cd panel
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # ajuste la URL del WebIf de NCam y el secreto
./run.sh                    # http://localhost:8080
```

Crear el **super administrador** (la contraseña se muestra una única vez):

```bash
PYTHONPATH=backend python3 -m app.seed --username admin
# datos de demostración (reseller, usuario, líneas y un peer de caché):
PYTHONPATH=backend python3 -m app.seed --demo
```

### Variables de entorno principales

| Variable | Por defecto | Descripción |
|---|---|---|
| `NCAM_PANEL_HOST` / `NCAM_PANEL_PORT` | `0.0.0.0` / `8080` | Escucha del panel. |
| `NCAM_PANEL_SECRET` | generado en `panel/.secret_key` | Clave de firma de los JWT. |
| `NCAM_PANEL_DB` | `panel/backend/data/panel.db` | Ruta de SQLite. |
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

## 4. Integración con el daemon NCam

1. En `ncam.conf` habilite el WebIf e **incluya el motor de caché v2**:

```ini
[webif]
http_port = 8181
httplocale = 1
httpuser = panel
httppwd  = una_clave_larga

[cache]
max_time    = 15
max_entries = 0        ; p. ej. 200000 en servidores con memoria limitada
```

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
python3 -m pytest          # 38 pruebas: auth, RBAC, líneas, créditos, caché,
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
