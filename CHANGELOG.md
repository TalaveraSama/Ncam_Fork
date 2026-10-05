# Changelog

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

### Pruebas

* `devtools/cache-engine-test.c` + `devtools/run-cache-test.sh`: compilan el motor
  de caché real con stubs y verifican 37 comportamientos (inserciones, aciertos,
  contabilidad, entradas calientes, capacidad con LRU, histórico de muestras,
  formateo de tamaños y expiración). No requiere cross-compilar el daemon.

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
