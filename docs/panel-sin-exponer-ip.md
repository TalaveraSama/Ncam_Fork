# Publicar NCPanel sin exponer tu IP pública (Cloudflare Tunnel)

Guía para que tú y tus usuarios entréis al panel por un dominio (con HTTPS) **sin
abrir puertos** en el servidor y **sin que la IP del VPS aparezca** en el DNS ni en
los escaneos. Usa **Cloudflare Tunnel** (`cloudflared`), que es gratis y no necesita
plan de pago.

> **Resumen en una frase:** `cloudflared` abre una conexión **de salida** desde tu
> VPS hacia Cloudflare; Cloudflare publica el dominio y lleva el tráfico hasta tu
> `127.0.0.1:8080`. Nadie se conecta a tu IP directamente, así que puedes cerrar el
> puerto 8080 en el cortafuegos. Si además pones **Cloudflare Access** delante,
> tendrás una barrera de login (con MFA) antes del propio login del panel.

---

## 1. Qué se puede ocultar y qué no

| Servicio | ¿Se puede ocultar la IP? | Cómo |
| --- | --- | --- |
| **NCPanel** (HTTP, 8080) | **Sí, completamente** | Cloudflare Tunnel (+ Access). Sin abrir puertos. |
| **WebIf del daemon** (HTTP, 8181) | Sí, pero **ojo**: detrás del túnel el daemon ya no distingue clientes (ver §6) | Túnel + Access, o mejor **no publicarlo** y entrar por SSH/VPN. |
| **SSH** (22) | Sí | Túnel de Cloudflare para SSH o Tailscale. |
| **Líneas de tus clientes** (CCcam 12000, Newcamd 50000, camd35 33333) | **No con el plan gratis** | Cloudflare solo pone el proxy a HTTP/HTTPS (80, 443, 8080, 8443, 2052/2053, 2082/2083, 2086/2087, 2095/2096, 8880). Para TCP/UDP en cualquier puerto hace falta **Spectrum** (plan Enterprise, de pago) o un **relé** (ver §7). |

Lo que **no** oculta la IP de ninguna manera:

* un registro DNS **solo DNS** (nube gris) apuntando a tu IP;
* dar a los clientes la **IP directa** o un hostname que resuelva a ella;
* cambiar el puerto del panel o del WebIf;
* dejar cualquier servicio escuchando en `0.0.0.0` con el puerto abierto: un escaneo
  de puertos lo encuentra aunque no lo anuncies.

---

## 2. Antes de empezar

1. Un **dominio** (o un subdominio de uno) con los **nameservers en Cloudflare**
   (plan Free basta). Compruébalo:

   ```bash
   dig NS tu-dominio.com +short     # deben salir nombres *.ns.cloudflare.com
   ```

2. El panel funcionando en el VPS: `sudo ncam-ng-status` → *panel: escuchando en 8080*.
3. Cuenta de Cloudflare (la misma del dominio) para los pasos de la web.

---

## 3. Instalar `cloudflared` en el VPS (Ubuntu/Debian)

```bash
# clave y repositorio oficiales
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list

sudo apt update && sudo apt install -y cloudflared
cloudflared --version
```

Alternativa en una línea (script oficial): `curl -L https://pkg.cloudflare.com/install.sh | sudo bash`

---

## 4. Crear el túnel y publicar el panel

Hay dos formas; las dos son gratis. La **A** se gestiona desde la web de Cloudflare
(la que recomienda Cloudflare desde 2026) y la **B** desde el propio servidor con un
fichero de configuración.

### A) Túnel gestionado desde el panel de Cloudflare (token)

1. Entra en <https://one.dash.cloudflare.com> → **Networks → Tunnels → Create a tunnel
   → Cloudflared**. Ponle un nombre (`ncpanel`) y **copia el token** que muestra.
2. En el VPS, instala el servicio con ese token:

   ```bash
   sudo cloudflared service install eyJhIjoi...TOKEN...
   sudo systemctl status cloudflared
   ```

3. Vuelve a la web del túnel → pestaña **Public Hostname** → **Add a public hostname**:
   * *Subdomain*: `panel` · *Domain*: `tu-dominio.com`
   * *Service*: **HTTP** → `127.0.0.1:8080`

   Listo: `https://panel.tu-dominio.com` ya llega al panel.

### B) Túnel gestionado desde el servidor (config.yml)

