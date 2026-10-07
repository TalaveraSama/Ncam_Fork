/* NCPanel :: frontend SPA (JavaScript puro, sin dependencias) */
"use strict";

const API = "/api/v1";
const state = {
  user: null,
  meta: null,
  view: "dashboard",
  tokens: {
    access: localStorage.getItem("ng_access") || "",
    refresh: localStorage.getItem("ng_refresh") || "",
  },
  settings: {},
};

/* ------------------------------------------------------------ utilidades */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtNumber(value) {
  const num = Number(value ?? 0);
  return Number.isFinite(num) ? num.toLocaleString("es-ES") : "0";
}

function fmtBytes(bytes) {
  const num = Number(bytes ?? 0);
  if (!num) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB"];
  let idx = 0;
  let value = num;
  while (value >= 1024 && idx < units.length - 1) { value /= 1024; idx += 1; }
  return `${value.toFixed(value < 10 && idx > 0 ? 1 : 0)} ${units[idx]}`;
}

function fmtDate(iso, withTime = false) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return esc(iso);
  const opts = withTime
    ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "2-digit", year: "numeric" };
  return date.toLocaleDateString("es-ES", opts);
}

function daysLeft(iso) {
  if (!iso) return null;
  const diff = new Date(iso).getTime() - Date.now();
  return Math.ceil(diff / 86400000);
}

