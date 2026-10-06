# Configuración óptima de NCam-NG (3 CAID: 1801, 1861 y 0B00)

Guía para dejar NCam-NG **lo más rápido posible** y con una **caché que guarde
todos los CW que entregan los lectores**, dando a cada usuario permiso para los
tres CAID o solo para uno.

- Ficheros de ejemplo listos para copiar: [`examples/ncam.conf`](../examples/ncam.conf),
  [`examples/ncam.server`](../examples/ncam.server),
  [`examples/ncam.user`](../examples/ncam.user).
- Se instalan también en el servidor, dentro del paquete:
  `/usr/share/doc/ncam-ng/examples/` (los del proyecto) y
  `/usr/share/doc/ncam-ng/examples/optimo/` (estos tres).

> **Aviso legal:** úsalo solo con contenido y tarjetas a los que estés autorizado
> (ver el *Aviso legal* del [README](../README.md)).

---

## 1. Resumen: qué hace cada pieza

```
  proveedor(es) ──►  LECTORES (ncam.server)  ──►  MOTOR DE CACHÉ v2  ──►  USUARIOS (ncam.user)
   C: / N: líneas        caid = 1801,1861,0B00      [cache] de ncam.conf      caid = los que permitas
                                                     guarda el CW 15 s         group = lectores que puede usar
```

| CAID | Sistema | Quién lo usa aquí |
| --- | --- | --- |
| `1801` | Nagravision | Uno de los tres paquetes |
| `1861` | Nagravision | Otro paquete distinto |
| `0B00` | Conax | El tercero |

Los tres son **CAID separados**: cada ECM llega con un CAID y NCam decide si ese
usuario puede pedirlo **por el `caid` de su cuenta**. Así puedes tener clientes
con los tres, o con uno solo, sin tocar los lectores.

**Lo más rápido** se consigue con esta cadena:

1. La caché interna **siempre se consulta primero**, antes de molestar a ningún
   lector: si el ECM está en la caché, NCam responde **en milisegundos** (sin
   viaje al proveedor). No hay que activar nada para esto.
2. Si no hay hit, `lb_mode = 1` + `fallbacktimeout = 2000` eligen el lector bueno
   y no se quedan esperando al que no contesta.
3. El CW que llega **se guarda** (`[cache]`), y esa entrada sirve las siguientes
   peticiones del mismo canal durante `max_time` segundos.
4. `delay = 0` evita cualquier espera añadida al responder con un CW de caché.

---

## 2. Dónde va cada fichero

| Fichero | Contenido | En el paquete `.deb` |
| --- | --- | --- |
| `/etc/ncam/ncam.conf` | `[global]`, `[cache]`, puertos, `[webif]` | es un *conffile* (dpkg respeta tus cambios) |
| `/etc/ncam/ncam.server` | lectores (proveedores, tarjetas, peers) | se crea vacío |
| `/etc/ncam/ncam.user` | usuarios (clientes y revendedores) | se crea vacío |

Copiar los ejemplos y recargar:

```bash
sudo cp examples/ncam.conf   /etc/ncam/ncam.conf     # o edítalo: sudo ncam-ng-ctl config ncam
sudo cp examples/ncam.server /etc/ncam/ncam.server
sudo cp examples/ncam.user   /etc/ncam/ncam.user
sudo nano /etc/ncam/ncam.server      # pon tu proveedor real
sudo nano /etc/ncam/ncam.user        # pon tus clientes reales
sudo restart-ncam
```

> Nombres importantes en los ejemplos: `servidor-proveedor.com`,
> `usuario_del_proveedor`, `clave_del_proveedor`, `CAMBIA_ESTA_CLAVE_1`,
> `nodeid = 0123456789ABCDEF` y `httppwd = CAMBIA_ESTA_CLAVE`. **Cámbialos
> todos.** El `nodeid` genéralo con `openssl rand -hex 8` y no lo cambies luego.

---

## 3. `[global]`: velocidad y balanceo