```bash
# 1) autorizar (en un VPS sin navegador imprime una URL: ábrela en tu PC)
cloudflared tunnel login                 # guarda ~/.cloudflared/cert.pem

# 2) crear el túnel y apuntar su UUID
cloudflared tunnel create ncpanel
cloudflared tunnel list

# 3) crear el CNAME que apunta al túnel
cloudflared tunnel route dns ncpanel panel.tu-dominio.com
```

```bash
# 4) configuración del servicio
sudo mkdir -p /etc/cloudflared
sudo mv ~/.cloudflared/<UUID>.json /etc/cloudflared/
sudo nano /etc/cloudflared/config.yml
```

```yaml
tunnel: <UUID>
credentials-file: /etc/cloudflared/<UUID>.json
ingress:
  - hostname: panel.tu-dominio.com
    service: http://127.0.0.1:8080
  - service: http_status:404        # resto: 404 (obligatorio)
```

```bash
# 5) validar y arrancar como servicio (sobrevive al cierre de la terminal)
cloudflared tunnel ingress validate
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo journalctl -u cloudflared -f     # busca "Registered tunnel connection"
```

---

## 5. Cerrar el panel a calle: ajustes del panel y cortafuegos

```bash
# el panel solo hace falta en localhost: es cloudflared quien le habla
sudo nano /opt/ncam-ng-panel/.env        # o: sudo ncam-ng-ctl config panel
```

```ini
# solo escucha en la propia máquina (cloudflared está en el mismo servidor)
NCAM_PANEL_HOST=127.0.0.1
# la conexión llega desde cloudflared (127.0.0.1): así el panel usa la IP REAL del
# cliente (CF-Connecting-IP) en la auditoría y para el bloqueo por intentos fallidos
NCAM_PANEL_TRUSTED_PROXIES=127.0.0.1,::1
```

```bash
sudo restart-ncam-panel

# cortafuegos: fuera los puertos que ya no hacen falta
sudo ufw status numbered
sudo ufw deny 8080/tcp        # panel (opcional si ya escucha en 127.0.0.1)
sudo ufw deny 8181/tcp        # WebIf del daemon, si no lo publicas
sudo ufw reload
```

> **Cortafuegos del proveedor**: si tu VPS tiene *security groups* o firewall en el
> panel del proveedor, cierra ahí también 8080/8181. Y **no** publiques esos puertos
> en el router si el servidor está en tu casa.

En Cloudflare, activa **SSL/TLS → Edge Certificates → Always Use HTTPS**.

---

## 6. El WebIf del daemon: una advertencia importante

`httpallowed` (ver §12 de [`configuracion-optima.md`](configuracion-optima.md)) filtra
por la **IP del socket**, y el daemon **no lee** `CF-Connecting-IP` ni
`X-Forwarded-For` (la comprobación se hace antes de leer las cabeceras de la
petición). Consecuencia práctica: **si publicas el WebIf por el túnel, todas las
peticiones llegan desde `127.0.0.1`** y `httpallowed` deja de distinguir clientes (la
lista se vuelve un «sí» o un «no» global).

Recetas sensatas, de más segura a más cómoda:

1. **No lo publiques** (recomendado). Sigue con `httpallowed = 127.0.0.1` y entra por
   un túnel SSH desde tu PC:

   ```bash
   ssh -N -L 8181:127.0.0.1:8181 usuario@192.6.154.19
   # y en tu navegador: http://127.0.0.1:8181
   ```

2. Publícalo por el túnel **con Cloudflare Access delante** (§8) y deja
   `httpallowed = 127.0.0.1` como última barrera (solo pasa el túnel).
3. Si necesitas acceso desde varios sitios sin complicarte, una **VPN**
   (Tailscale/WireGuard) es más limpia que exponerlo.

> El panel **sí** entiende la IP real del cliente desde la versión **2.4.3**
> (`NCAM_PANEL_TRUSTED_PROXIES`), así que ahí la auditoría y el bloqueo por intentos
> fallidos funcionan bien detrás del túnel.

---

## 7. Las líneas de tus clientes (CCcam/Newcamd) sí revelan la IP

El tráfico de las líneas es **TCP propio de CAM**, no HTTP, así que Cloudflare (plan
gratis) no lo puede poner detrás de su proxy: si apuntas un hostname proxied a tu
servidor y el cliente conecta al puerto 12000, la conexión falla; y si el registro
es *solo DNS*, el cliente ve tu IP. Opciones reales:

