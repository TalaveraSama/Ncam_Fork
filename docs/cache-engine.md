# Motor de caché v2 de NCam-NG

Documentación técnica de los cambios introducidos en `ncam-cache.c` /
`ncam-cache.h` y de su exposición a través del WebIf.

---

## 1. Estructura de la caché (sin cambios)

```
ht_cache (hash por csp_hash)
└── ECMHASH                       contenedor por ECM/csp_hash
    ├── first_recv_time           creación (orden del listado ll_cache)
    ├── upd_time                  última CW recibida (base del LRU)
    ├── ht_cw / ll_cw
    │   └── CW                    control word + metadatos de origen
    │       ├── cw[16], odd_even, caid, prid, srvid
    │       ├── count             veces que se ha servido (bit 0x0F000000 = local)
    │       ├── csp/cacheex/localcards/proxy
    │       ├── selected_reader, cacheex_src
    │       └── pushout_client    clientes a los que ya se ha enviado
    └── ll_node                   orden de creación
```

## 2. Novedades

### 2.1 Contadores (`struct s_cache_stats`)

Se actualizan desde los caminos de lectura/escritura existentes, sin locks
adicionales (contadores *best effort*, igual que el resto de estadísticas del
proyecto). En `check_cache()` hay un único punto de salida que clasifica cada
consulta como acierto o fallo.

| Campo | Significado |
|---|---|
| `lookups` | Llamadas a `check_cache()`. |
| `hits` / `misses` | Consultas resueltas / no resueltas por la caché interna. |
| `csp_entries` / `cw_entries` | Contenedores y control words actuales (contadores mantenidos, sin recorrer el *hash*). |
| `cw_new` / `cw_upd` | CW almacenadas por primera vez / ya conocidas. |
| `cwc_rejected` | CW descartadas por el *cw cycle check*. |
| `evicted_ttl` / `evicted_lru` | Contenedores expulsados por `max_time` / por límite de capacidad. |
| `mem_bytes` | Estimación: `sizeof(CW)·cw_entries + Σ (sizeof(ECMHASH) + tommy_hashlin_memory_usage(ht_cw))`. |

### 2.2 Capacidad con expulsión LRU

```ini
[cache]
max_entries = 200000   ; 0 = ilimitado (comportamiento anterior)
```

* Se comprueba al crear un **nuevo** contenedor (`find_hash_table()` fallido).
* El lote de expulsión es `max_entries / 32`, acotado a `[8, 64]` entradas, para
  que el bloqueo de escritura no se alargue.
* La selección de las víctimas se hace en **una sola pasada** sobre `ll_cache`
  manteniendo un array parcialmente ordenado por `upd_time` → coste `O(n)` por
  lote (no `O(k·n)`).
* Solo se expulsa hasta volver a estar por debajo del límite.

### 2.3 Refactor de liberación

`cache_free_ecmhash()` agrupa la destrucción de un contenedor (locks de push,
liberación de CWs, contadores `lg_cache_size`, `cache_cw_total`,
`cache_csp_total`, `deinitialize_hash_table()`, desenlace de las listas). La
usan tanto `cleanup_cache()` como `cache_evict_lru()`.

Además `cleanup_cache()`:

* calcula `now` **una vez** por barrido (antes, por contenedor),
* cuenta las expulsiones por TTL,
* registra un resumen en nivel `D_TRACE`.

## 3. API JSON

```
GET /ncamapi.json?part=cachestats
GET /ncamapi.json?part=cachestats&action=reset      (requiere WebIf con escritura)
GET /ncamapi.json?part=cachestats&callback=miFuncion  (JSONP, igual que el resto)
```

* Plantillas: `webif/api.json/cachestats.json` y `cachestats_hotbit.json`
  (registradas en `webif/pages_index.txt`).
* Construido en `send_ncam_cachestats()` (`module-webif.c`); añadido al
  enrutador `send_ncam_api()` como `part=cachestats`.
* `CACHE_TOP_ENTRIES_REPORTED` (en `ncam-cache.h`) controla cuántas entradas
  "calientes" se devuelven (20 por defecto).
* Los valores numéricos se devuelven entrecomillados, igual que el resto del
  API JSON de NCam; el panel los convierte al leerlos.

## 4. Pruebas

```bash
devtools/run-cache-test.sh
```

El banco de pruebas compila **el fichero real** `ncam-cache.c` junto con
`ncam-hashtable.c`, `ncam-llist.c`, `ncam-string.c`, `ncam-time.c`,
`ncam-lock.c` y los stubs de las funciones del daemon que la caché necesita
(log, `cs_malloc`, `checkcwcycle`, `get_cwcheck`, `cacheex_cache_push`...).
Verifica: inserciones y aciertos, contabilidad de CW nuevas/actualizadas,
listado de entradas calientes, límite de capacidad con LRU y expiración por
`max_time`.

## 5. Compatibilidad

* Sin cambios en el formato de datos ni en el protocolo cacheex.
* `max_entries = 0` (valor por defecto) reproduce exactamente el
  comportamiento anterior: solo expira por `max_time`.
* Los equipos con poca memoria pueden fijar `max_entries` (p. ej. 2000-5000 en
  routers) y el daemon mantendrá la caché acotada sin reinicios.