function statusBadge(status) {
  const map = {
    active: ["ok", "activa"], expired: ["bad", "caducada"], suspended: ["warn", "suspendida"],
    expiring: ["warn", "por caducar"],
  };
  const [cls, label] = map[status] || ["", status || "—"];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

function roleBadge(role) {
  const labels = { super_admin: "Super Admin", reseller: "Reseller", user: "Usuario" };
  return `<span class="badge role">${esc(labels[role] || role)}</span>`;
}

function toast(message, kind = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${kind === "ok" ? "" : kind}`;
  el.innerHTML = esc(message);
  $("#toast-root").appendChild(el);
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 4000);
}

function confirmDialog(title, message, confirmLabel = "Confirmar") {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    root.innerHTML = `
      <div class="modal-backdrop">
        <div class="modal" role="dialog" aria-modal="true">
          <h3>${esc(title)}</h3>
          <p class="muted">${esc(message)}</p>
          <div class="actions">
            <button class="btn ghost" data-close>Cancelar</button>
            <button class="btn danger" data-ok>${esc(confirmLabel)}</button>
          </div>
        </div>
      </div>`;
    const close = (result) => { root.innerHTML = ""; resolve(result); };
    $("[data-close]", root).onclick = () => close(false);
    $("[data-ok]", root).onclick = () => close(true);
  });
}

function modal(title, bodyHTML, { onSubmit, submitLabel = "Guardar", width } = {}) {
  const root = $("#modal-root");
  root.innerHTML = `
    <div class="modal-backdrop">
      <form class="modal" ${width ? `style="width:min(${width}px,100%)"` : ""}>
        <h3>${esc(title)}</h3>
        ${bodyHTML}
        <div class="actions">
          <button type="button" class="btn ghost" data-close>Cerrar</button>
          ${onSubmit ? `<button type="submit" class="btn primary">${esc(submitLabel)}</button>` : ""}
        </div>
      </form>
    </div>`;
  const form = $("form.modal", root);
  $("[data-close]", root).onclick = () => { root.innerHTML = ""; };
  if (onSubmit) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      const button = $("button[type=submit]", form);
      button.disabled = true;
      try {
        const keepOpen = await onSubmit(data, form);
        if (!keepOpen) root.innerHTML = "";
      } catch (error) {
        toast(error.message, "error");
      } finally {
        button.disabled = false;
      }
    };
  }
  return form;
}

function copyButton(text) {
  return `<button type="button" class="btn small" data-copy="${esc(text)}">Copiar</button>`;
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-copy]");
  if (!target) return;
  navigator.clipboard?.writeText(target.dataset.copy).then(
    () => toast("Copiado al portapapeles"),
    () => toast("No se pudo copiar", "error"),
  );
});

/* ----------------------------------------------------------------- API */
async function rawRequest(path, { method = "GET", body, useAuth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (useAuth && state.tokens.access) headers.Authorization = `Bearer ${state.tokens.access}`;
  const response = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  const text = await response.text();
  let payload = text;
  try { payload = text ? JSON.parse(text) : null; } catch (_) { /* respuesta no JSON */ }
  return { ok: response.ok, status: response.status, payload };
}

async function refreshSession() {
  if (!state.tokens.refresh) return false;
  const result = await rawRequest("/auth/refresh", {
    method: "POST",
    body: { refresh_token: state.tokens.refresh },
    useAuth: false,
  });
  if (result?.ok && result.payload?.access_token) {
    setTokens(result.payload.access_token, result.payload.refresh_token);
    return true;
  }
  return false;
}

async function api(path, options = {}) {
  let result = await rawRequest(path, options);
  if (result && result.status === 401 && !options.noRetry) {
    if (await refreshSession()) result = await rawRequest(path, options);
    else { logout(); throw new Error("Sesión caducada, vuelva a iniciar sesión"); }
  }
  if (!result) return null;
  if (!result.ok) {
    const detail = result.payload?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d.msg).join(", ")
      : `Error ${result.status}`;
    throw new Error(message);
  }
  return result.payload;
}

function setTokens(access, refresh) {
  state.tokens.access = access || "";
  state.tokens.refresh = refresh || state.tokens.refresh;
  localStorage.setItem("ng_access", state.tokens.access);
  localStorage.setItem("ng_refresh", state.tokens.refresh);
}

/* --------------------------------------------------------------- sesión */
async function login(event) {
  event.preventDefault();
  const button = $("#login-submit");
  const error = $("#login-error");
  error.classList.add("hidden");
  button.disabled = true;
  try {
    const payload = await api("/auth/login", {
      method: "POST",
      useAuth: false,
      body: {
        username: $("#login-username").value.trim(),
        password: $("#login-password").value,
      },
    });
    setTokens(payload.access_token, payload.refresh_token);
    state.user = payload.user;
    await boot();
  } catch (err) {
    error.textContent = err.message;
    error.classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

function logout() {
  state.tokens = { access: "", refresh: "" };
  localStorage.removeItem("ng_access");
  localStorage.removeItem("ng_refresh");
  state.user = null;
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

/* --------------------------------------------------- navegación por rol */
const NAV = [
  { id: "dashboard", label: "Panel", icon: "▦", roles: ["super_admin", "reseller", "user"] },
  { id: "lines", label: "Líneas", icon: "▤", roles: ["super_admin", "reseller", "user"] },
  { id: "accounts", label: "Revendedores y usuarios", icon: "👥", roles: ["super_admin", "reseller"] },
  { id: "cache", label: "Caché y peers", icon: "⚡", roles: ["super_admin", "reseller"] },
  { id: "usage", label: "Consumo ECM", icon: "🧮", roles: ["super_admin", "reseller"] },
  { id: "notifications", label: "Avisos de caducidad", icon: "🔔", roles: ["super_admin", "reseller"] },
  { id: "stats", label: "Estadísticas", icon: "📈", roles: ["super_admin", "reseller", "user"] },
  { id: "transactions", label: "Créditos", icon: "🪙", roles: ["super_admin", "reseller", "user"] },
  { id: "audit", label: "Auditoría", icon: "🛡", roles: ["super_admin", "reseller"] },
  { id: "settings", label: "Ajustes", icon: "⚙", roles: ["super_admin"] },
];

function renderNav() {
  const nav = $("#nav");
  nav.innerHTML = NAV.filter((item) => item.roles.includes(state.user.role))
    .map((item) => `<button data-view="${item.id}" class="${state.view === item.id ? "active" : ""}">
        <span class="ico">${item.icon}</span>${esc(item.label)}</button>`).join("");
  $$("#nav button").forEach((button) => {
    button.onclick = () => navigate(button.dataset.view);
  });
}

function navigate(view) {
  state.view = view;
  renderNav();
  renderView();
}

/* -------------------------------------------------------------- gráficos */
function sparkline(points, { height = 90, color = "#37d1a0" } = {}) {
  const values = points.map((p) => Number(p.value) || 0);
  if (values.length < 2) {
    return `<p class="empty small">Sin datos suficientes todavía. El panel guarda una muestra cada ${60}s
      mientras NCam esté accesible.</p>`;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const width = 600;
  const step = width / (values.length - 1);
  const scaled = values.map((value) => {
    const ratio = max === min ? 0.5 : (value - min) / (max - min);
    return height - 8 - ratio * (height - 20);
  });
  const path = scaled.map((y, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${path} L${width},${height} L0,${height} Z`;
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    <defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity=".45"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#grad)"></path>
    <path d="${path}" fill="none" stroke="${color}" stroke-width="2"></path>
  </svg>`;
}

/* ------------------------------------------------------------- dashboard */
async function viewDashboard(el) {
  const [overview, cache] = await Promise.all([
    api("/stats/overview"),
    api("/cache/stats").catch((error) => ({ reachable: false, error: error.message })),
  ]);

  const ncamPill = $("#ncam-pill");
  ncamPill.className = `pill ${overview.ncam?.reachable ? "ok" : "bad"}`;
  ncamPill.textContent = overview.ncam?.reachable ? "NCam: conectado" : "NCam: sin conexión";

  const kpi = [
    { label: "Líneas totales", value: fmtNumber(overview.lines.total), hint: `${overview.lines.active} activas`, icon: "▤" },
    { label: "Por caducar (3 días)", value: fmtNumber(overview.lines.expiring_soon), hint: `${overview.lines.expired} caducadas`, icon: "⏳" },
    { label: "Créditos propios", value: fmtNumber(overview.credits), hint: `Total cuentas: ${fmtNumber(overview.accounts.credits_total)}`, icon: "🪙" },
    { label: "Peers de caché", value: `${fmtNumber(overview.cache_servers.enabled)}/${fmtNumber(overview.cache_servers.total)}`, hint: "habilitados", icon: "⚡" },
  ];
  if (state.user.role === "super_admin") {
    kpi.push({ label: "Revendedores", value: fmtNumber(overview.accounts.resellers), hint: `${overview.accounts.users} usuarios finales`, icon: "👥" });
    kpi.push({ label: "Cuentas suspendidas", value: fmtNumber(overview.accounts.suspended), hint: "requieren revisión", icon: "⛔" });
  }

  const cacheCard = cache.reachable ? `
    <div class="card wide">
      <h3>Motor de caché NCam-NG <span class="pill ok">en vivo</span></h3>
      <div class="grid three" style="margin-top:12px">
        <div class="gauge">
          <div class="pct">${(Number(cache.hit_ratio) || 0).toFixed(1)}%</div>
          <div class="hint">aciertos sobre ${fmtNumber(cache.lookups)} consultas</div>
          <div class="bar" style="width:100%"><span style="width:${Math.min(100, Number(cache.hit_ratio) || 0)}%"></span></div>
        </div>
        <div>
          <p><strong>${fmtNumber(cache.entries)}</strong> entradas · <strong>${fmtNumber(cache.cw_entries)}</strong> CWs</p>
          <p class="hint">Memoria estimada: ${fmtBytes(cache.mem_bytes)}</p>
          <p class="hint">max_time ${cache.limits.max_time_seconds}s ·
            max_entries ${cache.limits.max_entries === 0 ? "ilimitado" : fmtNumber(cache.limits.max_entries)}</p>
        </div>
        <div>
          <p class="hint">hits ${fmtNumber(cache.hits)} · misses ${fmtNumber(cache.misses)}</p>
          <p class="hint">CW nuevos ${fmtNumber(cache.cw_new)} · actualizados ${fmtNumber(cache.cw_upd)}</p>
          <p class="hint">expulsadas por TTL ${fmtNumber(cache.evicted_ttl)} · por capacidad ${fmtNumber(cache.evicted_lru)}</p>
          <p class="hint">rechazadas por ciclo CW ${fmtNumber(cache.cwc_rejected)}</p>
        </div>
      </div>
      <h3 style="margin-top:16px">Histórico de aciertos (24 h)</h3>
      ${sparkline(cache.history || [])}
      <h3 style="margin-top:16px">Entradas más servidas</h3>
      ${cache.hot_entries?.length ? `
        <div class="table-wrap"><table>
          <thead><tr><th>CAID</th><th>Provider</th><th>Servicio</th><th>Aciertos</th><th>Origen</th></tr></thead>
          <tbody>${cache.hot_entries.map((entry) => `<tr>
            <td>${esc(entry.caid)}</td><td>${esc(entry.prid)}</td><td>${esc(entry.srvid)}</td>
            <td>${fmtNumber(entry.hits)}</td>
            <td>${[entry.from_localcards ? "tarjeta local" : "", entry.from_cacheex ? "cacheex" : "", entry.from_csp ? "csp" : ""]
              .filter(Boolean).join(", ") || "—"}</td>
          </tr>`).join("")}</tbody>
        </table></div>` : `<p class="empty small">Todavía no hay CWs servidas desde caché.</p>`}
    </div>` : `
    <div class="card wide">
      <h3>Motor de caché NCam-NG <span class="pill bad">sin conexión</span></h3>
      <p class="muted small">${esc(cache.error || "No se pudo consultar el WebIf de NCam.")}</p>
      <p class="hint">Configure la URL del WebIf en <strong>Ajustes</strong> (por defecto http://127.0.0.1:8181)
        y verifique que NCam esté en ejecución con <code>http_port</code> habilitado.</p>
      <p class="hint">Si el error es <strong>403</strong>, el daemon no permite la IP desde la que se
        conecta el panel: añádala con <code>sudo ncam-ng-ctl webif add 127.0.0.1</code> y aplique con
        <code>sudo restart-ncam</code> (si el panel va en otra máquina, esa IP).</p>
    </div>`;

  const daemonCard = overview.ncam?.reachable ? `
    <div class="card">
      <h3>Daemon NCam</h3>
      <p class="hint">versión ${esc(overview.ncam.version)} · rev ${esc(overview.ncam.revision)}</p>
      <p>Conectados: <strong>${fmtNumber(overview.ncam.totals.connected)}</strong> de ${fmtNumber(overview.ncam.totals.users)}</p>
      <p class="hint">ECM ok ${fmtNumber(overview.ncam.totals.ecm_ok)} · nok ${fmtNumber(overview.ncam.totals.ecm_nok)} · desde caché ${fmtNumber(overview.ncam.totals.from_cache)}</p>
    </div>` : `
    <div class="card"><h3>Daemon NCam</h3><p class="hint">${esc(overview.ncam?.error || "sin conexión")}</p></div>`;

  el.innerHTML = `
    <div class="grid kpi">${kpi.map((item) => `
      <div class="card">
        <h3><span>${esc(item.label)}</span><span class="kpi-icon">${item.icon}</span></h3>
        <div class="value">${item.value}</div>
        <div class="hint">${esc(item.hint)}</div>
      </div>`).join("")}
    </div>
    ${cacheCard}
    ${daemonCard}`;
}

/* ---------------------------------------------------------------- líneas */
async function viewLines(el) {
  const canManage = state.user.role !== "user";
  const [lines, accounts] = await Promise.all([
    api("/lines"),
    canManage && state.user.role !== "user" ? api("/accounts").catch(() => ({ items: [] })) : Promise.resolve({ items: [] }),
  ]);

  const owners = accounts.items || [];
  el.innerHTML = `
    <div class="toolbar">
      <input id="lines-search" placeholder="Buscar por nombre o usuario…">
      <select id="lines-protocol">
        <option value="">Todos los protocolos</option>
        <option value="cccam">CCcam</option><option value="newcamd">Newcamd</option>
        <option value="camd35">Camd35</option><option value="cacheex">CacheEx</option>
      </select>
      <select id="lines-status">
        <option value="">Todos los estados</option>
        <option value="active">Activas</option><option value="expiring">Por caducar</option>
        <option value="expired">Caducadas</option><option value="suspended">Suspendidas</option>
      </select>
      ${canManage ? `<button class="btn primary" id="line-new">+ Nueva línea</button>` : ""}
      <button class="btn ghost" id="lines-reload">Refrescar</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Nombre</th><th>Usuario</th><th>Protocolo</th><th>Propietario</th>
          <th>Caduca</th><th>Estado</th><th>CacheEx</th><th></th></tr></thead>
        <tbody id="lines-body"></tbody>
      </table>
    </div>`;

  const renderRows = (items) => {
    const body = $("#lines-body", el);
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="8" class="empty">No hay líneas que coincidan con el filtro.</td></tr>`;
      return;
    }
    body.innerHTML = items.map((line) => {
      const left = daysLeft(line.expires_at);
      return `<tr>
        <td><strong>${esc(line.name)}</strong><div class="hint">${esc(line.group_name ? `grupo ${line.group_name}` : "")}</div></td>
        <td><code>${esc(line.username)}</code></td>
        <td>${esc(line.protocol)}${line.caid_allow ? `<div class="hint">CAID ${esc(line.caid_allow)}</div>` : ""}</td>
        <td>${esc(line.owner_username || "—")}</td>
        <td class="nowrap">${fmtDate(line.expires_at)}${left !== null ? `<div class="hint">${left >= 0 ? `${left} días` : "caducada"}</div>` : ""}</td>
        <td>${statusBadge(line.effective_status)}</td>
        <td>${line.cacheex_mode ? `<span class="badge ok">modo ${line.cacheex_mode}</span>` : `<span class="badge">off</span>`}</td>
        <td class="actions">
          <button class="btn small ghost" data-act="export" data-id="${line.id}">Exportar</button>
          <button class="btn small ghost" data-act="pwd" data-id="${line.id}">Ver clave</button>
          ${canManage ? `<button class="btn small ghost" data-act="edit" data-id="${line.id}">Editar</button>` : ""}
          ${canManage ? `<button class="btn small blue" data-act="renew" data-id="${line.id}">+30 días</button>` : ""}
          ${canManage ? `<button class="btn small danger" data-act="del" data-id="${line.id}">Borrar</button>` : ""}
        </td>
      </tr>`;
    }).join("");
  };

  let cache = lines.items;
  const applyFilters = () => {
    const term = $("#lines-search", el).value.toLowerCase();
    const protocol = $("#lines-protocol", el).value;
    const status = $("#lines-status", el).value;
    renderRows(cache.filter((line) => (
      (!term || `${line.name} ${line.username}`.toLowerCase().includes(term))
      && (!protocol || line.protocol === protocol)
      && (!status || line.effective_status === status)
    )));
  };
  ["lines-search", "lines-protocol", "lines-status"].forEach((id) => {
    $(`#${id}`, el).addEventListener("input", applyFilters);
  });
  $("#lines-reload", el).onclick = () => renderView();
  applyFilters();

  const reload = async () => {
    cache = (await api("/lines")).items;
    applyFilters();
  };

  if (canManage) {
    $("#line-new", el).onclick = () => openLineForm(owners, reload);
  }

  el.querySelector("#lines-body").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const id = Number(button.dataset.id);
    const line = cache.find((item) => item.id === id);
    try {
      if (button.dataset.act === "del") {
        if (await confirmDialog("Eliminar línea", `¿Eliminar la línea ${line.name}? Esta acción no se puede deshacer.`, "Eliminar")) {
          await api(`/lines/${id}`, { method: "DELETE" });
          toast("Línea eliminada");
          await reload();
        }
      } else if (button.dataset.act === "renew") {
        await api(`/lines/${id}/renew`, { method: "POST", body: { days: 30 } });
        toast("Línea renovada 30 días");
        await reload();
      } else if (button.dataset.act === "pwd") {
        const data = await api(`/lines/${id}/password`);
        modal("Credenciales de la línea", `
          <p class="muted small">Esta consulta queda registrada en la auditoría.</p>
          <label>Usuario<input value="${esc(line.username)}" readonly></label>
          <label>Contraseña<input value="${esc(data.password)}" readonly></label>
          <div class="actions">${copyButton(`${line.username}:${data.password}`)}</div>`);
      } else if (button.dataset.act === "export") {
        openExportDialog(line);
      } else if (button.dataset.act === "edit") {
        openLineForm(owners, reload, line);
      }
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

function openLineForm(owners, onDone, line = null) {
  const editing = Boolean(line);
  const ownerOptions = owners.map((account) => `
    <option value="${account.id}" ${line && line.owner_id === account.id ? "selected" : ""}>
      ${esc(account.username)} (${esc(account.role)})</option>`).join("");

  modal(editing ? `Editar línea ${line.name}` : "Nueva línea", `
    <div class="row">
      <label>Nombre<input name="name" required maxlength="64" value="${esc(line?.name || "")}"></label>
      <label>Protocolo
        <select name="protocol">
          ${["cccam", "newcamd", "camd35", "cacheex"].map((p) =>
            `<option value="${p}" ${line?.protocol === p ? "selected" : ""}>${p}</option>`).join("")}
        </select>
      </label>
    </div>
    ${editing ? "" : `<div class="row">
      <label>Usuario (vacío = automático)<input name="username" maxlength="64"></label>
      <label>Contraseña (vacío = automática)<input name="password" maxlength="64"></label>
    </div>`}
    <div class="row">
      <label>Grupo NCam<input name="group_name" value="${esc(line?.group_name || "1")}"></label>
      <label>Conexiones máximas<input type="number" name="max_connections" min="1" max="64" value="${line?.max_connections || 1}"></label>
      <label>Saltos CCcam (cccmaxhops)
        <input type="number" name="cccmaxhops" min="-1" max="10" value="${line?.cccmaxhops ?? 1}">
        <span class="hint">1 = solo tus tarjetas directas; súbelo si el cliente revende</span>
      </label>
    </div>
    <div class="row">
      <label>CAIDs permitidos (vacío = todos)
        <input name="caid_allow" id="line-caid" maxlength="128" value="${esc(line?.caid_allow || "")}"
          placeholder="1801,1861,0B00">
      </label>
      <label>Poner/quitar rápido
        <span class="caid-quick">
          <button type="button" class="btn ghost small" data-caid="1801">1801</button>
          <button type="button" class="btn ghost small" data-caid="1861">1861</button>
          <button type="button" class="btn ghost small" data-caid="0B00">0B00</button>
          <button type="button" class="btn ghost small" data-caid="">Todos</button>
        </span>
      </label>
    </div>
    <p class="hint">Se escribe como <code>caid = …</code> en el bloque <code>[account]</code> del ncam.user:
      el cliente solo podrá ver esos CAID (<code>1801</code> = uno solo; <code>1801,1861,0B00</code> = los tres;
      vacío = sin restricción).</p>
    <div class="row">
      <label>CacheEx (0 = off)<input type="number" name="cacheex_mode" min="0" max="3" value="${line?.cacheex_mode ?? 0}"></label>
      <label>CacheEx maxhop<input type="number" name="cacheex_maxhop" min="0" max="10" value="${line?.cacheex_maxhop ?? 0}"></label>
    </div>
    <div class="row">
      ${editing ? `<label>Estado<select name="status">
          <option value="active" ${line.status === "active" ? "selected" : ""}>activa</option>
          <option value="suspended" ${line.status === "suspended" ? "selected" : ""}>suspendida</option>
        </select></label>` : `<label>Días de alta<input type="number" name="days" min="1" max="3650" value="30"></label>`}
      ${state.user.role === "super_admin" && !editing ? `<label>Propietario<select name="owner_id">${ownerOptions}</select></label>` : ""}
    </div>
    <div class="row">
      <label>Aviso por email<input type="email" name="notify_email" maxlength="200"
        value="${esc(line?.notify_email || "")}" placeholder="vacío = email del propietario"></label>
      <label>Aviso por Telegram<input name="notify_telegram" maxlength="64"
        value="${esc(line?.notify_telegram || "")}" placeholder="vacío = chat del panel"></label>
    </div>
    <label>Días de antelación del aviso (0 = global)
      <input type="number" name="notify_days" min="0" max="365" value="${line?.notify_days ?? 0}"></label>
    <label>Notas<textarea name="notes" maxlength="1000">${esc(line?.notes || "")}</textarea></label>
  `, {
    submitLabel: editing ? "Guardar cambios" : "Crear línea",
    onSubmit: async (data) => {
      if (editing) {
        const payload = {
          name: data.name, protocol: data.protocol, group_name: data.group_name,
          max_connections: Number(data.max_connections), cacheex_mode: Number(data.cacheex_mode),
          cccmaxhops: Number(data.cccmaxhops),
          cacheex_maxhop: Number(data.cacheex_maxhop), notes: data.notes || null, status: data.status,
          caid_allow: (data.caid_allow || "").trim(),
          notify_email: data.notify_email || null, notify_telegram: data.notify_telegram || null,
          notify_days: Number(data.notify_days || 0),
        };
        await api(`/lines/${line.id}`, { method: "PATCH", body: payload });
        toast("Línea actualizada");
      } else {
        const payload = {
          name: data.name, protocol: data.protocol, group_name: data.group_name,
          max_connections: Number(data.max_connections), cacheex_mode: Number(data.cacheex_mode),
          cccmaxhops: Number(data.cccmaxhops),
          cacheex_maxhop: Number(data.cacheex_maxhop), days: Number(data.days || 30),
          notes: data.notes || null,
          caid_allow: (data.caid_allow || "").trim(),
          notify_email: data.notify_email || null, notify_telegram: data.notify_telegram || null,
          notify_days: Number(data.notify_days || 0),
        };
        if (data.username) payload.username = data.username;
        if (data.password) payload.password = data.password;
        if (data.owner_id) payload.owner_id = Number(data.owner_id);
        const created = await api("/lines", { method: "POST", body: payload });
        toast(`Línea creada: ${created.username}`);
      }
      await onDone();
      return false;
    },
  });

  // botones rápidos de CAID: añaden o quitan valores del campo
  const caidInput = $("#line-caid");
  if (caidInput) {
    $$("button[data-caid]", $("#modal-root")).forEach((button) => {
      button.onclick = () => {
        const value = button.dataset.caid;
        if (!value) { caidInput.value = ""; return; }
        const current = caidInput.value.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean);
        const index = current.indexOf(value);
        if (index >= 0) current.splice(index, 1); else current.push(value);
        const order = ["1801", "1861", "0B00"];
        current.sort((a, b) => ((order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99)) || a.localeCompare(b));
        caidInput.value = current.join(",");
      };
    });
  }
}

function openExportDialog(line) {
  const formats = ["ncam", "cccam", "newcamd", "camd35", "json"];
  modal(`Exportar línea ${line.name}`, `
    <label>Formato
      <select id="export-format">${formats.map((f) => `<option value="${f}">${f}</option>`).join("")}</select>
    </label>
    <pre class="code" id="export-output">Cargando…</pre>
    <div class="actions">
      <button type="button" class="btn ghost small" id="export-copy">Copiar</button>
      <a class="btn small blue" id="export-download" href="#" download>Descargar</a>
    </div>`, { width: 720 });

  const output = $("#export-output");
  const load = async () => {
    const format = $("#export-format").value;
    const response = await fetch(`${API}/lines/${line.id}/export?format=${format}`, {
      headers: { Authorization: `Bearer ${state.tokens.access}` },
    });
    output.textContent = await response.text();
    $("#export-copy").onclick = () => navigator.clipboard?.writeText(output.textContent)
      .then(() => toast("Copiado"));
    $("#export-download").href = `${API}/lines/${line.id}/export?format=${format}&download=true`;
  };
  $("#export-format").onchange = load;
  load();
}

/* --------------------------------------------------------------- cuentas */
async function viewAccounts(el) {
  const { items } = await api("/accounts");
  const isSuper = state.user.role === "super_admin";
  const supers = items.filter((item) => item.role === "super_admin");
  const resellers = items.filter((item) => item.role === "reseller");
  const users = items.filter((item) => item.role === "user");
  // el último super administrador activo no se puede borrar ni degradar
  const lastSuperAdmin = (account) =>
    account.role === "super_admin" && account.status === "active" &&
    supers.filter((item) => item.status === "active").length <= 1;

  el.innerHTML = `
    <div class="toolbar">
      <input id="acc-search" placeholder="Buscar cuenta…">
      <button class="btn primary" id="acc-new">+ Nueva ${isSuper ? "cuenta" : "usuario final"}</button>
      <button class="btn ghost" id="acc-reload">Refrescar</button>
    </div>
    <div class="grid kpi">
      <div class="card"><h3>Cuentas visibles</h3><div class="value">${fmtNumber(items.length)}</div>
        <div class="hint">${supers.length} admin · ${resellers.length} resellers · ${users.length} usuarios</div></div>
      <div class="card"><h3>Créditos en cartera</h3>
        <div class="value">${fmtNumber(items.reduce((sum, item) => sum + (item.credits || 0), 0))}</div>
        <div class="hint">suma de saldos visibles</div></div>
      <div class="card"><h3>Líneas asignadas</h3>
        <div class="value">${fmtNumber(items.reduce((sum, item) => sum + (item.lines_count || 0), 0))}</div>
        <div class="hint">líneas de estas cuentas</div></div>
    </div>
    <div class="table-wrap">
      <table><thead><tr><th>Usuario</th><th>Rol</th><th>Padre</th><th>Créditos</th>
        <th>Líneas</th><th>Estado</th><th>API key</th><th>Último acceso</th><th></th></tr></thead>
        <tbody id="acc-body"></tbody></table>
    </div>`;

  const byId = Object.fromEntries(items.map((item) => [item.id, item]));
  const render = (list) => {
    $("#acc-body", el).innerHTML = list.length ? list.map((account) => `
      <tr>
        <td><strong>${esc(account.username)}</strong><div class="hint">${esc(account.email || "")}</div></td>
        <td>${roleBadge(account.role)}</td>
        <td>${esc(byId[account.parent_id]?.username || "—")}</td>
        <td>${fmtNumber(account.credits)}</td>
        <td>${fmtNumber(account.lines_count)}${account.max_lines ? `<span class="hint"> / ${account.max_lines}</span>` : ""}</td>
        <td>${account.status === "active" ? '<span class="badge ok">activa</span>' : '<span class="badge warn">suspendida</span>'}</td>
        <td>${account.has_api_key ? `<code>${esc(account.api_key_prefix)}…</code>` : '<span class="hint">—</span>'}</td>
        <td class="nowrap">${fmtDate(account.last_login_at, true)}</td>
        <td class="actions">
          ${isSuper ? `<button class="btn small blue" data-act="credits" data-id="${account.id}">+ Créditos</button>` : ""}
          ${account.role !== "super_admin" ? `<button class="btn small ghost" data-act="transfer" data-id="${account.id}">Transferir</button>` : ""}
          ${isSuper || account.id === state.user.id || account.role !== "super_admin" ? `<button class="btn small ghost" data-act="edit" data-id="${account.id}">Editar</button>` : ""}
          <button class="btn small ghost" data-act="apikey" data-id="${account.id}">API key</button>
          ${account.id !== state.user.id && !lastSuperAdmin(account)
            ? `<button class="btn small danger" data-act="del" data-id="${account.id}">Borrar</button>` : ""}
        </td>
      </tr>`).join("") : `<tr><td colspan="9" class="empty">Sin cuentas que mostrar.</td></tr>`;
  };
  render(items);

  $("#acc-search", el).addEventListener("input", (event) => {
    const term = event.target.value.toLowerCase();
    render(items.filter((item) => item.username.toLowerCase().includes(term)));
  });
  $("#acc-reload", el).onclick = () => renderView();
  $("#acc-new", el).onclick = () => openAccountForm(async () => renderView());

  $("#acc-body", el).addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const account = byId[Number(button.dataset.id)];
    const act = button.dataset.act;
    try {
      if (act === "del") {
        if (await confirmDialog("Eliminar cuenta", `¿Eliminar ${account.username} y todas sus líneas?`, "Eliminar")) {
          await api(`/accounts/${account.id}`, { method: "DELETE" });
          toast("Cuenta eliminada");
          renderView();
        }
      } else if (act === "credits") {
        modal(`Añadir créditos a ${account.username}`, `
          <label>Cantidad<input type="number" name="amount" min="1" value="100" required></label>
          <label>Descripción<input name="description" placeholder="Recarga manual"></label>`,
        {
          submitLabel: "Añadir créditos",
          onSubmit: async (data) => {
            const result = await api(`/accounts/${account.id}/credits`, {
              method: "POST",
              body: { amount: Number(data.amount), description: data.description || null },
            });
            toast(`Saldo de ${account.username}: ${fmtNumber(result.credits)}`);
            renderView();
            return false;
          },
        });
      } else if (act === "transfer") {
        modal(`Transferir créditos a ${account.username}`, `
          <p class="muted small">Se descuentan de su saldo (${fmtNumber(state.user.credits)}).</p>
          <label>Cantidad<input type="number" name="amount" min="1" value="50" required></label>
          <label>Descripción<input name="description" placeholder="Saldo para el cliente"></label>`,
        {
          submitLabel: "Transferir",
          onSubmit: async (data) => {
            const result = await api(`/accounts/${state.user.id}/transfer`, {
              method: "POST",
              body: { target_id: account.id, amount: Number(data.amount), description: data.description || null },
            });
            toast(`Transferido. Su saldo: ${fmtNumber(result.source_balance)}`);
            await refreshUser();
            renderView();
            return false;
          },
        });
      } else if (act === "apikey") {
        if (await confirmDialog("Generar API key", `Se generará una nueva clave para ${account.username}. Las anteriores dejarán de funcionar.`, "Generar")) {
          const result = await api(`/accounts/${account.id}/api-key`, { method: "POST" });
          modal("API key generada", `
            <p class="muted small">${esc(result.warning)}</p>
            <pre class="code">${esc(result.api_key)}</pre>
            <div class="actions">${copyButton(result.api_key)}</div>`);
          renderView();
        }
      } else if (act === "edit") {
        openAccountForm(async () => renderView(), account);
      }
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

function openAccountForm(onDone, account = null) {
  const editing = Boolean(account);
  const isSuper = state.user.role === "super_admin";
  modal(editing ? `Editar cuenta ${account.username}` : "Nueva cuenta", `
    ${editing ? "" : `<div class="row">
      <label>Usuario<input name="username" required minlength="3" pattern="[A-Za-z0-9._-]+"></label>
      <label>Contraseña<input name="password" type="password" required minlength="8"></label>
    </div>
    ${isSuper ? `<label>Rol<select name="role">
        <option value="user">Usuario final (solo sus líneas, sin gestión)</option>
        <option value="reseller" ${editing ? "" : "selected"}>Revendedor (sus líneas y sus usuarios)</option>
        <option value="super_admin">Administrador (control total del panel)</option>
      </select></label>
      <div class="hint">Un <strong>administrador</strong> (super admin) puede crear otros
      administradores, repartir créditos, tocar los Ajustes y ver la auditoría completa.</div>` : ""}`}
    ${editing && isSuper ? `<label>Rol actual<select name="role" ${account.id === state.user.id ? "disabled" : ""}>
        <option value="super_admin" ${account.role === "super_admin" ? "selected" : ""}>Administrador (control total)</option>
        <option value="reseller" ${account.role === "reseller" ? "selected" : ""}>Revendedor</option>
        <option value="user" ${account.role === "user" ? "selected" : ""}>Usuario final</option>
      </select></label>
      <div class="hint">${account.id === state.user.id
        ? "No puede cambiarse el rol a sí mismo."
        : "Cambiar de rol no borra sus líneas; los usuarios de un revendedor quedan sin padre."}</div>` : ""}
    ${editing ? `<label>Nueva contraseña (vacío = sin cambios)<input name="password" type="password" minlength="8"></label>` : ""}
    <div class="row">
      <label>Email<input name="email" type="email" value="${esc(account?.email || "")}"></label>
      ${editing && isSuper ? `<label>Créditos<input type="number" name="credits" min="0" value="${account.credits}"></label>`
        : (!editing && isSuper ? `<label>Créditos iniciales<input type="number" name="credits" min="0" value="0"></label>` : "")}
    </div>
    <div class="row">
      ${isSuper ? `<label>Límite de líneas (0 = sin límite)<input type="number" name="max_lines" min="0" value="${account?.max_lines ?? 0}"></label>` : ""}
      ${editing ? `<label>Estado<select name="status">
          <option value="active" ${account.status === "active" ? "selected" : ""}>activa</option>
          <option value="suspended" ${account.status === "suspended" ? "selected" : ""}>suspendida</option>
        </select></label>` : ""}
    </div>
    <label>Notas<textarea name="notes">${esc(account?.notes || "")}</textarea></label>
  `, {
    submitLabel: editing ? "Guardar" : "Crear cuenta",
    onSubmit: async (data) => {
      if (editing) {
        const payload = { email: data.email, notes: data.notes, status: data.status };
        if (data.password) payload.password = data.password;
        if (isSuper && data.role && data.role !== account.role) payload.role = data.role;
        if (isSuper && data.credits !== undefined) payload.credits = Number(data.credits);
        if (isSuper && data.max_lines !== undefined) payload.max_lines = Number(data.max_lines);
        await api(`/accounts/${account.id}`, { method: "PATCH", body: payload });
        toast("Cuenta actualizada");
      } else {
        const payload = {
          username: data.username, password: data.password, role: data.role || "user",
          email: data.email || null, notes: data.notes || null,
          credits: Number(data.credits || 0), max_lines: Number(data.max_lines || 0),
        };
        await api("/accounts", { method: "POST", body: payload });
        toast("Cuenta creada");
      }
      await onDone();
      return false;
    },
  });
}

/* ----------------------------------------------------------------- caché */
async function viewCache(el) {
  const isSuper = state.user.role === "super_admin";
  const [cache, servers, limits] = await Promise.all([
    api("/cache/stats").catch((error) => ({ reachable: false, error: error.message, history: [], hot_entries: [], peers: { total: 0, online: 0 } })),
    api("/cache/servers"),
    api("/cache/limits"),
  ]);

  el.innerHTML = `
    <div class="grid kpi">
      <div class="card"><h3>Estado del motor</h3>
        <div class="value">${cache.reachable ? "En línea" : "Sin conexión"}</div>
        <div class="hint">${esc(cache.reachable ? cache.engine : cache.error || "")}</div></div>
      <div class="card"><h3>Aciertos</h3><div class="value">${cache.reachable ? `${(Number(cache.hit_ratio) || 0).toFixed(1)}%` : "—"}</div>
        <div class="hint">${fmtNumber(cache.lookups)} consultas</div></div>
      <div class="card"><h3>Entradas</h3><div class="value">${fmtNumber(cache.entries)}</div>
        <div class="hint">${fmtNumber(cache.cw_entries)} CWs · ${fmtBytes(cache.mem_bytes)}</div></div>
      <div class="card"><h3>Peers</h3><div class="value">${fmtNumber(cache.peers?.online)}/${fmtNumber(cache.peers?.total)}</div>
        <div class="hint">online/total</div></div>
    </div>

    <div class="card">
      <h3>Ajustes del motor <span class="hint">se exportan a ncam.conf</span></h3>
      <div class="grid three">
        <label>max_time (segundos)<input id="limit-max-time" type="number" min="3" max="600" value="${limits.max_time}"></label>
        <label>max_entries (0 = ilimitado)<input id="limit-max-entries" type="number" min="0" max="10000000" value="${limits.max_entries}"></label>
        <label>CacheEx<select id="limit-cacheex">
          <option value="1" ${limits.cacheex_enabled ? "selected" : ""}>habilitado</option>
          <option value="0" ${limits.cacheex_enabled ? "" : "selected"}>deshabilitado</option>
        </select></label>
      </div>
      ${isSuper ? `<div class="actions" style="margin-top:12px">
        <button class="btn primary" id="limits-save">Guardar ajustes</button>
        <button class="btn ghost" id="limits-export">Generar bloques de configuración</button>
        <a class="btn ghost" href="${API}/cache/config/download?file=ncam.conf" onclick="return ncamDownload(event)">Descargar ncam.conf</a>
      </div>` : `<p class="hint">Solo el super administrador puede cambiar estos ajustes.</p>`}
    </div>

    <div class="card">
      <h3>Histórico de aciertos
        <span class="toolbar">
          <button class="btn small ghost" data-range="1">1 h</button>
          <button class="btn small ghost" data-range="24">24 h</button>
          <button class="btn small ghost" data-range="168">7 d</button>
          <button class="btn small blue" id="snapshot-now">Guardar muestra</button>
        </span>
      </h3>
      <div id="cache-chart">${sparkline(cache.history || [])}</div>
    </div>

    <div class="card wide">
      <h3>Peers de caché <button class="btn small primary" id="peer-new">+ Nuevo peer</button></h3>
      <div class="table-wrap" style="margin-top:12px">
        <table><thead><tr><th>Nombre</th><th>Dirección</th><th>Protocolo</th><th>Propietario</th>
          <th>Prioridad</th><th>Último test</th><th>Estado</th><th></th></tr></thead>
          <tbody>${servers.items.length ? servers.items.map((server) => `
            <tr>
              <td><strong>${esc(server.name)}</strong></td>
              <td><code>${esc(server.host)}:${esc(server.port)}</code></td>
              <td>${esc(server.protocol)}</td>
              <td>${esc(server.owner_username || "—")}</td>
              <td>${fmtNumber(server.priority)}</td>
              <td class="nowrap">${server.last_check_at ? `${fmtDate(server.last_check_at, true)}<div class="hint">${
                server.last_check_ok ? `${server.last_check_ms} ms` : esc(server.last_check_error || "falló")}</div>` : "—"}</td>
              <td>${server.enabled ? '<span class="badge ok">habilitado</span>' : '<span class="badge">deshabilitado</span>'}</td>
              <td class="actions">
                <button class="btn small blue" data-peer="test" data-id="${server.id}">Probar</button>
                <button class="btn small ghost" data-peer="config" data-id="${server.id}">Config</button>
                <button class="btn small ghost" data-peer="edit" data-id="${server.id}">Editar</button>
                <button class="btn small danger" data-peer="del" data-id="${server.id}">Borrar</button>
              </td>
            </tr>`).join("") : `<tr><td colspan="8" class="empty">Todavía no hay peers de caché configurados.</td></tr>`}
          </tbody></table>
      </div>
    </div>`;

  const ranges = { 1: 1, 24: 24, 168: 168 };
  $$("[data-range]", el).forEach((button) => {
    button.onclick = async () => {
      const data = await api(`/cache/stats/history?metric=cache.hit_ratio&hours=${ranges[button.dataset.range]}`);
      $("#cache-chart", el).innerHTML = sparkline(data.items);
    };
  });

  $("#snapshot-now", el).onclick = async () => {
    try {
      const result = await api("/cache/stats/snapshot", { method: "POST" });
      toast(result.saved ? `Muestra guardada (${result.saved} métricas)` : `No se pudo guardar: ${result.detail}`,
        result.saved ? "ok" : "warn");
    } catch (error) { toast(error.message, "error"); }
  };

  if (isSuper) {
    $("#limits-save", el).onclick = async () => {
      try {
        await api("/settings", {
          method: "PATCH",
          body: { values: {
            "ncam.cache.max_time": $("#limit-max-time", el).value,
            "ncam.cache.max_entries": $("#limit-max-entries", el).value,
            "ncam.cache.cacheex_enable": $("#limit-cacheex", el).value,
          } },
        });
        toast("Ajustes guardados");
      } catch (error) { toast(error.message, "error"); }
    };
    $("#limits-export", el).onclick = async () => {
      const data = await api("/cache/config");
      modal("Configuración para NCam", `
        <p class="muted small">Copie cada bloque en el archivo correspondiente del daemon y recargue NCam.</p>
        ${Object.entries(data.blocks).map(([file, content]) => `
          <h3 style="margin-top:10px">${esc(file)} ${copyButton(content)}</h3>
          <pre class="code">${esc(content || "# (vacío)")}</pre>`).join("")}
      `, { width: 760 });
    };
  }

  $("#peer-new", el).onclick = () => openPeerForm(async () => renderView());

  el.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-peer]");
    if (!button) return;
    const id = Number(button.dataset.id);
    const server = servers.items.find((item) => item.id === id);
    try {
      if (button.dataset.peer === "test") {
        const result = await api(`/cache/servers/${id}/test`, { method: "POST" });
        toast(result.ok ? `Respuesta en ${result.latency_ms} ms` : `Sin respuesta: ${result.error}`, result.ok ? "ok" : "error");
        renderView();
      } else if (button.dataset.peer === "config") {
        const data = await api(`/cache/servers/${id}/config`);
        modal(`Config de ${server.name}`, `<pre class="code">${esc(data.block)}</pre>
          <div class="actions">${copyButton(data.block)}</div>`, { width: 700 });
      } else if (button.dataset.peer === "edit") {
        openPeerForm(async () => renderView(), server);
      } else if (button.dataset.peer === "del") {
        if (await confirmDialog("Eliminar peer", `¿Eliminar ${server.name}?`, "Eliminar")) {
          await api(`/cache/servers/${id}`, { method: "DELETE" });
          toast("Peer eliminado");
          renderView();
        }
      }
    } catch (error) { toast(error.message, "error"); }
  });
}