| Opción | Cómo | Ventajas | Inconvenientes |
| --- | --- | --- | --- |
| **Relé TCP** en otro VPS barato | El relé reenvía los puertos al tuyo; tus clientes usan el hostname del relé | Tu IP queda oculta, sin tocar a los clientes | Otro servidor que pagar/mantener, +latencia, el relé ve el tráfico |
| **Tailscale / WireGuard** | Los clientes (o sus equipos) instalan el cliente VPN y conectan a la IP `100.x` | Todo cifrado y oculto, sin abrir puertos | Hay que instalar el cliente en cada equipo; no todos los decodificadores lo soportan |
| **Cloudflare Spectrum** | Proxy TCP de Cloudflare en cualquier puerto | Sin relé propio | Solo plan **Enterprise** (de pago) |

Ejemplo de relé con `nginx` (en el VPS relé, `/etc/nginx/nginx.conf`):

```nginx
stream {
    server {
        listen 12000;                          # CCcam
        proxy_pass 192.6.154.19:12000;         # tu servidor real
    }
    server {
        listen 50000;                          # Newcamd
        proxy_pass 192.6.154.19:50000;
    }
}
```

Y sin nginx, para probar: `socat TCP-LISTEN:12000,fork,reuseaddr TCP:192.6.154.19:12000`

> Con el relé, en `[global]`/lectores del daemon puede ser útil `serverip`/`bind`
> para que los logs y las respuestas muestren el equipo correcto, y en el relé
> conviene limitar por `allow`/`deny` (nginx) o `ufw` para que no lo use cualquiera.

Si no quieres relé: **asume que los clientes ven la IP del servidor** y protégelo
(contraseñas largas, `max_connections`, `uniq`, `dropdups`, `failban`).

---

## 8. Poner Cloudflare Access delante (recomendado, gratis hasta 50 usuarios)

Access añade un login (email con código de un solo uso, Google, o MFA) **antes** de
llegar al panel; el login propio del panel sigue existiendo después.

1. <https://one.dash.cloudflare.com> → **Access → Applications → Add an application →
   Self-hosted**.
2. *Application name*: `NCPanel` · *Session duration*: 24 h.
3. *Application domain*: `panel.tu-dominio.com` (deja la ruta vacía).
4. **Policies → Add a policy**: nombre `admins`, acción **Allow**, incluir
   **Emails** con tu correo (y los de tus administradores) o **Emails ending in**
   `@tudominio.com`. Con eso, quien no esté en la lista ni llega a ver el login del
   panel.
5. Guarda y prueba en una ventana privada: primero te pedirá el código por email.

Notas:

* Es gratis hasta **50 usuarios**; por encima, Cloudflare cobra por usuario.
* Access protege **HTTP/HTTPS**; no sirve para los puertos de las líneas (§7).
* Para integraciones por API puedes usar un **Service Token** en lugar de correo.
* Opcional (plan Free tiene reglas limitadas): en **Security → WAF → Rate limiting**,
  limita `https://panel.tu-dominio.com/api/v1/auth/login` a, p. ej., 10 peticiones
  por minuto y por IP. El panel ya bloquea 8 intentos fallidos cada 5 minutos
  (`NCAM_PANEL_MAX_LOGIN_ATTEMPTS`, `NCAM_PANEL_LOGIN_LOCKOUT`).

---

## 9. Comprobar que tu IP está oculta

Desde tu PC (o el móvil con datos, **no** desde el VPS):

```bash
# 1) el DNS debe devolver IPs de Cloudflare, no la tuya
dig +short panel.tu-dominio.com
#   -> 104.x.x.x / 172.67.x.x / 2606:4700:...    (nunca 192.6.154.19)

# 2) el puerto del panel debe estar cerrado desde fuera
nc -vz -w 5 192.6.154.19 8080 ; echo "codigo: $?"     # timeout / refused = bien
nc -vz -w 5 192.6.154.19 8181 ; echo "codigo: $?"     # idem si no publicas el WebIf

# 3) y el panel debe contestar por el dominio
curl -sI https://panel.tu-dominio.com | head -3       # 302 (Access) o 200/401 del panel
```

En el VPS:

