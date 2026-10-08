// Prueba de humo del frontend de NCPanel (jsdom): carga index.html + app.js,
// simula la API y comprueba que la pantalla de Ajustes se dibuja bien, que los
// campos están etiquetados y que las contraseñas enmascaradas no se reenvían.
//
// Uso:  node devtools/frontend-smoke-test.mjs     (necesita jsdom)
//       o devtools/run-frontend-tests.sh           (instala jsdom y lo ejecuta)
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// jsdom puede estar instalado en una carpeta temporal (devtools/run-frontend-tests.sh);
// en ese caso se resuelve desde ahí en vez de exigir node_modules en el repo.
const resolveFrom = process.env.NCAM_NG_JSDOM_DIR
  ? join(process.env.NCAM_NG_JSDOM_DIR, "package.json")
  : import.meta.url;
const { JSDOM } = createRequire(resolveFrom)("jsdom");

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PANEL = join(ROOT, "panel/frontend");

const settings = {
  "panel.name": "NCPanel",
  "panel.public_host": "cam.midominio.tv",
  "panel.port.cccam": "12000",
  "panel.port.newcamd": "50000",
  "panel.port.camd35": "33333",
  "panel.port.cacheex": "8181",
  "panel.ncam_webif_url": "http://127.0.0.1:8181",
  "panel.ncam_webif_user": "admin",
  "panel.ncam_webif_password": "***",
  "ncam.cache.max_time": "15",
  "ncam.cache.max_entries": "0",
  "ncam.cache.cacheex_enable": "1",
  "ncam.cache.panel_poll": "1",
  "billing.currency": "créditos",
  "billing.line_cost": "10",
  "billing.renew_cost": "10",
  "billing.ecm.enabled": "0",
  "billing.ecm.price": "10",
  "billing.ecm.block": "1000",
  "billing.ecm.interval_seconds": "900",
  "billing.ecm.suspend_on_debt": "0",
  "notify.enabled": "1",
  "notify.days_before": "3",
  "notify.interval_seconds": "3600",
  "notify.channel.email": "1",
  "notify.smtp.host": "smtp.gmail.com",
  "notify.smtp.port": "587",
  "notify.smtp.user": "tucorreo@gmail.com",
  "notify.smtp.password": "***",
  "notify.smtp.from": "NCPanel <tucorreo@gmail.com>",
  "notify.smtp.starttls": "1",
  "notify.channel.telegram": "0",
  "notify.telegram.bot_token": "",
  "notify.telegram.chat_id": "",
};

const responses = {
  "/api/v1/settings": { items: settings, editable: Object.keys(settings) },
  "/api/v1/meta": { panel_version: "2.2.1", roles: ["super_admin"], features: [] },
};

// La lista de campos imita la tabla de ajustes por defecto (app/db.py): si se
// añade un ajuste nuevo, actualízala aquí.
const dom = new JSDOM(readFileSync(`${PANEL}/index.html`, "utf8"), {
  url: "http://localhost:8080/",
  runScripts: "dangerously",
  pretendToBeVisual: true,
});
const { window } = dom;

window.fetch = async (url) => {
  const path = String(url).replace(/^https?:\/\/[^/]+/, "").split("?")[0];
  const body = responses[path] ?? {};
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
};
window.alert = () => {};
window.confirm = () => true;

const failures = [];
const check = (name, condition) => {
  if (!condition) failures.push(name);
  console.log(`${condition ? "ok  " : "FALLO"} ${name}`);
};

const script = window.document.createElement("script");
script.textContent = readFileSync(`${PANEL}/static/app.js`, "utf8");
window.document.body.appendChild(script);

await window.eval(`(async () => {
  state.user = { username: "admin", role: "super_admin", credits: 0 };
  state.tokens = { access: "tok", refresh: "tok" };
  state.view = "settings";
  await renderView();
})()`);

const doc = window.document;
const html = doc.querySelector("#view").innerHTML;
check("la vista de Ajustes se dibuja", html.length > 500);
for (const label of [
  "Nombre del panel",
  "Host público",
  "URL del WebIf",
  "max_entries (entradas)",
  "Muestreo automático (1/0)",
  "Coste por renovación (créditos)",
  "ECM por bloque facturable",
  "Servidor SMTP",
  "Token del bot de Telegram",
]) {
  check(`campo «${label}»`, html.includes(label));
}
check("las claves internas se muestran como ayuda", html.includes("panel.port.cccam"));
check("las secciones están agrupadas", html.includes("Créditos y facturación") && html.includes("Avisos de caducidad"));
check("enlace a la guía", html.includes("docs/ajustes.md"));
check("mantenimiento intacto", html.includes("Purgar histórico") && html.includes("ncam.user"));
check("el valor público se muestra", html.includes('value="cam.midominio.tv"'));
check("el número de campos por sección es correcto", doc.querySelectorAll("#settings-form input").length === Object.keys(settings).length);
check("solo 3 campos son de contraseña", doc.querySelectorAll('#settings-form input[type="password"]').length === 3);
check("la contraseña del WebIf llega enmascarada", doc.querySelector('input[name="panel.ncam_webif_password"]').value === "***");