function ncamDownload(event) {
  // la descarga necesita el token: se resuelve por fetch + blob
  event.preventDefault();
  const link = event.currentTarget;
  fetch(link.href, { headers: { Authorization: `Bearer ${state.tokens.access}` } })
    .then((response) => response.blob())
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "ncam.conf";
      anchor.click();
      URL.revokeObjectURL(url);
    })
    .catch(() => toast("No se pudo descargar", "error"));
  return false;
}
window.ncamDownload = ncamDownload;

function openPeerForm(onDone, server = null) {
  const editing = Boolean(server);
  modal(editing ? `Editar peer ${server.name}` : "Nuevo peer de caché", `
    <div class="row">
      <label>Nombre<input name="name" required value="${esc(server?.name || "")}"></label>
      <label>Protocolo<select name="protocol">
        ${["cccam", "camd35", "newcamd", "csp"].map((p) =>
          `<option value="${p}" ${server?.protocol === p ? "selected" : ""}>${p}</option>`).join("")}
      </select></label>
    </div>
    <div class="row">
      <label>Host / IP<input name="host" required value="${esc(server?.host || "")}"></label>
      <label>Puerto<input type="number" name="port" min="1" max="65535" required value="${server?.port || 12000}"></label>
    </div>
    <div class="row">
      <label>Usuario<input name="username" value="${esc(server?.username || "")}"></label>
      <label>Contraseña<input name="password" value=""></label>
    </div>
    <div class="row">
      <label>Node ID (opcional)<input name="node_id" value="${esc(server?.node_id || "")}"></label>
      <label>Prioridad<input type="number" name="priority" min="0" max="100" value="${server?.priority ?? 0}"></label>
    </div>
    <label><input type="checkbox" name="enabled" ${server?.enabled !== 0 ? "checked" : ""}> habilitado</label>
  `, {
    submitLabel: editing ? "Guardar" : "Crear peer",
    onSubmit: async (data) => {
      const payload = {
        name: data.name, host: data.host, port: Number(data.port), protocol: data.protocol,
        username: data.username || null, node_id: data.node_id || null,
        priority: Number(data.priority || 0), enabled: data.enabled === "on",
      };
      if (data.password) payload.password = data.password;
      if (editing) await api(`/cache/servers/${server.id}`, { method: "PATCH", body: payload });
      else await api("/cache/servers", { method: "POST", body: payload });
      toast(editing ? "Peer actualizado" : "Peer creado");
      await onDone();
      return false;
    },
  });
}

