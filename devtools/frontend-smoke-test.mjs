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

console.log(failures.length ? `\n${failures.length} fallo(s)` : "\nfrontend OK");
process.exit(failures.length ? 1 : 0);