| Ajuste | Valor | Por qué |
| --- | --- | --- |
| `nice` | `-10` | Más prioridad de CPU: NCam atiende ECM antes que procesos de fondo. |
| `clienttimeout` | `7000` | Máximo que se espera a un cliente (7 s). |
| `fallbacktimeout` | `2000` | Si un lector no responde en 2 s, se pasa al siguiente. **Es la clave de la velocidad**; no lo bajes de 1500 salvo que todos tus proveedores sean muy rápidos. |
| `clientmaxidle` | `300` | Cierra clientes colgados y libera conexiones. |
| `preferlocalcards` | `1` | Pregunta antes a las **tarjetas locales** (si tienes). `0` = pregunta a todos a la vez; `2` = como 1 pero además no usa los peers de cacheex como primera opción (no lo pongas si compartes caché). La caché interna se consulta siempre, con cualquier valor. |
| `dropdups` | `1` | Desconecta **inicios de sesión duplicados** del mismo usuario (evita que dos equipos compartan una línea). Con `uniq = 2` en la cuenta se permite repetir desde la misma IP/NAT. |
| `waitforcards` | `0` | Sin tarjeta en la máquina: no esperar. |
| `readerrestartseconds` | `20` | Reinicia un lector caído tras 20 s (antes 1-5 s puede crear tormentas de reconexión). |
| `lb_mode` | `1` | Reparte las peticiones entre lectores según estadísticas. |
| `lb_save` | `100` | Guarda esas estadísticas para que el reinicio no empiece de cero. |
| `lb_nbest_readers` | `2` | Pide a 2 lectores a la vez como máximo: la respuesta buena llega antes. |
| `lb_retrylimit` | `500` | Límite de reintentos por ECM (evita bucles). |
| `disablecrccws` | `1` | Muchos proveedores mandan el CW con CRC alterado; sin esto verías *not found* aunque el CW sea bueno. Si prefieres limitarlo a tus CAID: `disablecrccws_only_for = 1801:000000;1861:000000;0B00:000000`. |
| `cccam_cfg_enabled` | `1` | Permite leer los `.cfg` de proveedores con formato CCcam. |

`ecmfmt` solo cambia **cómo se escribe el registro**; con
`P: c:0p:s:d:i #ECM_L:l #CW=w HOP:j` ves CAID, SID, duración y saltos en el log,
que es lo que hace fácil diagnosticar.

---

## 4. `[cache]`: que la caché lo guarde todo

Esta sección es el **motor de caché v2 de NCam-NG**. Cada CW que entrega un
lector se guarda como una entrada indexada por el ECM: mientras sea válida, las
peticiones de ese mismo ECM se responden **desde la caché**, sin tocar al
proveedor.

| Ajuste | Valor | Qué hace |
| --- | --- | --- |
| `delay` | `0` | **Milisegundos** de espera antes de contestar con un CW de la caché. `0` = al instante (lo más rápido). Súbelo a `120` solo si tienes tarjeta local y ves "CW cycles": deja llegar antes el CW de la tarjeta. |
| `max_time` | `15` | **Validez de cada entrada** (segundos). El motor borra las entradas que lleven `max_time` sin actualizarse: 15 s cubre el hueco entre refrescos de ECM sin servir nunca un CW caducado. |
| `max_entries` | `0` | **`0` = sin límite**: se guarda todo hasta que caduque por `max_time`. Es lo que quieres para "no perder caché". Si prefieres acotar memoria, pon un número (p. ej. `20000`): al llenarse expulsa primero la entrada usada hace más tiempo (**LRU**, por eso nunca tira la más "caliente"). |
| `max_hit_time` | `15` | Memoria de aciertos para **cacheex**: durante 15 s recuerda que ese `caid/prid/srvid` ya se sirvió (evita reenviar lo mismo a los peers). `0` = desactivar. Sin cacheex no hace nada. |
| `cacheexenablestats` | `0` | Contadores de cacheex **por cliente** en el WebIf. Las estadísticas del motor (entradas, hits, misses, ratio) se ven **siempre** en `cacheengine.html` y en NCPanel, con o sin esta opción. |
| `cacheex_dropdiffs` | `0` | No descartar CW distintos que lleguen por cacheex: se queda el bueno. |
| `cacheex_localgenerated_only` | `0` | Aceptar también entradas que vengan de peers de cacheex. |

**Cómo comprobar que la caché trabaja**: WebIf → *Cache Engine* (o
`http://TU_IP:8181/cacheengine.html`). Ahí ves *entries*, *hits*, *misses* y el
**hit ratio**. En un servidor sano el ratio sube enseguida por encima del 20-30 %.
En NCPanel lo tienes en *Caché y peers* con histórico.

