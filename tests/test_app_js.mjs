/** Offline tests for shared UI visuals and pagination. */
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const code = fs.readFileSync(new URL("../app/static/common.js", import.meta.url), "utf8");
const elements = new Map();
function makeEl() {
  return {
    textContent: "", innerHTML: "", className: "", children: [],
    classList: { toggle() {}, add() {}, remove() {} },
    append(child) { this.children.push(child); }, remove() {},
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
const { escapeHtml, scoreVisual, criteriaVisual, paginationHtml, statusBadge } = sandbox.JEV;
let passed = 0;
function check(name, callback) { callback(); passed++; console.log("ok  ", name); }

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

check("les valeurs injectées sont échappées", () => {
  assert.equal(escapeHtml('<script>"x"</script>'), "&lt;script&gt;&quot;x&quot;&lt;/script&gt;");
});

console.log(`\n${passed} tests JS OK`);
