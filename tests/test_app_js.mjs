/**
 * Tests hors navigateur de la logique JS du dashboard (filtres + groupement).
 * Exécute app.js dans un contexte Node avec un DOM factice minimal.
 *
 * Run:  node tests/test_app_js.mjs
 */
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const code = fs.readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");

const STATS = {
  offers: 0, scored: 0, qualified: 0, rejected: 0, jev_excluded: 0, errors: 0,
  avg_score: null, best_score: null, worst_score: null, distribution: [],
  criteria: [], gates: [], top_offers: [], jev_cost: 0, jev_input_tokens: 0, runs: 0,
};

function makeEl() {
  return {
    value: "", checked: true, textContent: "", innerHTML: "", dataset: {},
    addEventListener() {}, insertAdjacentHTML() {}, remove() {},
    querySelector: () => null, closest: () => null,
    scrollIntoView() {}, after() {},
  };
}

const sandbox = {
  document: {
    querySelector: () => makeEl(),
    getElementById: () => null,
    addEventListener() {},
    createElement: () => makeEl(),
  },
  fetch: async (url) => ({
    ok: true,
    json: async () => (String(url).includes("/api/stats") ? STATS
      : String(url).includes("/api/history") ? { runs: [] } : { offers: [] }),
  }),
  console, setTimeout, clearInterval, setInterval: () => 0,
};
vm.createContext(sandbox);
const { filterOffers, groupOffersByLot, cvJobStatus } = vm.runInContext(
  `${code}\n;({ filterOffers, groupOffersByLot, cvJobStatus })`, sandbox);

const OFFERS = [
  { run_id: "lotB", evaluated_at: "2026-09-23T10:00:00", title: "Ingénieur sécurité réseaux",
    company: "SG", location: "Paris", status: "rejected", score: 61.8, minimum_global_score: 68,
    blocking_criteria: ["junior_fit"], gate_failures: [] },
  { run_id: "lotA", evaluated_at: "2026-09-22T09:00:00", title: "Admin systèmes",
    company: "DGSI", location: "Levallois", status: "qualified", score: 74.0, minimum_global_score: 68,
    blocking_criteria: [], gate_failures: [] },
  { run_id: "lotA", evaluated_at: "2026-09-22T09:00:00", title: "Stage cyber",
    company: "Hellowork", location: "Toulouse", status: "rejected", score: 68.6, minimum_global_score: 68,
    blocking_criteria: ["junior_fit"], gate_failures: ["contract_type"] },
  { run_id: "lotA", evaluated_at: "2026-09-22T09:00:00", title: "Page JS vide",
    company: "—", location: "—", status: "error", minimum_global_score: 68,
    blocking_criteria: [], gate_failures: ["freshness"] },
];

const opts = (over = {}) => ({ query: "", status: "", score: "", ...over });
/* les tableaux renvoyés appartiennent au contexte vm : on compare des chaînes */
const titles = (rows) => Array.from(rows, (o) => o.title).join(" | ");
const keys = (groups) => Array.from(groups, (g) => g.run_id).join(" | ");
let passed = 0;
function check(name, fn) { fn(); passed++; console.log("ok  ", name); }

check("filtre score ≥ seuil ne garde que les offres au-dessus", () => {
  const rows = filterOffers(OFFERS, opts({ score: "above" }));
  assert.equal(titles(rows), "Admin systèmes | Stage cyber");
});

check("filtre score sous le seuil", () => {
  const rows = filterOffers(OFFERS, opts({ score: "below" }));
  assert.equal(titles(rows), "Ingénieur sécurité réseaux");
});

check("filtre sans score = échec technique, et il est bien non vide", () => {
  const rows = filterOffers(OFFERS, opts({ score: "unscored" }));
  assert.equal(titles(rows), "Page JS vide");
});

check("les deux filtres score sont complémentaires", () => {
  const scored = filterOffers(OFFERS, opts({ score: "scored" }));
  const unscored = filterOffers(OFFERS, opts({ score: "unscored" }));
  assert.equal(Array.from(scored).length + Array.from(unscored).length, OFFERS.length);
});

check("filtre statut", () => {
  assert.equal(titles(filterOffers(OFFERS, opts({ status: "qualified" }))), "Admin systèmes");
});

check("recherche plein texte sur titre, entreprise, critère bloquant", () => {
  assert.equal(filterOffers(OFFERS, opts({ query: "dgsI" })).length, 1);
  assert.equal(filterOffers(OFFERS, opts({ query: "junior_fit" })).length, 2);
  assert.equal(filterOffers(OFFERS, opts({ query: "contract_type" })).length, 1);
  assert.equal(filterOffers(OFFERS, opts({ query: "aucun resultat" })).length, 0);
});

check("filtres combinés", () => {
  const rows = filterOffers(OFFERS, opts({ status: "rejected", query: "stage", score: "above" }));
  assert.equal(titles(rows), "Stage cyber");
});

check("groupement par lot : tous les lots, offres conservées, lots récents d'abord", () => {
  const groups = groupOffersByLot(OFFERS);
  assert.equal(Array.from(groups).length, 2);
  assert.equal(keys(groups), "lotB | lotA");
  assert.equal(Array.from(groups)[1].offers.length, 3);
  const total = Array.from(groups).reduce((sum, g) => sum + Array.from(g.offers).length, 0);
  assert.equal(total, OFFERS.length);
});

check("groupement d'une liste vide", () => {
  assert.equal(Array.from(groupOffersByLot([])).length, 0);
});

check("le groupement respecte les filtres appliqués avant", () => {
  const filtered = filterOffers(OFFERS, opts({ score: "above" }));
  const groups = groupOffersByLot(filtered);
  /* les deux offres au-dessus du seuil viennent du même lot */
  assert.equal(keys(groups), "lotA");
  assert.equal(Array.from(groups).reduce((s, g) => s + Array.from(g.offers).length, 0), 2);
});

check("le suivi CV distingue en cours, prêt et échec", () => {
  assert.equal(cvJobStatus({ status: "running" }), "Génération en cours…");
  assert.equal(cvJobStatus({ status: "done" }), "PDF prêt");
  assert.equal(cvJobStatus({ status: "failed" }), "Échec");
});

console.log(`\n${passed} tests JS OK`);