**Compartir caché con otros servidores (cacheex)** — opcional, añade al `[cache]`:

```ini
cacheexenablestats             = 1                     # contadores por cliente en el WebIf
cacheex_mode1_delay            = 1801:120,1861:120,0B00:120
cw_cache_size                  = 8192
cw_cache_memory                = 8
ecm_cache_size                 = 8192
ecm_cache_memory               = 8
```

(`cw_cache_*` y `ecm_cache_*` son la caché de CW/ECM usada para el intercambio con
los peers; con `0` están apagadas, que es lo correcto si no compartes caché.)

y en el lector del peer `cacheex = 3` (ver §6.4). Lo que llegue de un peer se
guarda en la misma caché: tus clientes normales lo aprovechan igual, sin que ellos
sean usuarios de cacheex.

---

## 5. `[cccam]` y `[newcamd]`: servir a tus clientes

```ini
[cccam]
port            = 12000
nodeid          = 0123456789ABCDEF   # tuyo, fijo, generado con openssl rand -hex 8
version         = 2.3.2
reshare         = 0                  # 0 = tus tarjetas no se reenvían más; súbelo si tus clientes revenden
stealth         = 1                  # no revelar datos internos del servidor
keepconnected   = 1                  # evita reconexiones constantes
updateinterval  = 3600
autosidblock    = 1                  # marca los SID que no puedes servir (el cliente los ve no disponibles)
```

```ini
[newcamd]
port            = 50000@1801,1861,0B00   # un solo puerto da los tres CAID
key             = 0102030405060708091011121314
mgclient        = 1
```

Un usuario de CCcam recibiría esto (equivalente a una `C:`):

```
C: TU_IP_O_DOMINIO 12000 cliente_todo CAMBIA_ESTA_CLAVE_1 yes
```

Y uno de Newcamd, una `N:` con la misma `key`:

```
N: TU_IP_O_DOMINIO 50000 cliente_solo_1801 CAMBIA_ESTA_CLAVE_2 01 02 03 04 05 06 07 08 09 10 11 12 13 14
```

> El **puerto CCcam (12000) es solo para que entren tus clientes**; los lectores
> de proveedor tienen su propio host y puerto en `ncam.server`. No se mezclan.

---

## 6. Lectores: el ejemplo CCcam y el ejemplo Newcamd

Ambos están en [`examples/ncam.server`](../examples/ncam.server) listos para pegar.

### 6.1 Línea CCcam (proveedor) — "el ejemplo CCcam"

Si tu proveedor te da una línea así:

```
C: servidor-proveedor.com 12000 usuario_del_proveedor clave_del_proveedor yes
```

en NCam se escribe:

```ini
[reader]
label            = linea-cccam-3caids
enable           = 1
protocol         = cccam
device           = servidor-proveedor.com,12000
user             = usuario_del_proveedor
password         = clave_del_proveedor
cccmaxhops       = 10          # saltos permitidos al pedir por esta línea
cccversion       = 2.3.2
ccckeepalive     = 1           # mantiene la conexión viva
cccreconnect     = 30          # reintento si se cae
caid             = 1801,1861,0B00
group            = 1
lb_weight        = 200         # preferida frente a otras del mismo CAID
audisabled       = 1           # no pedir EMM/AU a una línea de proveedor
ecmnotfoundlimit = 0
dropbadcws       = 0           # no descartar CW "raros" (algunos proveedores)
```

| Línea | Qué hace |
| --- | --- |
| `device` | `host,puerto` del proveedor (hostname o IP). |
| `user` / `password` | Los que te dio el proveedor. |
| `caid` | Qué CAID se piden por aquí. Si te da los tres, déjalos. |
| `group` | Grupo del lector. Los usuarios con `group = 1` pueden usarlo. |
| `ccc...` | Solo para `protocol = cccam` (saltos, versión, keepalive, reconexión). |
| `audisabled = 1` | No molestar a la línea con actualizaciones/EMM: menos cortes. |
| `dropbadcws = 0` | Guardar el CW aunque venga marcado como "malo": es lo que hace que **la caché se llene**. |