/* ------------------------------------------------------------ estadísticas */
async function viewStats(el) {
  const [overview, expiring] = await Promise.all([
    api("/stats/overview"),
    api("/stats/expiring?days=7"),
  ]);
  el.innerHTML = `
    <div class="grid two">
      <div class="card">
        <h3>Aciertos de caché (24 h)</h3>
        <div id="chart-hit">${sparkline((await api("/stats/timeseries?metric=cache.hit_ratio&hours=24")).items)}</div>
      </div>
      <div class="card">
        <h3>Entradas en caché</h3>
        <div id="chart-entries">${sparkline((await api("/stats/timeseries?metric=cache.entries&hours=24")).items, { color: "#4c8dff" })}</div>
      </div>
      <div class="card">
        <h3>ECM servidas desde caché</h3>
        <div id="chart-ecm">${sparkline((await api("/stats/timeseries?metric=ncam.ecm_from_cache&hours=24")).items, { color: "#ffb03a" })}</div>
      </div>
      <div class="card">
        <h3>Usuarios conectados</h3>
        <div id="chart-users">${sparkline((await api("/stats/timeseries?metric=ncam.users_connected&hours=24")).items, { color: "#37d1a0" })}</div>
      </div>
    </div>
    <div class="card wide">
      <h3>Líneas que caducan en 7 días</h3>
      ${expiring.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Línea</th><th>Usuario</th><th>Propietario</th><th>Caduca</th><th>Días</th></tr></thead>
        <tbody>${expiring.items.map((line) => `<tr>
          <td>${esc(line.name)}</td><td><code>${esc(line.username)}</code></td>
          <td>${esc(line.owner_username)}</td><td>${fmtDate(line.expires_at)}</td>
          <td>${daysLeft(line.expires_at)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="empty small">Ninguna línea caduca en los próximos 7 días.</p>`}
    </div>
    <div class="card wide">
      <h3>Resumen general</h3>
      <div class="grid three">
        <div><p class="hint">Líneas activas</p><div class="value">${fmtNumber(overview.lines.active)}</div></div>
        <div><p class="hint">Créditos en circulación</p><div class="value">${fmtNumber(overview.accounts.credits_total)}</div></div>
        <div><p class="hint">Muestras guardadas (24 h)</p><div class="value">${fmtNumber(overview.cache.snapshots_24h)}</div></div>
      </div>
    </div>`;
}

/* ------------------------------------------------------------- créditos */
async function viewTransactions(el) {
  const { items } = await api("/accounts/transactions?limit=300");
  el.innerHTML = `
    <div class="toolbar">
      <input id="tx-search" placeholder="Buscar por usuario o descripción…">
      <select id="tx-kind">
        <option value="">Todos los tipos</option>
        <option value="topup">Recargas</option><option value="debit">Consumos</option>
        <option value="adjust">Ajustes</option><option value="refund">Devoluciones</option>
      </select>
      <button class="btn ghost" id="tx-reload">Refrescar</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Fecha</th><th>Cuenta</th><th>Tipo</th><th>Importe</th><th>Saldo</th><th>Descripción</th><th>Autor</th></tr></thead>
      <tbody id="tx-body"></tbody></table></div>`;

  const kindLabels = { topup: "recarga", debit: "consumo", adjust: "ajuste", refund: "devolución" };
  const render = (list) => {
    $("#tx-body", el).innerHTML = list.length ? list.map((tx) => `
      <tr>
        <td class="nowrap">${fmtDate(tx.created_at, true)}</td>
        <td>${esc(tx.user_username)}</td>
        <td><span class="badge ${tx.amount >= 0 ? "ok" : "warn"}">${esc(kindLabels[tx.kind] || tx.kind)}</span></td>
        <td>${tx.amount >= 0 ? "+" : ""}${fmtNumber(tx.amount)}</td>
        <td>${fmtNumber(tx.balance_after)}</td>
        <td>${esc(tx.description || "—")}</td>
        <td>${esc(tx.actor_username || "sistema")}</td>
      </tr>`).join("") : `<tr><td colspan="7" class="empty">Sin movimientos.</td></tr>`;
  };
  render(items);

  const filter = () => {
    const term = $("#tx-search", el).value.toLowerCase();
    const kind = $("#tx-kind", el).value;
    render(items.filter((tx) => (
      (!term || `${tx.user_username} ${tx.description || ""}`.toLowerCase().includes(term))
      && (!kind || tx.kind === kind)
    )));
  };
  $("#tx-search", el).addEventListener("input", filter);
  $("#tx-kind", el).addEventListener("change", filter);
  $("#tx-reload", el).onclick = () => renderView();
}

/* --------------------------------------------------------------- consumo */
async function viewUsage(el) {
  const [usage, history] = await Promise.all([
    api("/billing/ecm"),
    api("/billing/ecm/history?limit=50"),
  ]);
  const conf = usage.settings;

  el.innerHTML = `
    <div class="grid two">
      <div class="card">
        <h3>Tarifa por consumo</h3>
        <p class="muted small">El consumo se mide leyendo del daemon las ECM servidas por cada
          cuenta y se factura por bloques completos. Nunca se cobra por adelantado.</p>
        <div class="grid three" style="margin-top:8px">
          <div><p class="hint">Facturación</p><div class="value">${conf.enabled ? "activa" : "manual"}</div></div>
          <div><p class="hint">Bloque</p><div class="value">${fmtNumber(conf.block)} ECM</div></div>
          <div><p class="hint">Precio</p><div class="value">${fmtNumber(conf.price)} ${esc(usage.currency)}</div></div>
        </div>
        ${conf.suspend_on_debt ? '<p class="hint">Las líneas con consumo impagado se suspenden.</p>' : ""}
      </div>
      <div class="card">
        <h3>Facturar ahora</h3>
        <p class="muted small">Mide el consumo en el daemon y descuenta los bloques completos
          pendientes del saldo del propietario. La simulación no cobra nada.</p>
        <div class="toolbar" style="margin-top:12px">
          <button class="btn ghost" id="ecm-dry">Simular facturación</button>
          <button class="btn primary" id="ecm-run">Medir y facturar</button>
          <button class="btn blue" id="ecm-refresh">${state.user.role === "super_admin" ? "Solo medir" : ""}</button>
        </div>
        <pre id="ecm-report" class="hint" style="white-space:pre-wrap;margin-top:10px"></pre>
      </div>
    </div>
    <div class="card wide">
      <h3>Consumo por línea</h3>
      ${usage.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Línea</th><th>Usuario</th><th>Propietario</th><th>ECM servidas</th>
          <th>ECM facturadas</th><th>Pendientes</th><th>Bloques</th><th>Importe pendiente</th></tr></thead>
        <tbody>${usage.items.map((item) => `<tr>
          <td><strong>${esc(item.line)}</strong><div class="hint">${esc(item.protocol)}</div></td>
          <td><code>${esc(item.username)}</code></td>
          <td>${esc(item.owner)}</td>
          <td>${fmtNumber(item.ecm_total)}</td>
          <td>${fmtNumber(item.ecm_billed)}</td>
          <td>${fmtNumber(item.ecm_pending)}</td>
          <td>${fmtNumber(item.blocks_pending)}</td>
          <td>${fmtNumber(item.credits_pending)} ${esc(usage.currency)}</td>
        </tr>`).join("")}</tbody></table></div>`
        : `<p class="empty small">No hay líneas con contadores de ECM todavía.
             Exporte las líneas al daemon y pulse «Medir y facturar».</p>`}
    </div>
    <div class="card wide">
      <h3>Últimas mediciones y cargos</h3>
      ${history.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Fecha</th><th>Línea</th><th>Contador</th><th>Nuevas ECM</th>
          <th>Bloques cobrados</th><th>Créditos</th><th>Nota</th></tr></thead>
        <tbody>${history.items.map((row) => `<tr>
          <td class="nowrap">${fmtDate(row.measured_at, true)}</td>
          <td>${esc(row.line_name || row.line_id || "—")}</td>
          <td>${fmtNumber(row.ecm_ok)}</td>
          <td>${row.ecm_delta ? `+${fmtNumber(row.ecm_delta)}` : "0"}</td>
          <td>${fmtNumber(row.blocks)}</td>
          <td>${row.credits ? fmtNumber(row.credits) : "—"}</td>
          <td>${esc(row.note || "")}</td>
        </tr>`).join("")}</tbody></table></div>`
        : `<p class="empty small">Sin mediciones registradas.</p>`}
    </div>`;

  const report = (data) => {
    const lines = data.lines || [];
    const summary = [
      `Enviados a facturar: ${lines.length} línea(s)`,
      `Bloques cobrados: ${data.billed_blocks} · Créditos: ${data.billed_credits} ${data.currency || ""}`,
      data.measurement && data.measurement.reachable === false
        ? `Daemon inalcanzable: ${data.measurement.error}`
        : `Medición: ${data.measurement ? data.measurement.updated : 0} línea(s) actualizadas`,
      data.skipped.length ? `Avisos: ${data.skipped.map((s) => s.reason).join("; ")}` : "",
    ].filter(Boolean).join("\n");
    $("#ecm-report", el).textContent = summary;
  };

  $("#ecm-dry", el).onclick = async () => report(await api("/billing/ecm/run", { method: "POST", body: { dry_run: true } }));
  $("#ecm-run", el).onclick = async () => {
    const data = await api("/billing/ecm/run", { method: "POST", body: {} });
    report(data);
    toast(`Consumo facturado: ${data.billed_credits} créditos`);
    renderView();
  };
  const refreshBtn = $("#ecm-refresh", el);
  if (state.user.role === "super_admin") {
    refreshBtn.onclick = async () => {
      const data = await api("/billing/ecm/refresh", { method: "POST" });
      $("#ecm-report", el).textContent = JSON.stringify(data.measured || data, null, 1);
    };
  } else {
    refreshBtn.style.display = "none";
  }
}

/* ---------------------------------------------------------- notificaciones */
async function viewNotifications(el) {
  const isAdmin = state.user.role === "super_admin";
  const [expiring, config, log] = await Promise.all([
    api("/notifications/expiring?days=7"),
    api("/notifications/config"),
    api("/notifications/log?limit=50"),
  ]);

  const channelBadge = (on, ready) => on
    ? `<span class="badge ${ready ? "ok" : "warn"}">${ready ? "activo" : "sin configurar"}</span>`
    : `<span class="badge">desactivado</span>`;

  el.innerHTML = `
    <div class="grid two">
      <div class="card">
        <h3>Estado de los avisos</h3>
        <div class="grid three" style="margin-top:8px">
          <div><p class="hint">Avisos automáticos</p>
            <div class="value">${config.enabled ? "sí" : "no"}</div></div>
          <div><p class="hint">Antelación</p>
            <div class="value">${fmtNumber(config.days_before)} días</div></div>
          <div><p class="hint">Frecuencia</p>
            <div class="value">${fmtNumber(Math.round(config.interval_seconds / 60))} min</div></div>
        </div>
        <p class="hint" style="margin-top:10px">Email ${channelBadge(config.email.enabled, config.email.ready)}
          &nbsp;·&nbsp; Telegram ${channelBadge(config.telegram.enabled, config.telegram.ready)}</p>
        ${isAdmin ? `<p class="muted small">Configure los datos SMTP y el bot de Telegram en <strong>Ajustes</strong>.</p>` : ""}
      </div>
      <div class="card">
        <h3>Enviar avisos manualmente</h3>
        <p class="muted small">Se avisa a las líneas que caducan dentro de la ventana configurada.
          La simulación no envía nada ni deja registro.</p>
        <div class="toolbar" style="margin-top:12px">
          <button class="btn ghost" id="notif-dry">Simular envío</button>
          <button class="btn primary" id="notif-run">Enviar avisos ahora</button>
          ${isAdmin ? `<button class="btn blue" id="notif-test-email">Probar email</button>
          <button class="btn blue" id="notif-test-tg">Probar Telegram</button>` : ""}
        </div>
        <pre id="notif-report" class="hint" style="white-space:pre-wrap;margin-top:10px"></pre>
      </div>
    </div>
    <div class="card wide">
      <h3>Líneas que caducan en ${fmtNumber(expiring.days_before)} días</h3>
      ${expiring.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Línea</th><th>Usuario</th><th>Propietario</th><th>Caduca</th><th>Días</th>
          <th>Aviso email</th><th>Aviso Telegram</th><th>Antelación</th></tr></thead>
        <tbody>${expiring.items.map((line) => `<tr>
          <td><strong>${esc(line.name)}</strong><div class="hint">${esc(line.protocol)}</div></td>
          <td><code>${esc(line.username)}</code></td>
          <td>${esc(line.owner_username)}</td>
          <td class="nowrap">${fmtDate(line.expires_at)}</td>
          <td>${line.days_left}</td>
          <td>${line.notify_email ? esc(line.notify_email) : `<span class="hint">propietario</span>`}</td>
          <td>${line.notify_telegram ? esc(line.notify_telegram) : `<span class="hint">chat del panel</span>`}</td>
          <td>${line.notify_days ? `${line.notify_days} días` : `<span class="hint">${config.days_before} (global)</span>`}</td>
        </tr>`).join("")}</tbody></table></div>`
        : `<p class="empty small">Ninguna línea caduca en ese plazo.</p>`}
    </div>
    <div class="card wide">
      <h3>Últimos avisos enviados</h3>
      ${log.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Fecha</th><th>Línea</th><th>Canal</th><th>Destino</th><th>Días</th><th>Resultado</th></tr></thead>
        <tbody>${log.items.map((item) => `<tr>
          <td class="nowrap">${fmtDate(item.created_at, true)}</td>
          <td>${esc(item.line_name || item.line_id || "—")}</td>
          <td>${esc(item.channel)}</td>
          <td>${esc(item.target || "—")}</td>
          <td>${item.days_left}</td>
          <td><span class="badge ${item.status === "sent" ? "ok" : item.status === "failed" ? "bad" : ""}">${esc(item.status)}</span>
            ${item.error ? `<div class="hint">${esc(item.error)}</div>` : ""}</td>
        </tr>`).join("")}</tbody></table></div>`
        : `<p class="empty small">Todavía no se ha enviado ningún aviso.</p>`}
    </div>`;

  const report = (data) => {
    $("#notif-report", el).textContent =
      `Enviados: ${data.sent.length} · Fallidos: ${data.failed.length} · Omitidos: ${data.skipped.length}`;
  };

  $("#notif-dry", el).onclick = async () => report(await api("/notifications/run", {
    method: "POST", body: { dry_run: true },
  }));
  $("#notif-run", el).onclick = async () => {
    const data = await api("/notifications/run", { method: "POST", body: {} });
    report(data);
    toast(`Avisos enviados: ${data.sent.length}`);
    renderView();
  };
  if (isAdmin) {
    $("#notif-test-email", el).onclick = async () => {
      await api("/notifications/test", { method: "POST", body: { channel: "email" } });
      toast("Mensaje de prueba enviado por email");
    };
    $("#notif-test-tg", el).onclick = async () => {
      await api("/notifications/test", { method: "POST", body: { channel: "telegram" } });
      toast("Mensaje de prueba enviado por Telegram");
    };
  }
}

/* -------------------------------------------------------------- auditoría */
async function viewAudit(el) {
  const { items } = await api("/audit-logs?limit=300");
  el.innerHTML = `
    <div class="toolbar">
      <input id="audit-search" placeholder="Buscar acción, usuario o IP…">
      <button class="btn ghost" id="audit-reload">Refrescar</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Fecha</th><th>Actor</th><th>Acción</th><th>Objeto</th><th>Detalles</th><th>IP</th></tr></thead>
      <tbody id="audit-body"></tbody></table></div>`;

  const render = (list) => {
    $("#audit-body", el).innerHTML = list.length ? list.map((log) => `
      <tr>
        <td class="nowrap">${fmtDate(log.created_at, true)}</td>
        <td>${esc(log.actor_username || "sistema")} ${log.actor_role ? roleBadge(log.actor_role) : ""}</td>
        <td><code>${esc(log.action)}</code></td>
        <td>${esc(log.target_type || "")}${log.target_id ? ` #${log.target_id}` : ""}</td>
        <td><span class="hint">${esc((log.details || "").slice(0, 120))}</span></td>
        <td>${esc(log.ip || "—")}</td>
      </tr>`).join("") : `<tr><td colspan="6" class="empty">Sin eventos.</td></tr>`;
  };
  render(items);
  $("#audit-search", el).addEventListener("input", (event) => {
    const term = event.target.value.toLowerCase();
    render(items.filter((log) => JSON.stringify(log).toLowerCase().includes(term)));
  });
  $("#audit-reload", el).onclick = () => renderView();
}

/* ---------------------------------------------------------------- ajustes */
// Cada ajuste con su etiqueta y su ayuda, agrupado por para qué sirve.
const SETTING_GROUPS = [
  {
    title: "Panel",
    hint: "Identidad del panel y datos que se publican a los clientes al exportar sus líneas.",
    fields: [
      { key: "panel.name", label: "Nombre del panel", hint: "aparece en la interfaz y en el asunto de los avisos" },
      { key: "panel.public_host", label: "Host público", hint: "IP o dominio que se escribe en las líneas exportadas (no lo dejes en TU_SERVIDOR)" },
      { key: "panel.port.cccam", label: "Puerto CCcam", hint: "debe coincidir con [cccam] port de ncam.conf" },
      { key: "panel.port.newcamd", label: "Puerto Newcamd", hint: "debe coincidir con [newcamd] port de ncam.conf" },
      { key: "panel.port.camd35", label: "Puerto Camd35", hint: "debe coincidir con [camd35] port de ncam.conf" },
      { key: "panel.port.cacheex", label: "Puerto Cacheex", hint: "debe coincidir con [cache] port de ncam.conf" },
    ],
  },
  {
    title: "Daemon NCam (WebIf)",
    hint: "De aquí salen el estado, las estadísticas del motor de caché y los contadores de ECM. Se aplican al instante.",
    fields: [
      { key: "panel.ncam_webif_url", label: "URL del WebIf", hint: "con puerto, p. ej. http://127.0.0.1:8181" },
      { key: "panel.ncam_webif_user", label: "Usuario del WebIf", hint: "vacío = el del fichero .env" },
      { key: "panel.ncam_webif_password", label: "Contraseña del WebIf", hint: "se guarda en la base de datos y la API nunca la devuelve" },
    ],
  },
  {
    title: "Motor de caché",
    hint: "Valores con los que el panel genera el bloque [cache] de ncam.conf (Caché y peers → Exportar configuración, copiar y reiniciar NCam).",
    fields: [
      { key: "ncam.cache.max_time", label: "max_time (segundos)", hint: "tiempo que una entrada se considera válida" },
      { key: "ncam.cache.max_entries", label: "max_entries (entradas)", hint: "0 = sin límite; con límite se expulsa primero lo menos usado (LRU)" },
      { key: "ncam.cache.cacheex_enable", label: "Cacheex activado (1/0)", hint: "añade las opciones de caché compartida al bloque generado" },
      { key: "ncam.cache.panel_poll", label: "Muestreo automático (1/0)", hint: "guarda una muestra de métricas cada 60 s para los gráficos" },
    ],
  },
  {
    title: "Créditos y facturación",
    hint: "Reglas de negocio: lo que cuesta crear y renovar líneas, y el cobro por consumo real de ECM.",
    fields: [
      { key: "billing.currency", label: "Nombre de la moneda", hint: "etiqueta que se muestra en saldos y movimientos" },
      { key: "billing.line_cost", label: "Coste por línea (créditos)", hint: "se descuenta al crear una línea" },
      { key: "billing.renew_cost", label: "Coste por renovación (créditos)", hint: "se descuenta al renovar (+días)" },
      { key: "billing.ecm.enabled", label: "Facturar consumo de ECM (1/0)", hint: "cobra solo bloques completos, nunca por adelantado" },
      { key: "billing.ecm.price", label: "Créditos por bloque de ECM", hint: "precio de cada bloque completo" },
      { key: "billing.ecm.block", label: "ECM por bloque facturable", hint: "ECM respondidas con OK (cwok) que forman un bloque" },
      { key: "billing.ecm.interval_seconds", label: "Segundos entre mediciones", hint: "mínimo 60; por defecto 900 (15 min)" },
      { key: "billing.ecm.suspend_on_debt", label: "Suspender líneas con consumo impagado (1/0)", hint: "la línea se suspende hasta que el propietario recargue" },
    ],
  },
  {
    title: "Avisos de caducidad",
    hint: "Recordatorios por email y/o Telegram antes de que caduque una línea.",
    fields: [
      { key: "notify.enabled", label: "Avisos activados (1/0)", hint: "interruptor maestro: sin esto no se envía nada" },
      { key: "notify.days_before", label: "Días de antelación por defecto", hint: "cada línea puede tener sus propios días" },
      { key: "notify.interval_seconds", label: "Segundos entre revisiones", hint: "mínimo 60; 3600 = cada hora" },
      { key: "notify.channel.email", label: "Enviar avisos por email (1/0)" },
      { key: "notify.smtp.host", label: "Servidor SMTP", hint: "p. ej. smtp.gmail.com" },
      { key: "notify.smtp.port", label: "Puerto SMTP", hint: "587 con STARTTLS (el 465 con SSL directo no está soportado)" },
      { key: "notify.smtp.user", label: "Usuario SMTP" },
      { key: "notify.smtp.password", label: "Contraseña SMTP", hint: "en Gmail, contraseña de aplicación" },
      { key: "notify.smtp.from", label: "Remitente de los avisos", hint: "p. ej. NCPanel <tucorreo@gmail.com>" },
      { key: "notify.smtp.starttls", label: "Usar STARTTLS (1/0)" },
      { key: "notify.channel.telegram", label: "Enviar avisos por Telegram (1/0)" },
      { key: "notify.telegram.bot_token", label: "Token del bot de Telegram", hint: "te lo da @BotFather" },
      { key: "notify.telegram.chat_id", label: "Chat de Telegram por defecto", hint: "tu id numérico (api.telegram.org/bot&lt;token&gt;/getUpdates)" },
    ],
  },
];

const SECRET_SETTINGS = ["panel.ncam_webif_password", "notify.smtp.password", "notify.telegram.bot_token"];
const GUIDE_URL = "https://github.com/TalaveraSama/Ncam_Fork/blob/main/docs/ajustes.md";

async function viewSettings(el) {
  const data = await api("/settings");
  const settingsField = ({ key, label, hint }) => `
    <label>${esc(label)}
      <input name="${esc(key)}" value="${esc(data.items[key] || "")}"${SECRET_SETTINGS.includes(key) ? ' type="password" autocomplete="new-password"' : ""}>
      <span class="hint">${esc(key)}${hint ? ` · ${esc(hint)}` : ""}</span>
    </label>`;
  const groups = SETTING_GROUPS.map((group) => {
    const fields = group.fields.filter(({ key }) => key in data.items || key.startsWith("panel."));
    if (!fields.length) return "";
    return `
      <div class="card">
        <h3>${esc(group.title)}</h3>
        <p class="hint">${esc(group.hint)}</p>
        <div class="grid two" style="margin-top:10px">${fields.map(settingsField).join("")}</div>
      </div>`;
  }).join("");

  el.innerHTML = `
    <form id="settings-form">
      ${groups}
      <div class="card">
        <div class="toolbar">
          <button class="btn primary" type="submit">Guardar ajustes</button>
          <a class="btn ghost" href="${GUIDE_URL}" target="_blank" rel="noopener">Guía de configuración</a>
        </div>
        <p class="hint">Los cambios se aplican al guardar. Los campos de contraseña muestran *** si ya hay un valor:
          solo cambian si escribes otro (vaciarlos los borra).</p>
      </div>
    </form>
    <div class="card">
      <h3>Mantenimiento</h3>
      <div class="toolbar">
        <button class="btn ghost" id="maint-snapshot">Guardar muestra de métricas</button>
        <button class="btn ghost" id="maint-purge">Purgar histórico (30 días)</button>
        <a class="btn ghost" href="${API}/cache/config/download?file=ncam.user" onclick="return ncamDownloadFile(event, 'ncam.user')">Descargar ncam.user</a>
        <a class="btn ghost" href="${API}/cache/config/download?file=ncam.server" onclick="return ncamDownloadFile(event, 'ncam.server')">Descargar ncam.server</a>
      </div>
      <p class="hint">El histórico se guarda automáticamente cada 60 s si NCam está accesible (se puede apagar con el
        muestreo automático, arriba). Los ficheros ncam.user / ncam.server se copian en /etc/ncam/ y se recargan con
        <strong>sudo restart-ncam</strong>. La base de datos (panel.db) es SQLite: no la edites con nano.</p>
    </div>`;

  $("#settings-form", el).onsubmit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.target).entries());
    // los campos de contraseña sin tocar llegan como ***: no se reenvían
    const filtered = Object.fromEntries(Object.entries(values).filter(([, value]) => value !== "***"));
    try {
      const result = await api("/settings", { method: "PATCH", body: { values: filtered } });
      toast(`Ajustes aplicados: ${Object.keys(result.applied).length}`);
      renderView();
    } catch (error) { toast(error.message, "error"); }
  };
  $("#maint-snapshot", el).onclick = async () => {
    const result = await api("/cache/stats/snapshot", { method: "POST" });
    toast(result.saved ? `Muestra guardada (${result.saved} métricas)` : `No se pudo guardar: ${result.detail}`,
      result.saved ? "ok" : "warn");
  };
  $("#maint-purge", el).onclick = async () => {
    if (await confirmDialog("Purga", "¿Eliminar el histórico de métricas y los intentos de login con más de 30 días?", "Purgar")) {
      const result = await api("/maintenance/purge?days=30", { method: "POST" });
      toast(`Eliminados ${result.snapshots_removed} registros de métricas`);
    }
  };
}

function ncamDownloadFile(event, filename) {
  event.preventDefault();
  fetch(event.currentTarget.href, { headers: { Authorization: `Bearer ${state.tokens.access}` } })
    .then((response) => response.blob())
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    });
  return false;
}
window.ncamDownloadFile = ncamDownloadFile;

/* ------------------------------------------------------------ renderizado */
const VIEWS = {
  dashboard: { title: "Panel", subtitle: "Resumen de líneas, cuentas y motor de caché", render: viewDashboard },
  lines: { title: "Líneas", subtitle: "Altas, renovaciones, credenciales y exportación", render: viewLines },
  accounts: { title: "Revendedores y usuarios", subtitle: "Jerarquía de cuentas, créditos y API keys", render: viewAccounts },
  cache: { title: "Caché y peers", subtitle: "Motor de caché NCam-NG y conexiones cacheex", render: viewCache },
  stats: { title: "Estadísticas", subtitle: "Métricas históricas y avisos de caducidad", render: viewStats },
  transactions: { title: "Créditos", subtitle: "Libro mayor de movimientos", render: viewTransactions },
  notifications: { title: "Avisos de caducidad", subtitle: "Recordatorios por email y Telegram", render: viewNotifications },
  usage: { title: "Consumo de ECM", subtitle: "Medición y facturación por bloques", render: viewUsage },
  audit: { title: "Auditoría", subtitle: "Registro de acciones sensibles", render: viewAudit },
  settings: { title: "Ajustes", subtitle: "Configuración global y mantenimiento", render: viewSettings },
};

async function renderView() {
  const config = VIEWS[state.view] || VIEWS.dashboard;
  $("#view-title").textContent = config.title;
  $("#view-subtitle").textContent = config.subtitle;
  const el = $("#view");
  el.innerHTML = `<p class="muted">Cargando…</p>`;
  try {
    await config.render(el);
  } catch (error) {
    if (error.message.includes("sesión")) return;
    el.innerHTML = `<div class="card"><h3>No se pudo cargar la vista</h3>
      <p class="muted small">${esc(error.message)}</p></div>`;
  }
}

async function refreshUser() {
  try {
    state.user = await api("/auth/me", { noRetry: true });
    paintUser();
  } catch (_) { /* se gestiona en api() */ }
}

function paintUser() {
  const roleLabels = { super_admin: "Super Admin", reseller: "Reseller", user: "Usuario" };
  $("#user-avatar").textContent = (state.user.username || "?").slice(0, 1).toUpperCase();
  $("#user-name").textContent = state.user.username;
  $("#user-role").textContent = roleLabels[state.user.role] || state.user.role;
  $("#user-credits").textContent = state.user.role === "super_admin"
    ? "Créditos ilimitados (administrador)"
    : `Saldo: ${fmtNumber(state.user.credits)} créditos`;
  $("#brand-sub").textContent = `v2 · ${roleLabels[state.user.role] || ""}`;
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  if (!state.user) {
    try { state.user = await api("/auth/me", { noRetry: true }); }
    catch (_) { logout(); return; }
  }
  state.settings = (await api("/settings").catch(() => ({ items: {} }))).items || {};
  state.meta = await api("/meta").catch(() => null);
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  paintUser();
  renderNav();
  navigate(state.view);
}

$("#login-form").addEventListener("submit", login);
$("#logout-btn").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST", body: { refresh_token: state.tokens.refresh } });
  } catch (_) { /* ignorado */ }
  logout();
});
$("#refresh-btn").addEventListener("click", () => renderView());

if (state.tokens.access || state.tokens.refresh) {
  boot().catch(() => logout());
}