```bash
sudo ss -ltnp | grep -E '8080|8181'      # 127.0.0.1:8080 y 127.0.0.1:8181 = ideal
systemctl is-active cloudflared          # active
sudo journalctl -u cloudflared -n 30     # conexiones registradas sin errores
```

Y en el panel: **Auditoría** debe mostrar la IP real de cada visita (no
`127.0.0.1`). Si sale `127.0.0.1`, revisa `NCAM_PANEL_TRUSTED_PROXIES=127.0.0.1,::1`
en `/opt/ncam-ng-panel/.env` y reinicia el panel.

---

## 10. Problemas frecuentes

| Síntoma | Causa | Solución |
| --- | --- | --- |
| Cloudflare muestra **1033 / 502 Bad Gateway** | `cloudflared` caído o apunta al puerto equivocado | `systemctl status cloudflared`; en el túnel, service `http://127.0.0.1:8080` |
| **502** y el panel responde en `curl http://127.0.0.1:8080` | El panel escucha en `127.0.0.1` pero el túnel apunta a `localhost` resuelto a IPv6 (`::1`) | Usa `127.0.0.1` en el service del túnel (no `localhost`) |
| Redirección infinita (**too many redirects**) | Suele pasar cuando el origen es un registro *solo DNS* y el modo SSL de Cloudflare es *Flexible* | Con túnel el modo SSL no interviene (cloudflared habla `http://127.0.0.1:8080`); activa *Always Use HTTPS* y borra galletas del dominio |
| **Access** no pide login | La aplicación de Access no cubre ese dominio, o el hostname no está proxied | Los hostnames de túnel van proxied; revisa dominio y política en Access |
| **Access** entra en bucle de login | Galletas de sesión antiguas del dominio | Borra las galletas de `panel.tu-dominio.com` (o prueba en ventana privada) |
| En la auditoría todo es `127.0.0.1` | El panel no sabe que viene de un proxy | `NCAM_PANEL_TRUSTED_PROXIES=127.0.0.1,::1` y `restart-ncam-panel` |
| `cloudflared tunnel login` no abre nada | VPS sin navegador (normal) | Copia la URL que imprime y ábrela en tu PC; autoriza el dominio |
| `dig` devuelve tu IP | Registro *solo DNS* (nube gris) o dominio fuera de Cloudflare | Crea el hostname en el túnel (paso 4) y comprueba que la nube esté naranja |
| Los clientes CCcam no conectan por el dominio | Puerto no proxiable (12000) | Usa relé o VPN (§7); no lo publiques como proxied |

---

## 11. Tu caso concreto (VPS `192.6.154.19`, VPN `191.103.121.243`)

```bash
# 1) túnel al panel
cloudflared tunnel create ncpanel && cloudflared tunnel route dns ncpanel panel.tu-dominio.com
#    (config.yml del §4B o el hostname del §4A -> http://127.0.0.1:8080)

# 2) el panel, solo en local y sabiendo que viene de un proxy
sudo -e /opt/ncam-ng-panel/.env      # NCAM_PANEL_HOST=127.0.0.1
                                     # NCAM_PANEL_TRUSTED_PROXIES=127.0.0.1,::1
sudo restart-ncam-panel

# 3) cerrar puertos (el WebIf se queda solo para ti, por SSH)
sudo ufw deny 8080/tcp && sudo ufw deny 8181/tcp && sudo ufw reload

# 4) Access con tu correo (y el de tus administradores) y a navegar:
#    https://panel.tu-dominio.com
```

Desde ese momento tus usuarios entran por el dominio, con HTTPS y (si activas
Access) con doble login, y **en ningún `dig`, `nmap` ni respuesta HTTP aparece
`192.6.154.19`**. Lo único que sigue mostrando la IP del servidor (o la del relé) son
las líneas de CCcam/Newcamd, por lo explicado en §7.

---

*Ver también: [`configuracion-optima.md`](configuracion-optima.md) (§12, `httpallowed`
y el WebIf), [`ajustes.md`](ajustes.md) (Ajustes del panel),
[`administradores.md`](administradores.md) (varios administradores) e
[`../INSTALL.md`](../INSTALL.md).*

*Documentación de Cloudflare usada:*
[*Network ports*](https://developers.cloudflare.com/fundamentals/reference/network-ports/)
*(puertos que admite el proxy), [Zero Trust (Access) gratis hasta 50
usuarios](https://www.cloudflare.com/plans/zero-trust-services/) y [Cloudflare
Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).*
