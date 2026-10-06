# Varios administradores en NCPanel

NCPanel puede tener **tantos administradores como quieras**. Todos son iguales:
control total del panel (líneas, cuentas, créditos, ajustes y auditoría). Este
documento explica cómo crearlos, qué puede cada rol y qué límites protegen al
panel de quedarse sin nadie que lo administre.

> Versión mínima: **2.4.1** (`ncam-ng-ctl admin`). En paquetes anteriores solo se
> creaba un administrador durante la instalación.

---

## 1. Los tres roles

| Rol | Qué puede | Qué **no** puede |
| --- | --- | --- |
| **Administrador** (`super_admin`) | Todo: crear/editar **otros administradores**, revendedores y usuarios; emitir y ajustar créditos; ajustes globales y del motor de caché; ver toda la auditoría; purgar histórico. | Nada dentro del panel. No puede cambiarse el rol a sí mismo ni borrarse, y no puede dejar el panel sin administrador activo. |
| **Revendedor** (`reseller`) | Sus líneas y sus usuarios finales, con su saldo de créditos; transferir créditos a sus usuarios; sus peers de caché; API key. | Ver o tocar datos de otros, crear administradores, ascender a nadie, cambiar roles, tocar los Ajustes. |
| **Usuario final** (`user`) | Solo lectura de sus propias líneas y su saldo. | Todo lo demás. |

Si solo quieres que alguien **gestione sus propias líneas y clientes**, lo que
buscas es un **revendedor**, no otro administrador.

---

## 2. Crear otro administrador desde la web

1. Entra en NCPanel con tu cuenta de administrador (`http://TU_IP:8080`).
2. Menú **Revendedores y usuarios** → botón **+ Nueva cuenta**.
3. Rellena **Usuario** y **Contraseña** (mínimo 8 caracteres).
4. En **Rol**, elige **Administrador (control total del panel)**.
5. **Crear cuenta**.

En la tabla verás la etiqueta *Super Admin* en esa fila. Cada administrador entra
con su propio usuario y contraseña y puede, a su vez, crear más administradores.

En la ficha de cualquier cuenta (**Editar**) puedes cambiarle el rol más adelante.
Tu propio rol sale bloqueado a propósito: nadie puede cambiarse el rol a sí
mismo. Cambiar de rol **no borra sus líneas**.

---

## 3. Crear otro administrador desde la consola

Con el paquete `.deb` instalado (`ncam-ng-ctl` ya está en el sistema):

```bash
sudo ncam-ng-ctl admin add maria          # administrador (super admin)
sudo ncam-ng-ctl admin add maria Clave.Maria1        # con la contraseña que tú elijas
sudo ncam-ng-ctl admin add maria Clave.Maria1 maria@ejemplo.com
```

Si no pasas contraseña, se genera una **aleatoria y fuerte** que se muestra **una
sola vez**:

```
==============================================================
  CUENTA CREADA
  usuario:    maria
  contraseña: 15Kg8faM*mGYy3#0
  Guárdela: no se vuelve a mostrar.
==============================================================
Entra en el panel con este usuario: tiene control total (super admin).
```

El rol por defecto es administrador; también puedes crear los otros dos:

```bash
sudo ncam-ng-ctl admin add luis reseller              # revendedor
sudo ncam-ng-ctl admin add pepe user Clave.Pepe1      # usuario final
```

Y gestionar lo que ya existe:

```bash
sudo ncam-ng-ctl admin                    # lista: id, usuario, rol, estado, email
sudo ncam-ng-ctl admin role luis reseller # cambia el rol de una cuenta
sudo ncam-ng-ctl admin del viejo          # elimina una cuenta
sudo ncam-ng-ctl admin passwd maria       # nueva contraseña (se muestra una vez)
```

Nada de esto reinicia servicios: las cuentas se leen de la base de datos en cada
petición, así que el cambio está activo al instante.

### Sin el paquete `.deb` (desde el código)

Es el mismo programa que usa el comando anterior:

```bash
cd Ncam_Fork/panel
PYTHONPATH=backend python3 -m app.seed --list
PYTHONPATH=backend python3 -m app.seed --create --username maria --role super_admin
PYTHONPATH=backend python3 -m app.seed --create --username luis --role reseller --email luis@ejemplo.com
PYTHONPATH=backend python3 -m app.seed --set-role maria reseller
PYTHONPATH=backend python3 -m app.seed --delete maria
```

En una instalación con paquetes, las rutas del servidor son:

```bash
sudo -u ncam-panel PYTHONPATH=/opt/ncam-ng-panel/backend \
  NCAM_PANEL_DB=/var/lib/ncam-ng-panel/panel.db \
  /opt/ncam-ng-panel/.venv/bin/python -m app.seed --list
```

> `panel.db` es una base de datos **SQLite**: se consulta con
> `sqlite3 /var/lib/ncam-ng-panel/panel.db 'select username, role, status from users;'`
> y **nunca** se abre con un editor de textos (nano, vi), porque se corrompe.

---

## 4. Reglas que protegen el panel

| Regla | Qué pasa si la intentas saltar |
| --- | --- |
| Solo un administrador puede crear o ascender a otro administrador | Un revendedor recibe `403 Solo un super administrador puede crear otro super administrador`. |
| Nadie puede cambiarse el rol a sí mismo | La API responde `400 No puede cambiarse el rol a sí mismo`; en la web, tu propio rol sale bloqueado. |
| Nadie puede suspenderse a sí mismo | `400 No puede suspenderse a sí mismo`. |
| **El panel nunca se queda sin administrador activo** | Degradar, suspender o eliminar al último super admin se rechaza (`400`); la web esconde el botón *Borrar* en esa fila y el comando avisa: *«No se puede degradar el único super administrador activo: cree antes otro»*. |
| Todo cambio de rol queda registrado | Menú **Auditoría**: `account.update` con `{"role": "reseller -> super_admin"}`. |

Se cuentan solo los administradores **activos**: uno suspendido no puede iniciar
sesión (`403 Cuenta suspendida`), así que dejarlo como único administrador
bloquearía el panel.

---

## 5. Preguntas frecuentes

**¿Cuántos administradores puedo tener?** Los que quieras. Todos con el mismo
control total; no hay permisos parciales dentro del rol de administrador.

**¿Puedo dar a alguien permisos «de solo líneas»?** Sí, pero con el rol
**revendedor** (gestiona las suyas) o **usuario** (solo lectura de las suyas).

**Perdí la contraseña de un administrador.** Cámbiala desde otro administrador
(*Revendedores y usuarios* → **Editar** → *Nueva contraseña*) o desde la consola:

```bash
sudo ncam-ng-ctl admin passwd maria      # o: sudo ncam-ng-ctl passwd maria
```

**¿Cómo suspendo temporalmente a un administrador?** *Editar* → **Estado →
suspendida**. Mientras haya otro administrador activo, es un cambio permitido; si
es el único, la API lo rechaza para no dejarte fuera del panel.

**¿Los administradores ven las líneas de los revendedores?** Sí: el super admin
ve todas las cuentas y líneas (los revendedores solo ven las suyas y las de sus
usuarios).

**¿Los administradores se facturan ECM como los demás?** No: las cuentas
administradoras no se facturan a sí mismas.

**Cambié de rol a un revendedor que tenía usuarios, ¿los pierdo?** No se borra
nada; los usuarios que dependían de él quedan sin padre (`parent_id` vacío) y
siguen existiendo. Revisa *Revendedores y usuarios* después del cambio.

---

## 6. Resumen de una línea

```bash
sudo ncam-ng-ctl admin add maria    # y ya tienes otro administrador con control total
```

---

*Ver también: [`../INSTALL.md`](../INSTALL.md) (§F, comandos de consola),
[`../README.md`](../README.md) (roles del panel) y
[`ajustes.md`](ajustes.md) (pantalla de Ajustes).*
