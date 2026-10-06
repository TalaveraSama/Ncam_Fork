# NCam-NG

**NCam-NG** es la evolución de [NCam](https://github.com/fairbird/NCam) (a su vez
basado en [OSCam](https://svn.streamboard.tv/oscam/trunk/) y
[oscam-emu](https://github.com/oscam-emu/oscam-patched)) con dos aportaciones
principales:

1. **Motor de caché v2** dentro del daemon: monitorización completa, límite de
   capacidad con expulsión LRU, API JSON nativa y contadores de rendimiento.
2. **Panel de gestión web** (`panel/`) con roles de **super administrador** y
   **reseller**: líneas, créditos, usuarios finales, peers de caché, auditoría y
   métricas — integrado con el motor de caché del daemon.

> **Releases:** <https://github.com/TalaveraSama/Ncam_Fork/releases> — paquetes
> `.deb` del daemon y del panel listos para instalar.

> Copyright: NCam-NG mantiene la licencia **GPL v3** del proyecto original.
> NCam es Copyright (C) 2012-2018 Javilonas y Copyright (C) 2015-2025 RAED
> (Fairbird); OSCam es Copyright (C) 2009-2026 de los desarrolladores de OSCam.

---

## 1. Motor de caché v2 (NCam-NG)

### Qué se añadió

| Función | Descripción |
|---|---|
| **Estadísticas internas** | Contadores de consultas, aciertos, fallos, CW nuevas/actualizadas, rechazos por ciclo CW, expulsiones por TTL y por capacidad, y estimación de memoria. |
| **Capacidad con LRU** | Nueva opción `[cache] max_entries`: cuando la caché alcanza el límite se expulsan las entradas menos usadas recientemente (por `upd_time`), en lotes para mantener corto el bloqueo de escritura. |
| **Endurización del *hot path*** | El contaje se hace sin locks adicionales y con un único punto de salida en `check_cache()`. |
| **Código refactorizado** | La liberación de un contenedor ECM (`cache_free_ecmhash()`) se comparte entre la limpieza periódica y la expulsión LRU; `cleanup_cache()` usa una sola marca de tiempo por barrido. |
| **API JSON** | `GET /ncamapi.json?part=cachestats` con todo el estado del motor, incluidas las CW más servidas; `&action=reset` reinicia los contadores. |
| **Página del WebIf** | `cacheengine.html` en el WebIf clásico: contadores, hit ratio, entradas más servidas, peers cacheex y últimas muestras del histórico (se auto-alimenta cada 30 s). |
| **Pruebas** | `devtools/run-cache-test.sh` compila el motor real (`ncam-cache.c`) contra stubs y verifica inserciones, aciertos, contabilidad, capacidad/LRU y expiración. |

### Configuración

```ini
[cache]
delay        = 120
max_time     = 15      ; segundos que un ECM permanece en la caché
max_entries  = 0       ; NCam-NG: 0 = ilimitado; p. ej. 200000 en equipos con poca RAM
max_hit_time = 15
```

### Consulta de métricas

```bash
curl -s "http://127.0.0.1:8181/ncamapi.json?part=cachestats" | jq .ncam.cachestats
```

```json
{
  "engine": "NCam-NG cache engine",
  "max_entries": "0", "max_time": "15",
  "entries": "137", "cw_entries": "168", "mem_bytes": "124224",
  "lookups": "49415", "hits": "41241", "misses": "8174", "hit_ratio": "83.46",
  "cw_new": "15421", "cw_upd": "25811", "cwc_rejected": "3",
  "evicted_ttl": "9820", "evicted_lru": "0",
  "cw_cache": { "entries": "42", "mem_bytes": "20480", "localgenerated": "7" },
  "hot_entries": [
    { "caid": "0100", "prid": "000000", "srvid": "0001", "hits": "8421",
      "from_csp": "0", "from_cacheex": "1", "from_localcards": "0" }
  ]
}
```

### Pruebas del motor de caché

```bash
devtools/run-cache-test.sh     # no requiere compilar el daemon completo
```

---

## 2. Panel de gestión (super admin + reseller)

Ubicado en `panel/`. Se instala en segundos y se conecta al WebIf de NCam para
leer, en vivo, las métricas del motor de caché.

```bash
devtools/install-panel.sh --demo     # venv + dependencias + .env + super admin

# equivalente a mano:
cd panel
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# variables de entorno (o copiar .env.example a .env)
export NCAM_WEBIF_URL="http://127.0.0.1:8181"
export NCAM_PANEL_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"

# crea el super administrador (imprime la contraseña una sola vez)
PYTHONPATH=backend python3 -m app.seed --username admin
# (opcional) datos de demostración
PYTHONPATH=backend python3 -m app.seed --demo

./run.sh          # http://localhost:8080
```

### Roles

| Rol | Permisos |
|---|---|
| **super_admin** | Control total: crea/edita **resellers** y usuarios, emite y ajusta créditos, define ajustes globales y del motor de caché, ve toda la auditoría. |
| **reseller** | Gestiona **sus** líneas y **sus** usuarios finales, con saldo de créditos que se descuenta al crear/renovar líneas; puede transferir créditos a sus usuarios y rotar su API key. No ve datos de otros resellers. |
| **user** | Solo lectura de sus propias líneas (credenciales, caducidad) y su saldo. |

### Consumo y facturación por ECM

El panel lee del daemon las ECM servidas por cada cuenta y factura al propietario
los **bloques completos** (`billing.ecm.block` ECM a `billing.ecm.price`
créditos), nunca por adelantado: si el saldo no alcanza, el resto queda pendiente.
Incluye libro mayor, histórico de mediciones, detección de reinicio del daemon y
suspensión opcional por deuda. Vista **Consumo ECM** y endpoints
`/api/v1/billing/ecm*`.

### Avisos de caducidad

El panel avisa (por **email** y/o **Telegram**) cuando una línea está a punto de
expirar: antelación global o por línea, destinos propios o heredados del
propietario, planificador automático, envío manual/simulado e histórico de
avisos. Se configura en la vista **Ajustes** (`notify.*`) y se prueba con un
botón desde la vista **Avisos de caducidad**.

Detalles completos en [`panel/README.md`](panel/README.md).

---

## 3. Instalación

### Con paquetes `.deb` (lo más rápido)

Cada release publica los paquetes del daemon y del panel para amd64
(Debian/Ubuntu) junto a un instalador que verifica su SHA-256:

```bash
curl -fsSL -o install-deb.sh \
  https://github.com/TalaveraSama/Ncam_Fork/releases/latest/download/install-deb.sh
sudo sh install-deb.sh          # deja los servicios ncam y ncam-panel activos
```

Los paquetes se compilan en Ubuntu 22.04 (funcionan en Ubuntu 22.04/24.04 y
Debian 12/13). Tras instalarlos, `sudo ncam-ng-install-deb` actualiza (o repara)
la instalación con la última release.
¿Prefieres construir los paquetes tú mismo? `devtools/build-deb.sh --with-wheels`
genera los `.deb` en `dist/`, y el workflow
[`.github/workflows/release.yml`](.github/workflows/release.yml) los publica al
empujar una etiqueta `v*`.

### Desde el código

Guía paso a paso (daemon + panel, con systemd y problemas frecuentes):
[`INSTALL.md`](INSTALL.md).

Servicios systemd para que daemon y panel arranquen solos y sobrevivan al cierre
de la terminal:

```bash
sudo devtools/install-systemd.sh
```

### Compilación del daemon

Igual que el NCam original (Makefile / CMake con soporte de toolchains):

```bash
./config.sh --enable all            # o ./config.sh --help para opciones
make -j"$(nproc)"
```

El binario resultante queda en `Distribution/` y se instala con:

```bash
sudo devtools/install-daemon.sh --with-config   # binario + ejemplos de configuración
```

Consulta `INSTALL.md` para la guía completa y `Distribution/doc/` para la
documentación de configuración clásica.

---

## 4. Estructura del repositorio

```
├── ncam-cache.c / ncam-cache.h     # motor de caché (v2: estadísticas + LRU)
├── module-webif.c                  # endpoint /ncamapi.json?part=cachestats
├── webif/api.json/cachestats*.json # plantillas JSON del nuevo endpoint
├── webif/cache/cache.html          # página del motor de caché del WebIf
├── devtools/cache-engine-test.c    # banco de pruebas del motor de caché
├── devtools/run-cache-test.sh
├── devtools/build-deb.sh           # construye los paquetes .deb
├── devtools/install-deb.sh         # descarga e instala los .deb de una release
├── packaging/                      # control, servicios systemd y scripts de los .deb
├── .github/workflows/release.yml   # compila y publica los .deb al etiquetar v*
├── Distribution/doc/example/ncam.conf
├── docs/cache-engine.md            # documentación técnica del motor v2
└── panel/                          # panel de gestión (super admin / reseller)
    ├── backend/app/                # API FastAPI + SQLite
    ├── backend/tests/              # 64 pruebas automatizadas
    ├── frontend/                   # SPA en JavaScript puro
    └── tools/mock_ncam_webif.py    # simulador del WebIf para desarrollo
```

## 5. Pruebas

```bash
devtools/run-cache-test.sh                        # motor de caché (C): 37 comprobaciones
cd panel/backend && python3 -m pytest             # API del panel (Python): 64 pruebas
```

## 6. Aviso legal

Este software se distribuye bajo **GPL v3** (ver `COPYING`). Debe usarse
únicamente con contenido y tarjetas a los que el operador esté autorizado a
acceder. Los autores no se responsabilizan del uso indebido.