### 6.2 Línea Newcamd (proveedor)

```ini
[reader]
label            = linea-newcamd-3caids
protocol         = newcamd
device           = servidor-proveedor.com,50000
key              = 0102030405060708091011121314
user             = usuario_del_proveedor
password         = clave_del_proveedor
caid             = 1801,1861,0B00
group            = 2
lb_weight        = 100
audisabled       = 1
inactivitytimeout = 0          # no cerrar la línea por inactividad
```

### 6.3 Tarjeta local (si la tienes)

```ini
#[reader]
#label           = tarjeta-local-1801
#protocol        = internal        # o pcsc / smartreader
#device          = 0
#caid            = 1801
#group           = 3
#au              = 1
#emmcache        = 1,3,2
#lb_weight       = 300             # gana sobre los proveedores
```

Con `preferlocalcards = 1` (o `2` si no compartes caché) los lectores locales se
preguntan **antes** que los proveedores: es la respuesta más rápida que existe.
La caché interna se consulta siempre, antes que cualquier lector.

### 6.4 Peer de cacheex

```ini
#[reader]
#label           = peer-cacheex
#protocol        = cccam
#device          = otro-servidor.com,12000
#user            = usuario_cacheex
#password        = clave_cacheex
#caid            = 1801,1861,0B00
#group           = 5
#cacheex         = 3               # 1 = solo pedir, 2 = solo enviar, 3 = ambas
#cacheex_maxhop  = 2
#cacheex_drop_csp = 1
#audisabled      = 1
```

---

## 7. Permisos por CAID: un usuario con los tres o solo con uno

**El permiso se pone en el `[account]` del usuario**, en la línea `caid`:

| Lo que pongas | Ese cliente recibe |
| --- | --- |
| `caid = 1801,1861,0B00` | Los **tres** CAID |
| `caid = 1801` | **Solo** 1801 |
| `caid = 0B00` | **Solo** 0B00 |
| *(sin línea `caid`)* | Todos los CAID de sus grupos (sin filtro) |

Si el cliente pide un CAID que no tiene permitido, NCam lo rechaza en el acto con
`invalid caid 0x1861` (código interno `E2_CAID`) **sin llegar a preguntar al
proveedor**: no se gasta un ECM ni se ensucia el ratio de la caché.

### 7.1 Los tres usuarios de ejemplo

```ini
# --- puede ver los TRES CAID ---
[account]
user        = cliente_todo
pwd         = CAMBIA_ESTA_CLAVE_1
group           = 1,2
caid            = 1801,1861,0B00
cccmaxhops      = 1            # 1 = solo tus tarjetas directas (sube para revendedores)
max_connections = 1            # conexiones simultáneas de esta cuenta
cccreshare      = 0
uniq            = 1
keepalive       = 1
au              = 0

# --- SOLO el CAID 1801 ---
[account]
user        = cliente_solo_1801
pwd         = CAMBIA_ESTA_CLAVE_2
group           = 1,2
caid            = 1801
cccmaxhops      = 1
uniq            = 1

# --- SOLO el CAID 0B00 ---
[account]
user        = cliente_solo_0b00
pwd         = CAMBIA_ESTA_CLAVE_3
group           = 1,2
caid            = 0B00
cccmaxhops      = 1
uniq            = 1
```

| Línea del `[account]` | Para qué |
| --- | --- |
| `caid` | El permiso, como se explicó arriba. |
| `group` | Qué lectores puede usar: `1` = línea CCcam, `2` = Newcamd, `1,2` = ambas. |
| `cccmaxhops` | Saltos de tarjeta que ve el cliente. `1` = solo tus tarjetas directas; `-1` = ninguna (bloqueo); súbelo (`3`, `6`, `10`) si el proveedor anuncia las tarjetas con más saltos o si tu cliente revende. |
| `cccreshare` | Niveles que el cliente puede reenviar de tus tarjetas: `0` = no reenvía, `1`+ = revendedor. |
| `max_connections` | Conexiones **simultáneas** de esa cuenta (por defecto `1`). Con `1`, un segundo equipo que use la misma línea es rechazado/aislado. |
| `uniq` | Cómo se cuentan los duplicados: `1` = una conexión en total; `2` = permite varios equipos desde la **misma IP** (casa con NAT) y rechaza los de otras IP; `3`/`4` variantes de lo anterior. |
| `keepalive` | Mantiene la conexión viva. |
| `au` | `0` en clientes normales: no compartir EMM con ellos. |
| `allowedprotocols` | `cccam,newcamd` para que pueda entrar por los dos puertos. |