// al enviar, los *** no se reenvían y el resto sí
let sent = null;
window.fetch = async (url, options = {}) => {
  sent = JSON.parse(options.body);
  return {
    ok: true, status: 200, headers: { get: () => "application/json" },
    json: async () => ({ applied: sent.values, rejected: [] }), text: async () => "{}",
  };
};
doc.querySelector("#settings-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await new Promise((resolve) => setTimeout(resolve, 100));
check("los campos enmascarados no se envían", sent !== null && !("panel.ncam_webif_password" in sent.values));
check("los campos normales sí se envían", sent !== null && sent.values["panel.port.cccam"] === "12000");

// --- formulario de línea: permiso por CAID ---------------------------------
await window.eval(`(async () => {
  state.user = { username: "admin", role: "super_admin", credits: 0 };
  await openLineForm([], async () => {}, null);
})()`);
const formHTML = doc.querySelector("#modal-root").innerHTML;
check("el formulario de línea tiene el campo de CAIDs", formHTML.includes('name="caid_allow"'));
check("tiene botones rápidos de CAID", (formHTML.match(/data-caid=/g) || []).length === 4);
check("tiene el campo de saltos CCcam", formHTML.includes('name="cccmaxhops"'));
const modalForm = doc.querySelector("#modal-root form");
const caidInput = doc.querySelector("#line-caid");
doc.querySelector('#modal-root button[data-caid="1801"]').click();
doc.querySelector('#modal-root button[data-caid="0B00"]').click();
check("los botones rápidos añaden CAID", caidInput.value === "1801,0B00");
doc.querySelector('#modal-root button[data-caid="1801"]').click();
check("volver a pulsar lo quita", caidInput.value === "0B00");
doc.querySelector('#modal-root button[data-caid=""]').click();
check("el botón Todos vacía el campo", caidInput.value === "");

// el formulario se envía con el caid_allow
let sentLine = null;
window.fetch = async (url, options = {}) => {
  sentLine = JSON.parse(options.body);
  return {
    ok: true, status: 201, headers: { get: () => "application/json" },
    json: async () => ({ id: 1, username: "nuevo" }), text: async () => "{}",
  };
};
caidInput.value = "1801,1861";
modalForm.querySelector('input[name="name"]').value = "Cliente de prueba";
modalForm.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await new Promise((resolve) => setTimeout(resolve, 100));
check("el alta envía caid_allow", sentLine !== null && sentLine.caid_allow === "1801,1861");

// --- alta de cuentas: se pueden crear más administradores -------------------
await window.eval(`(async () => {
  state.user = { username: "admin", role: "super_admin", credits: 0 };
  await openAccountForm(async () => {}, null);
})()`);
const accountForm = doc.querySelector("#modal-root").innerHTML;
check("el alta de cuentas ofrece el rol administrador", accountForm.includes('value="super_admin"'));
check("el alta explica qué puede un administrador", accountForm.includes("control total del panel"));

let sentAccount = null;
window.fetch = async (url, options = {}) => {
  sentAccount = JSON.parse(options.body);
  return {
    ok: true, status: 201, headers: { get: () => "application/json" },
    json: async () => ({ id: 9, username: "ana" }), text: async () => "{}",
  };
};
const accountModalForm = doc.querySelector("#modal-root form");
accountModalForm.querySelector('input[name="username"]').value = "ana";
accountModalForm.querySelector('input[name="password"]').value = "ClaveSegura!23";
accountModalForm.querySelector('select[name="role"]').value = "super_admin";
accountModalForm.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await new Promise((resolve) => setTimeout(resolve, 100));
check("el alta de un administrador envía role=super_admin",
  sentAccount !== null && sentAccount.role === "super_admin" && sentAccount.username === "ana");

// en edición: el rol se puede cambiar, salvo el de uno mismo (deshabilitado)
await window.eval(`(async () => {
  state.user = { id: 1, username: "admin", role: "super_admin", credits: 0 };
  await openAccountForm(async () => {}, { id: 5, username: "luis", role: "reseller", credits: 0, max_lines: 0 });
})()`);
const editForm = doc.querySelector("#modal-root").innerHTML;
check("la edición permite cambiar el rol", editForm.includes('name="role"') && editForm.includes("Revendedor"));

await window.eval(`(async () => {
  state.user = { id: 1, username: "admin", role: "super_admin", credits: 0 };
  await openAccountForm(async () => {}, { id: 1, username: "admin", role: "super_admin", credits: 0, max_lines: 0 });
})()`);
const selfForm = doc.querySelector("#modal-root").innerHTML;
check("no se puede cambiar el rol propio",
  /name="role"[^>]*disabled/.test(selfForm) && selfForm.includes("No puede cambiarse el rol a sí mismo"));

// --- vista de caché: un clic en «Probar» envía una sola petición -------------
// (regresión: viewCache añadía un listener nuevo en cada pintado sobre el
// mismo contenedor, así que un clic disparaba tantas peticiones como veces
// se había visitado la vista, con la cascada de «Error 500» correspondiente)
const cacheStats = {
  reachable: true, engine: "NCam-NG cache engine", hit_ratio: 83.4, lookups: 10,
  entries: 5, cw_entries: 6, mem_bytes: 1024, history: [], hot_entries: [],
  peers: { total: 1, online: 1 },
};
const cacheServers = { items: [{
  id: 1, name: "Peer 1", host: "127.0.0.1", port: 12000, protocol: "cccam",
  owner_username: "admin", priority: 0, enabled: 1, last_check_at: null,
  last_check_ok: null, last_check_ms: null, last_check_error: null,
}] };
const cacheLimits = { max_time: 15, max_entries: 0, cacheex_enabled: true };
let testPosts = 0;
let restartPosts = 0;
const daemonStatus = {
  reachable: true, version: "NCam-NG 2.5", revision: "33", uptime: "00d 01:23:45",
  totals: { connected: 1, users: 2, ecm_ok: 10, ecm_nok: 1, from_cache: 4 },
  cache_engine: "NCam-NG cache engine", error: null,
};
window.fetch = async (url, options = {}) => {
  const path = String(url).replace(/^https?:\/\/[^/]+/, "").split("?")[0];
  if ((options.method || "GET") === "POST" && path === "/api/v1/cache/servers/1/test") testPosts += 1;
  if ((options.method || "GET") === "POST" && path === "/api/v1/daemon/restart") restartPosts += 1;
  const bodies = {
    "/api/v1/cache/stats": cacheStats,
    "/api/v1/cache/servers": cacheServers,
    "/api/v1/cache/limits": cacheLimits,
    "/api/v1/cache/servers/1/test": { id: 1, host: "127.0.0.1", port: 12000, ok: true, latency_ms: 34, error: null },
    "/api/v1/daemon/status": daemonStatus,
    "/api/v1/daemon/restart": { ok: true, message: "Orden enviada" },
  };
  const body = bodies[path] ?? {};
  return {
    ok: true, status: 200, headers: { get: () => "application/json" },
    json: async () => body, text: async () => JSON.stringify(body),
  };
};
await window.eval(`(async () => {
  state.user = { username: "admin", role: "super_admin", credits: 0 };
  state.tokens = { access: "tok", refresh: "tok" };
  state.view = "cache";
  await renderView();
  await renderView();
})()`);
check("la vista de caché se dibuja", doc.querySelectorAll('#view button[data-peer="test"]').length === 1);
check("el super admin ve el botón Aplicar en cada peer",
  doc.querySelectorAll('#view button[data-peer="apply"]').length === 1);
check("el super admin ve Guardar y aplicar en los ajustes del motor",
  doc.querySelector("#view #limits-apply") !== null);
doc.querySelector('#view button[data-peer="test"]').click();
await new Promise((resolve) => setTimeout(resolve, 300));
check("un clic en Probar envía una sola petición aunque se pintó dos veces", testPosts === 1);

// --- vista del daemon: estado + reinicio con confirmación --------------------
await window.eval(`(async () => {
  state.view = "daemon";
  await renderView();
})()`);
check("la vista del daemon muestra el estado",
  doc.querySelector("#view").innerHTML.includes("En línea")
  && doc.querySelector("#view #daemon-restart") !== null);
doc.querySelector("#view #daemon-restart").click();
await new Promise((resolve) => setTimeout(resolve, 100));
check("reiniciar pide confirmación", doc.querySelector("#modal-root [data-ok]") !== null);
doc.querySelector("#modal-root [data-ok]").click();
await new Promise((resolve) => setTimeout(resolve, 300));
check("confirmar el reinicio envía una petición al daemon", restartPosts === 1);

console.log(failures.length ? `\n${failures.length} fallo(s)` : "\nfrontend OK");
process.exit(failures.length ? 1 : 0);
