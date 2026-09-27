/** Offline tests for shared UI visuals and pagination. */
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const code = fs.readFileSync(new URL("../app/static/common.js", import.meta.url), "utf8");
const elements = new Map();
function makeEl() {
  return {
    textContent: "", innerHTML: "", className: "", children: [], value: "",
    classList: { toggle() {}, add() {}, remove() {} },
    append(...children) { this.children.push(...children); },
    get firstChild() { return this.children[0] || null; },
    removeChild(child) { this.children = this.children.filter((item) => item !== child); },
    setAttribute(name, value) { this[name] = value; },
    addEventListener() {}, focus() {}, select() {}, remove() {},
  };
}
const sandbox = {
  window: {},
  document: {
    querySelector(selector) { return elements.get(selector) || null; },
    querySelectorAll() { return []; },
    createElement() { return makeEl(); },
    dispatchEvent() {},
  },
  fetch: async (url) => ({ ok: true, json: async () =>
    String(url).includes("/api/history")
      ? { total: 0, runs: [] }
      : { total: 0, jobs: [] } }),
  CustomEvent: class CustomEvent {},
  URL, URLSearchParams,
  history: { replaceState() {}, pushState() {} },
  location: { href: "https://app.test/offers" },
  setTimeout: () => 0, setInterval: () => 0, clearInterval() {},
  console,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const { escapeHtml, scoreVisual, criteriaVisual, paginationHtml, statusBadge,
  applicationStatusBadge } = sandbox.JEV;
let passed = 0;
function check(name, callback) { callback(); passed++; console.log("ok  ", name); }
async function checkAsync(name, callback) { await callback(); passed++; console.log("ok  ", name); }

check("le score visuel affiche valeur, barre et seuil", () => {
  const html = scoreVisual(74.2, 68, true);
  assert.match(html, /74\.2/);
  assert.match(html, /width:74\.2%/);
  assert.match(html, /left:68%/);
  assert.match(html, /seuil 68/);
  assert.match(html, /pass/);
});

check("un score sous le seuil est explicitement en échec", () => {
  const html = scoreVisual(61, 68);
  assert.match(html, /fail/);
  assert.match(html, /Score 61\.0 sur 100, seuil 68/);
});

check("un score absent n'est pas transformé en zéro", () => {
  const html = scoreVisual(null, 68);
  assert.match(html, /sans score/);
  assert.doesNotMatch(html, />0\.0</);
});

check("les mini-visuels de critères ont une légende textuelle", () => {
  const html = criteriaVisual([
    { id: "skills", name: "Compétences", score: 80, confidence: .9, required: true, passed: true },
    { id: "experience", name: "Expérience", score: 40, confidence: .8, required: true, passed: false },
  ], .5);
  assert.match(html, /criterion-dot ok/);
  assert.match(html, /criterion-dot bad/);
  assert.match(html, /1 bloquant/);
  assert.match(html, /Compétences : 80\.0\/100/);
});

check("la pagination borne la fenêtre autour de la page courante", () => {
  const html = paginationHtml(6, 12);
  assert.match(html, /data-page="4"/);
  assert.match(html, /data-page="8"/);
  assert.match(html, /data-page="12"/);
  assert.match(html, /class="active">6/);
});

check("les badges ont toujours un texte en plus de la couleur", () => {
  assert.match(statusBadge("qualified"), /Qualifiée/);
  assert.match(statusBadge("error"), /Erreur technique/);
});

check("les statuts de candidature ont un libellé explicite", () => {
  assert.match(applicationStatusBadge("to_review"), /À étudier/);
  assert.match(applicationStatusBadge("applied"), /Candidature envoyée/);
  assert.match(applicationStatusBadge("offer"), /Offre reçue/);
});

check("les valeurs injectées sont échappées", () => {
  assert.equal(escapeHtml('<script>"x"</script>'), "&lt;script&gt;&quot;x&quot;&lt;/script&gt;");
});

const adminResult = makeEl();
elements.set("#invite_result", adminResult);
const adminCode = fs.readFileSync(new URL("../app/static/admin.js", import.meta.url), "utf8");
sandbox.navigator = { clipboard: { writeText: async () => {} } };
vm.runInContext(adminCode, sandbox);

check("les dates invalides de l’administration restent lisibles", () => {
  assert.equal(sandbox.JEVAdmin.formatAdminDate("date-invalide"), "date-invalide");
  assert.equal(sandbox.JEVAdmin.formatAdminDate(""), "—");
});

check("le résultat d’invitation n’injecte pas de HTML", () => {
  sandbox.JEVAdmin.renderInviteResult({
    url: 'https://app.test/register?token=<script>',
    email_error: '<img src=x onerror=alert(1)>',
    email_sent: false,
  }, true);
  const copy = adminResult.children[0];
  assert.equal(copy.children[1].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(copy.children[2].value, 'https://app.test/register?token=<script>');
  assert.equal(adminResult.innerHTML, "");
});

check("la confirmation de suppression avertit sur les fichiers et les sauvegardes", () => {
  const message = sandbox.JEVAdmin.deleteConfirmationText("bob");
  assert.match(message, /CV, candidatures et fichiers actuels seront effacés/);
  assert.match(message, /sauvegardes existantes resteront inchangées/);
  assert.match(message, /exactement bob/);
});

await checkAsync("la suppression envoie une confirmation JSON exacte", async () => {
  let request = null;
  sandbox.fetch = async (url, options) => {
    request = {url, options};
    return {ok: true, json: async () => ({
      deleted: "bob-id", username: "bob", cleanup_pending: false,
    })};
  };
  const result = await sandbox.JEVAdmin.deleteUser("bob/id", "bob");
  assert.equal(request.url, "/api/admin/users/bob%2Fid");
  assert.equal(request.options.method, "DELETE");
  assert.equal(request.options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(request.options.body), {confirmation: "bob"});
  assert.equal(result.deleted, "bob-id");
});

const setupForm = makeEl();
setupForm.dataset = { processing: "false", apiKeySet: "true", error: "" };
const setupButton = makeEl();
setupButton.disabled = false;
const setupStatus = makeEl();
const setupFile = makeEl();
setupFile.files = [];
const setupElements = new Map([
  ["#setup_form", setupForm],
  ["#setup_submit", setupButton],
  ["#setup_status", setupStatus],
  ["#cv_pdf", setupFile],
]);
let setupReloads = 0;
let setupSchedules = 0;
const setupSandbox = {
  window: {},
  document: { querySelector(selector) { return setupElements.get(selector) || null; } },
  fetch: async () => ({ ok: true, json: async () => ({ needed: true, processing: true }) }),
  location: { reload() { setupReloads++; } },
  setTimeout: () => { setupSchedules++; return setupSchedules; },
  clearTimeout() {},
  console,
};
setupSandbox.window = setupSandbox;
vm.createContext(setupSandbox);
const setupCode = fs.readFileSync(new URL("../app/static/setup.js", import.meta.url), "utf8");
vm.runInContext(setupCode, setupSandbox);

check("l’onboarding en cours désactive le formulaire après actualisation", () => {
  const state = setupSandbox.JEVSetup.renderOnboarding({
    needed: true, processing: true, api_key_set: true, job: { status: "running" },
  });
  assert.equal(state, "running");
  assert.equal(setupButton.disabled, true);
  assert.match(setupStatus.textContent, /Analyse du CV en cours/);
});

check("un onboarding interrompu affiche l’erreur et autorise une relance", () => {
  const state = setupSandbox.JEVSetup.renderOnboarding({
    needed: true,
    processing: false,
    api_key_set: true,
    job: { status: "interrupted", last_error: "Analyse interrompue" },
  });
  assert.equal(state, "interrupted");
  assert.equal(setupButton.disabled, false);
  assert.equal(setupStatus.textContent, "Erreur : Analyse interrompue");
  assert.equal(setupSandbox.JEVSetup.detailMessage({ message: "Déjà en cours" }), "Déjà en cours");
});

check("la fin de l’onboarding recharge automatiquement l’application", () => {
  const state = setupSandbox.JEVSetup.renderOnboarding({ needed: false, processing: false });
  assert.equal(state, "done");
  assert.equal(setupReloads, 1);
});

await checkAsync("le polling terminé recharge sans programmer une nouvelle vérification", async () => {
  setupSandbox.fetch = async () => ({
    ok: true,
    json: async () => ({ needed: false, processing: false, api_key_set: true, job: { status: "done" } }),
  });
  const schedulesBefore = setupSchedules;
  await setupSandbox.JEVSetup.pollOnboarding();
  assert.equal(setupSchedules, schedulesBefore);
  assert.equal(setupReloads, 2);
});

await checkAsync("le polling s’arrête après dix erreurs consécutives", async () => {
  setupSandbox.fetch = async () => { throw new Error("indisponible"); };
  const schedulesBefore = setupSchedules;
  for (let attempt = 0; attempt < 9; attempt++) {
    await setupSandbox.JEVSetup.pollOnboarding();
  }
  assert.equal(setupSchedules, schedulesBefore + 9);
  await setupSandbox.JEVSetup.pollOnboarding();
  assert.equal(setupSchedules, schedulesBefore + 9);
  assert.match(setupStatus.textContent, /Actualisez la page/);
  assert.equal(setupButton.disabled, true);
});

console.log(`\n${passed} tests JS OK`);