### 7.2 Las otras dos formas de dar permisos

- **Por grupo de lectores** — si quieres que un cliente use solo *una* de las
  líneas: el lector tiene `group = 1` y el usuario `group = 1` (los ejemplos ya
  separan la línea CCcam en el grupo 1 y la Newcamd en el 2).
- **Por servicios** — si el proveedor te da CAID mezclados y quieres afinar por
  canales, define `[service]` en `ncam.services` con `caid =` y usa
  `services =` en el usuario (o en el lector). Ejemplo:

  ```ini
  [service]
  name    = paquete_1801
  caid    = 1801
  srvid   = 0001,0002,0003
  ```

  y en el usuario `services = paquete_1801`. Es más fino que el CAID, pero para
  "los tres o solo uno" con `caid` vas sobrado.

### 7.3 Y desde NCPanel, sin tocar ficheros

En **NCPanel → Líneas**, cada línea tiene el campo **CAIDs permitidos**:

- **Vacío** = todos los CAID del grupo (sin restricción).
- `1801` = solo ese; `1801,1861,0B00` = los tres. Hay botones rápidos para
  1801 / 1861 / 0B00 y para *Todos*.

También hay un campo **Saltos CCcam** (`cccmaxhops`, por defecto `1`): es cuántos
saltos de tarjeta ve ese cliente. `1` = solo tus tarjetas directas; `-1` = no ve
ninguna tarjeta; súbelo (3, 6, 10) para un revendedor.

El campo se guarda en la línea y **se escribe tal cual en la línea `caid =`** del
bloque `[account]` que genera *Caché y peers → Exportar configuración* /
*Descargar ncam.user*. Es decir: creas el cliente en el panel, pones su CAID,
pegas el `ncam.user` en el servidor y ya está.

> Si creas al cliente a mano en `ncam.user`, acuérdate de poner su `caid`; si lo
> dejas sin esa línea, el cliente tendrá acceso a **todos** los CAID de sus
> grupos.

---

## 8. Puesta en marcha en 5 minutos

```bash
# 1. copia los tres ficheros de ejemplo
sudo cp /usr/share/doc/ncam-ng/examples/optimo/ncam.conf   /etc/ncam/ncam.conf
sudo cp /usr/share/doc/ncam-ng/examples/optimo/ncam.server /etc/ncam/ncam.server
sudo cp /usr/share/doc/ncam-ng/examples/optimo/ncam.user   /etc/ncam/ncam.user

# 2. cambia lo tuyo: proveedor, nodeid, contraseñas del WebIf y de los clientes
sudo ncam-ng-ctl config ncam      # /etc/ncam/ncam.conf   (nodeid, httppwd...)
sudo nano /etc/ncam/ncam.server   # tus líneas reales
sudo nano /etc/ncam/ncam.user     # tus clientes y sus CAID

# 3. aplica
sudo restart-ncam

# 4. comprueba
sudo ncam-ng-status                            # servicios y puertos
curl -s -u admin:TU_CLAVE http://127.0.0.1:8181/ncamapi.json?part=status
```

Con NCPanel: *Ajustes* → **Host público** y puertos → *Líneas* con sus CAID →
*Caché y peers* → *Exportar configuración* para pegar los bloques en el servidor.

---

## 9. Comprobaciones y diagnóstico

| Qué quieres ver | Dónde |
| --- | --- |
| Lectores conectados y tarjetas | WebIf → *Readers* (`/readers.html`) |
| Clientes conectados y sus ECM | WebIf → *Users* (`/users.html`) |
| **Caché y ratio de aciertos** | WebIf → *Cache Engine* (`/cacheengine.html`) y NCPanel → *Caché y peers* |
| Peticiones en vivo | WebIf → *Live Log* |
| Registro del daemon | `ncam-ng-ctl logs ncam -f` |

Mensajes típicos del registro y qué significan:

| Mensaje | Significado |
| --- | --- |
| `invalid caid 0x1861` | El usuario pidió un CAID que **no tiene permitido** (`E2_CAID`): revisa su `caid =`. |
| `not found` | Ningún lector dio CW: proveedor caído, CW con CRC raro (`disablecrccws = 1`) o ECM sin permiso. |
| `timeout` | El lector no contestó en `fallbacktimeout`: súbelo o revisa la línea. |
| `found (Xms) by <lector>` | Todo bien: además te dice **qué lector** lo sirvió y en cuántos ms. |
| `cache hit` / `cacheex hit` | Se respondió desde la caché: es lo que quieres ver mucho. |

Consultas útiles a mano:

```bash
# resumen del motor de caché
curl -s -u admin:TU_CLAVE "http://127.0.0.1:8181/ncamapi.json?part=cachestats"
# usuarios y sus ECM
curl -s -u admin:TU_CLAVE "http://127.0.0.1:8181/ncamapi.json?part=userstats"
```

---

## 10. Problemas frecuentes

| Síntoma | Causa habitual | Solución |
| --- | --- | --- |
| Un cliente "no ve nada" pero otro sí | Su `caid` no incluye el CAID de esos canales. | Añade el CAID a su `caid =` (o quítala para darle todos). Verás `invalid caid` en el log. |
| `not found` en muchos canales | CW con CRC alterado por el proveedor. | `disablecrccws = 1` o `disablecrccws_only_for` con tus tres CAID. |
| Va lento al cambiar de canal | `fallbacktimeout` alto o un lector colgado en primer lugar. | `fallbacktimeout = 2000`, `lb_mode = 1`, y revisa *Readers* para ver si alguno acumula timeouts. |
| El ratio de caché es bajo | `max_time` muy bajo, `max_entries` pequeño o `dropbadcws = 1`. | `max_time = 15`, `max_entries = 0`, `dropbadcws = 0`; comprueba en el log que salgan `cache hit`. |
| Se pierde la caché al reiniciar | Es normal: la caché vive en memoria. | No hay nada que guardar; solo afecta a los primeros segundos tras reiniciar. |
| Dos equipos con la misma línea | `uniq = 1` cuenta los duplicados de cualquier IP y `max_connections = 1` solo admite una conexión. | Pon `uniq = 2` para permitir varios equipos desde la misma IP/NAT y sube `max_connections` (o abre otra línea). |
| El cliente CCcam no ve tarjetas | `cccmaxhops` bajo respecto a los saltos con los que llegan las tarjetas de tu proveedor. | Súbelo en ese `[account]` (`1` → `3` → `6` → `10`). |
| El ratio de caché no sube | El proveedor manda CW distintos con el mismo ECM, o `dropbadcws = 1` en el lector descarta respuestas. | Deja `cacheex_dropdiffs = 0` y `dropbadcws = 0`; revisa en el log que aparezcan `cache hit`. |
| El puerto 12000 no escucha | Falta la sección `[cccam]` o el puerto está ocupado. | `sudo ncam-ng-status` y revisa el log; cambia el puerto o libera el que usa. |

---

## 11. Valores de referencia rápida

```ini
# ncam.conf
[global]
nice                = -10
fallbacktimeout     = 2000
preferlocalcards    = 1        # 2 solo si NO compartes caché
dropdups            = 1
lb_mode             = 1
lb_nbest_readers    = 2
disablecrccws       = 1

[cache]
delay               = 0        # sin espera al servir desde caché (lo más rápido)
max_time            = 15       # validez de cada entrada
max_entries         = 0        # 0 = guardar todo hasta que caduque
max_hit_time        = 15       # memoria de aciertos de cacheex (0 = off)
cacheexenablestats  = 0        # 1 solo si compartes caché (contadores por cliente)
```

```ini
# ncam.server  (lector)
caid                = 1801,1861,0B00
group               = 1
audisabled          = 1
dropbadcws          = 0

# ncam.user  (permiso)
caid                = 1801,1861,0B00   # o solo 1801 / solo 0B00
group               = 1,2
```

---

*Ver también: [`cache-engine.md`](cache-engine.md) (cómo funciona el motor de
caché v2), [`ajustes.md`](ajustes.md) (NCPanel) e [`../INSTALL.md`](../INSTALL.md)
(instalación y actualizaciones).*
