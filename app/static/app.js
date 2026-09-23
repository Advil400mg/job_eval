const $ = (sel) => document.querySelector(sel);
let poller = null;
let offersCache = [];
let cvJobsCache = [];
const cvPollers = {};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const num = (v, digits = 1) => (typeof v === "number" ? v.toFixed(digits) : "—");
const scoreClass = (score, threshold) =>
  score === null || score === undefined ? "na" : (score >= (threshold ?? 68) ? "hi" : "lo");

/* ------------------------------------------------------------------ évaluation */

async function startRun() {
  const raw = $("#urls").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!raw.length) { $("#status").textContent = "Collez au moins une URL."; return; }
  $("#run").disabled = true;
  $("#status").textContent = "Envoi…";
  try {
    const res = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: raw }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erreur");
    pollRun(data.run_id);
  } catch (err) {
    $("#status").textContent = "Erreur : " + err.message;
    $("#run").disabled = false;
  }
}

function pollRun(runId) {
  if (poller) clearInterval(poller);
  const tick = async () => {
    const res = await fetch(`/api/runs/${runId}`);
    if (!res.ok) { $("#status").textContent = "Lot introuvable"; clearInterval(poller); return; }
    const run = await res.json();
    $("#status").textContent = `${run.progress}/${run.total} offres traitées…`;
    renderRun(run);
    if (run.status !== "running") {
      clearInterval(poller); poller = null;
      $("#run").disabled = false;
      $("#status").textContent = `Terminé — ${run.progress}/${run.total} offres.`;
      loadDashboard();
    }
  };
  tick();
  poller = setInterval(tick, 1500);
}

/* ------------------------------------------------------------------ dashboard */

function kpi(label, value, cls = "", hint = "") {
  return `<div class="kpi ${cls}"><span class="kpi-value">${value}</span>
    <span class="kpi-label">${escapeHtml(label)}</span>
    ${hint ? `<span class="muted">${escapeHtml(hint)}</span>` : ""}</div>`;
}

function renderKpis(stats) {
  $("#kpis").innerHTML = [
    kpi("Offres évaluées", stats.scored ?? 0, "", `${stats.runs} lot(s) — ${stats.offers} entrées stockées`),
    kpi("Qualifiées", stats.qualified ?? 0, stats.qualified ? "good" : ""),
    kpi("Refusées Jev", stats.rejected ?? 0, stats.rejected ? "bad" : ""),
    kpi("Validées Jev mais exclues", stats.jev_excluded ?? 0, stats.jev_excluded ? "warn" : ""),
    kpi("Échecs techniques", stats.errors ?? 0),
    kpi("Score moyen", num(stats.avg_score), "",
        `meilleur ${num(stats.best_score)} — pire ${num(stats.worst_score)}`),
    kpi("Coût Jev cumulé", "$" + (stats.jev_cost ?? 0).toFixed(4), "",
        `${(stats.jev_input_tokens || 0).toLocaleString("fr-FR")} tokens d'entrée`),
  ].join("");
}

function renderDistribution(stats) {
  const max = Math.max(1, ...stats.distribution.map((b) => b.count));
  $("#distribution").innerHTML = stats.distribution.map((b) => `
    <div class="distrow">
      <span class="distlabel">${escapeHtml(b.bucket)}</span>
      <div class="distbar ${parseInt(b.bucket, 10) >= 68 ? "hi" : "lo"}"
           style="width:${Math.round((b.count / max) * 100)}%"></div>
      <span class="muted">${b.count}</span>
    </div>`).join("");
}

function renderGates(stats) {
  if (!stats.gates.length) { $("#gates").innerHTML = '<p class="muted">Aucune donnée.</p>'; return; }
  $("#gates").innerHTML = `<table class="tbl">
    <thead><tr><th>Porte</th><th>OK</th><th>Échec</th><th>Réserve</th><th>Inconnu</th><th>Motif d'échec fréquent</th></tr></thead>
    <tbody>${stats.gates.map((g) => {
      const reasons = Object.entries(g.reasons || {}).sort((a, b) => b[1] - a[1]);
      const top = reasons.length
        ? `${escapeHtml(reasons[0][0])} <span class="muted">(×${reasons[0][1]})</span>` : "—";
      return `<tr><td><code>${escapeHtml(g.gate)}</code></td>
        <td class="num">${g.pass || 0}</td>
        <td class="num ${g.fail ? "bad-text" : ""}">${g.fail || 0}</td>
        <td class="num">${g.warn || 0}</td>
        <td class="num">${g.unknown || 0}</td>
        <td class="muted">${top}</td></tr>`;
    }).join("")}</tbody></table>`;
}

function renderCriteriaStats(stats) {
  if (!stats.criteria.length) {
    $("#criteria_stats").innerHTML = '<p class="muted">Aucune donnée.</p>';
    return;
  }
  $("#criteria_stats").innerHTML = `<table class="tbl">
    <thead><tr><th>Critère</th><th>Poids</th><th>Obligatoire</th><th>Évalué</th>
      <th>Score moyen</th><th>Confiance moy.</th><th>Bloque</th><th>Sous le seuil de confiance</th><th></th></tr></thead>
    <tbody>${stats.criteria.map((c) => `
      <tr>
        <td><code>${escapeHtml(c.id)}</code><div class="muted">${escapeHtml(c.name)}</div></td>
        <td class="num">${c.weight ?? "—"}</td>
        <td>${c.required ? `oui <span class="muted">≥ ${c.min_score}</span>` : "non"}</td>
        <td class="num">${c.evaluated}</td>
        <td class="num ${scoreClass(c.avg_score, c.min_score ?? 68)}-text">${num(c.avg_score)}</td>
        <td class="num">${num(c.avg_confidence, 2)}</td>
        <td class="num ${c.blocking ? "bad-text" : ""}">${c.blocking}
          ${c.blocking_share !== null ? `<span class="muted">(${num(c.blocking_share)} %)</span>` : ""}</td>
        <td class="num">${c.low_confidence}</td>
        <td class="bar"><span style="width:${Math.max(0, Math.min(100, c.avg_score ?? 0))}%"></span></td>
      </tr>`).join("")}</tbody></table>`;
}

/* ------------------------------------------------------------------ historique */

function renderHistory(history) {
  if (!history.runs.length) {
    $("#history").innerHTML = '<p class="muted">Aucun lot enregistré.</p>';
    return;
  }
  $("#history").innerHTML = `<table class="tbl">
    <thead><tr><th>Quand</th><th>Offres</th><th>Meilleur</th><th>Moyenne</th>
      <th>Qualifiées</th><th>Refusées</th><th>Exclues</th><th>Portes en échec</th>
      <th>Meilleure offre</th><th></th></tr></thead>
    <tbody>${history.runs.map((r) => `
      <tr>
        <td>${escapeHtml(r.created_at).replace("T", " ")}
          <div class="muted">${escapeHtml(r.status)}${r.status === "running" ? ` ${r.progress}/${r.total}` : ""}</div></td>
        <td class="num">${r.offers}</td>
        <td class="num ${scoreClass(r.best_score)}-text">${num(r.best_score)}</td>
        <td class="num">${num(r.avg_score)}</td>
        <td class="num">${r.qualified}</td>
        <td class="num">${r.rejected}</td>
        <td class="num">${r.jev_excluded}</td>
        <td class="num ${r.gate_failures ? "bad-text" : ""}">${r.gate_failures}</td>
        <td>${r.top.length ? `${escapeHtml(r.top[0].title || r.top[0].url).slice(0, 62)}
          <div class="muted">${escapeHtml(r.top[0].company || "—")} — ${num(r.top[0].score)}/100</div>` : "—"}</td>
        <td class="nowrap">
          <button class="mini" data-expand-run="${r.id}">offres ▾</button>
          <button class="mini" data-run="${r.id}">détail</button>
          <a class="mini" href="/api/runs/${r.id}/export?fmt=json">json</a>
          <a class="mini" href="/api/runs/${r.id}/export?fmt=csv">csv</a>
        </td>
      </tr>`).join("")}</tbody></table>`;
}

/* Déplie un lot dans l'historique pour voir ses offres groupées. */
async function toggleRunRow(runId, button) {
  const existing = document.getElementById(`exp-${runId}`);
  if (existing) {
    existing.remove();
    button.textContent = "offres ▾";
    return;
  }
  button.textContent = "chargement…";
  const run = await fetch(`/api/runs/${runId}`).then((r) => r.json());
  const head = document.querySelector(`[data-expand-run="${runId}"]`).closest("tr");
  const scores = (run.results || []).map((i) => (i.jev || {}).global_score)
    .filter((s) => typeof s === "number");
  const best = scores.length ? Math.max(...scores) : null;
  const rows = [...(run.results || [])].sort((a, b) =>
    ((b.jev || {}).global_score ?? -1) - ((a.jev || {}).global_score ?? -1));
  const html = `<td colspan="10">
    <div class="muted small">${run.results.length} offre(s) dans ce lot
      ${best !== null ? `— meilleur score ${num(best)}` : ""}
      — statut ${escapeHtml(run.status)}</div>
    <table class="tbl offers nested">${OFFER_HEAD}<tbody>
      ${rows.map((item) => offerRow({
        run_id: run.id,
        url: item.url, title: item.title, company: item.company, location: item.location,
        evaluated_at: run.created_at, published_at: item.published_at,
        status: (item.decision || {}).status || item.status, error: item.error,
        score: (item.jev || {}).global_score,
        minimum_global_score: (item.jev || {}).minimum_global_score,
        blocking_criteria: (item.jev || {}).blocking_criteria || [],
        criteria: (item.jev || {}).criteria || [],
        gate_failures: ((item.decision || {}).hard_gate_failures || []).map((g) => g.gate),
        cv: null,
      })).join("")}
    </tbody></table></td>`;
  const row = document.createElement("tr");
  row.id = `exp-${runId}`;
  row.className = "expand";
  row.innerHTML = html;
  head.after(row);
  button.textContent = "offres ▴";
}

/* ------------------------------------------------------------------ table des offres */

function miniCriteria(criteria, minimumConfidence) {
  if (!criteria || !criteria.length) return "";
  return `<div class="minibars">${criteria.map((c) => {
    const cls = c.required && !c.passed ? "fail"
      : (c.confidence !== null && c.confidence < minimumConfidence ? "lowconf" : "");
    return `<span class="${cls}" style="height:${Math.max(2, Math.round((c.score / 100) * 22))}px"
      title="${escapeHtml(c.id)} : ${num(c.score)}/100, confiance ${num(c.confidence, 2)}${c.required ? ` (obligatoire ≥ ${c.min_score})` : ""}"></span>`;
  }).join("")}</div>`;
}

/* --- filtres et groupement : fonctions pures, testées hors navigateur --- */

function filterOffers(offers, opts) {
  const query = (opts.query || "").trim().toLowerCase();
  return offers.filter((o) => {
    if (opts.status && o.status !== opts.status) return false;
    const hasScore = typeof o.score === "number";
    const threshold = o.minimum_global_score ?? 68;
    if (opts.score === "scored" && !hasScore) return false;
    if (opts.score === "unscored" && hasScore) return false;
    if (opts.score === "above" && !(hasScore && o.score >= threshold)) return false;
    if (opts.score === "below" && !(hasScore && o.score < threshold)) return false;
    if (!query) return true;
    return [o.title, o.company, o.location, o.status, o.url,
            ...(o.blocking_criteria || []), ...(o.gate_failures || [])]
      .join(" ").toLowerCase().includes(query);
  });
}

function groupOffersByLot(offers) {
  const groups = new Map();
  for (const offer of offers) {
    const key = offer.run_id || "sans-lot";
    if (!groups.has(key)) {
      groups.set(key, { run_id: key, created_at: offer.evaluated_at || "", offers: [] });
    }
    const group = groups.get(key);
    group.offers.push(offer);
    if (offer.evaluated_at && offer.evaluated_at > group.created_at) {
      group.created_at = offer.evaluated_at;
    }
  }
  return [...groups.values()].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
}

function cvCell(o) {
  return `<td class="nowrap" id="cv-${escapeHtml(o.url)}">
    ${o.cv ? `<a class="mini" href="/api/cv/${o.cv.job_id}/pdf" target="_blank">PDF existant</a>` : ""}
    <button class="mini" data-cv="${escapeHtml(o.url)}">CV (PDF)</button>
    <button class="mini" data-cv-email="${escapeHtml(o.url)}" title="envoie aussi le PDF sur ta boîte mail">CV + email</button>
  </td>`;
}

function offerRow(o) {
  return `<tr>
    <td><a href="${escapeHtml(o.url)}" target="_blank" rel="noopener">${escapeHtml(o.title || o.url).slice(0, 90)}</a>
      <div class="muted">${escapeHtml(o.company || "—")} — ${escapeHtml(o.location || "—")}
      ${o.evaluated_at ? `— évaluée le ${escapeHtml(o.evaluated_at).replace("T", " ")}` : ""}</div>
      ${o.error ? `<div class="error small">${escapeHtml(o.error)}</div>` : ""}</td>
    <td class="num ${scoreClass(o.score, o.minimum_global_score)}-text">${num(o.score)}
      <div class="muted">seuil ${o.minimum_global_score ?? "—"}</div></td>
    <td>${miniCriteria(o.criteria, 0.5)}</td>
    <td>${statusBadge(o.status)}</td>
    <td class="nowrap">${o.published_at ? escapeHtml(o.published_at) : '<span class="muted">non prouvée</span>'}</td>
    <td class="muted">${(o.blocking_criteria || []).map((c) => `<code>${escapeHtml(c)}</code>`).join(" ") || "—"}</td>
    <td class="muted">${(o.gate_failures || []).map((g) => `<span class="chip bad">${escapeHtml(g)}</span>`).join("") || "—"}</td>
    ${cvCell(o)}
  </tr>`;
}

const OFFER_HEAD = `<thead><tr><th>Poste / entreprise</th><th>Score</th><th>Critères</th><th>Statut</th>
  <th>Publiée</th><th>Ce qui bloque</th><th>Portes</th><th>CV</th></tr></thead>`;

function renderOffers() {
  const rows = filterOffers(offersCache, {
    query: $("#filter").value,
    status: $("#status_filter").value,
    score: $("#score_filter").value,
  });
  $("#offers_count").textContent = `${rows.length} / ${offersCache.length} offres`;
  if (!rows.length) { $("#offers").innerHTML = '<p class="muted">Aucune offre pour ce filtre.</p>'; return; }

  if (!$("#group_by_lot").checked) {
    $("#offers").innerHTML = `<table class="tbl offers">${OFFER_HEAD}<tbody>${rows.map(offerRow).join("")}</tbody></table>`;
    return;
  }

  $("#offers").innerHTML = groupOffersByLot(rows).map((group) => {
    const scores = group.offers.map((o) => o.score).filter((s) => typeof s === "number");
    const best = scores.length ? Math.max(...scores) : null;
    return `<table class="tbl offers grouped">
      <thead><tr class="lothead">
        <th colspan="8">Lot du ${escapeHtml(group.created_at.replace("T", " "))}
          — ${group.offers.length} offre(s) affichée(s)
          ${best !== null ? `— meilleur score ${num(best)}` : ""}
          <button class="mini" data-run="${escapeHtml(group.run_id)}">détail du lot</button>
          <a class="mini" href="/api/runs/${escapeHtml(group.run_id)}/export?fmt=csv">csv</a>
        </th></tr></thead>
      <tbody>${group.offers.map(offerRow).join("")}</tbody>
    </table>`;
  }).join("");
}

/* ------------------------------------------------------------------ détail d'un lot */

function statusBadge(status) {
  const map = {
    qualified: ["Qualifiée", "ok"],
    jev_excluded: ["Validée Jev mais exclue", "warn"],
    rejected: ["Refusée Jev", "bad"],
    unverified: ["Non vérifiée", "unknown"],
    ok: ["Évaluée (refus Jev)", "bad"],
    error: ["Échec technique", "unknown"],
  };
  const [label, cls] = map[status] || [status || "—", "unknown"];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function gatesBlock(gates) {
  if (!gates || !gates.length) return "";
  return `<ul class="gates">${gates.map((g) => {
    const cls = { pass: "ok", fail: "bad", warn: "warn" }[g.status] || "unknown";
    const symbol = { pass: "✓", fail: "✗", warn: "!" }[g.status] || "?";
    return `<li class="${cls}"><strong>${escapeHtml(g.gate)}</strong> ${symbol} ${escapeHtml(g.reason)}</li>`;
  }).join("")}</ul>`;
}

function criteriaTable(jev, minimumConfidence) {
  if (!jev || !jev.criteria) return "";
  return `<table class="criteria">
    <thead><tr><th>Critère</th><th>Score</th><th>Confiance</th><th>Obligatoire</th><th></th></tr></thead>
    <tbody>${jev.criteria.map((c) => {
      const low = c.confidence !== null && c.confidence < minimumConfidence;
      return `<tr class="${c.required && !c.passed ? "failed" : ""}">
        <td><code>${escapeHtml(c.id)}</code><div class="muted">${escapeHtml(c.name)}</div></td>
        <td class="num"><strong>${num(c.score)}</strong>
          <div class="muted">/100${c.required ? ` — seuil ${c.min_score}` : ""}</div></td>
        <td class="num">${num(c.confidence, 2)}${low ? '<div class="muted">confiance faible</div>' : ""}</td>
        <td>${c.required ? (c.passed ? "obligatoire ✓" : "obligatoire ✗") : "—"}</td>
        <td class="bar"><span style="width:${Math.max(0, Math.min(100, c.score))}%"></span></td>
      </tr>`;
    }).join("")}</tbody></table>`;
}

function renderRun(run) {
  const results = run.results || [];
  const minimumConfidence = results[0]?.jev?.minimum_confidence ?? 0.5;
  const minimumGlobalScore = results[0]?.jev?.minimum_global_score ?? 68;
  const sorted = [...results].sort((a, b) => (b.jev?.global_score ?? -1) - (a.jev?.global_score ?? -1));
  const s = run.summary || {};
  $("#results").innerHTML = `
    <div class="toolbar">
      <h2>Lot ${escapeHtml(run.id)} — ${sorted.length}/${run.total} offres
        <span class="muted">(${escapeHtml(run.created_at).replace("T", " ")} — ${escapeHtml(run.status)})</span></h2>
      <div>
        <a class="btn" href="/api/runs/${run.id}/export?fmt=json">Export JSON</a>
        <a class="btn" href="/api/runs/${run.id}/export?fmt=csv">Export CSV</a>
      </div>
    </div>
    <div class="kpis small">
      ${kpi("Score moyen du lot", num(s.avg_score))}
      ${kpi("Meilleur", num(s.best_score))}
      ${kpi("Qualifiées", s.qualified ?? 0)}
      ${kpi("Portes en échec", s.gate_failures ?? 0)}
    </div>
    ${sorted.map((item) => card(item, minimumConfidence, minimumGlobalScore)).join("")}`;
}

function card(item, minimumConfidence, minimumGlobalScore) {
  const jev = item.jev || {};
  const decision = item.decision || {};
  const score = jev.global_score;
  const gateFailures = (decision.hard_gate_failures || [])
    .map((g) => `<li class="muted">porte ${escapeHtml(g.gate)} : ${escapeHtml(g.reason)}</li>`).join("");
  const blocking = (jev.blocking_criteria || []).length
    ? `<p class="muted">Critères obligatoires non satisfaits :
        ${jev.blocking_criteria.map((c) => `<code>${escapeHtml(c)}</code>`).join(" ")}</p>` : "";
  const lowConf = (jev.low_confidence_criteria || []).length
    ? `<p class="muted">Confiance sous ${minimumConfidence} : ${jev.low_confidence_criteria.map(escapeHtml).join(", ")}
       — réserve à signaler, pas un rejet net.</p>` : "";
  return `<article class="card">
    <div class="cardhead">
      <div>
        <h3>${escapeHtml(item.title || item.url)}</h3>
        <p class="muted">${escapeHtml(item.company || "—")} — ${escapeHtml(item.location || "—")}
          ${item.published_at ? `— publiée le ${escapeHtml(item.published_at)}` : "— date non prouvée"}
          ${item.published_at_provenance ? `<span class="muted">(${escapeHtml(item.published_at_provenance)})</span>` : ""}</p>
        <p class="muted"><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.url)}</a>
          ${jev.usage ? `<span class="muted">— ${jev.usage.input_tokens} tokens, $${(jev.usage.cost || 0).toFixed(5)}</span>` : ""}</p>
      </div>
      <div class="scorecell">
        ${score === undefined ? '<span class="score na">—</span>'
          : `<span class="score ${scoreClass(score, minimumGlobalScore)}">${num(score)}</span>
             <span class="muted">/100 — seuil ${jev.minimum_global_score}</span>`}
        ${statusBadge(decision.status || item.status)}
        <div class="cvbox" id="cv-${escapeHtml(item.url)}">
          ${item.cv ? `<a class="mini" href="/api/cv/${item.cv.job_id}/pdf" target="_blank">PDF existant</a>` : ""}
          <button class="mini" data-cv="${escapeHtml(item.url)}">Générer le CV (PDF)</button>
          <button class="mini" data-cv-email="${escapeHtml(item.url)}"
                  title="envoie aussi le PDF sur ta boîte mail">CV + email</button>
        </div>
      </div>
    </div>
    ${item.error ? `<p class="error">${escapeHtml(item.error)}</p>` : ""}
    ${gatesBlock(item.gate_results)}
    ${gateFailures ? `<ul class="gates">${gateFailures}</ul>` : ""}
    ${blocking}${lowConf}
    ${criteriaTable(jev, minimumConfidence)}
  </article>`;
}

/* ------------------------------------------------------------------ CV */

function rememberCvJob(job) {
  const index = cvJobsCache.findIndex((item) => item.id === job.id);
  if (index === -1) cvJobsCache.unshift(job);
  else cvJobsCache[index] = job;
  cvJobsCache = cvJobsCache.slice(0, 20);
}

function cvJobStatus(job) {
  if (job.status === "running") return "Génération en cours…";
  if (job.status === "done") return "PDF prêt";
  return "Échec";
}

function renderCvJobs() {
  const target = $("#cv_jobs");
  if (!target) return;
  if (!cvJobsCache.length) {
    target.innerHTML = '<p class="muted">Aucune génération de CV.</p>';
    return;
  }
  target.innerHTML = `<table class="tbl">
    <thead><tr><th>Lancée le</th><th>Offre</th><th>État</th><th>Résultat</th></tr></thead>
    <tbody>${cvJobsCache.map((job) => {
      const payload = job.payload || {};
      const result = job.status === "done"
        ? `<a class="mini" href="/api/cv/${job.id}/pdf" target="_blank">Télécharger le PDF</a>`
        : (job.status === "failed"
          ? `<span class="error small">${escapeHtml((payload.error || "échec").slice(0, 400))}</span>`
          : '<span class="muted small">Le suivi reprend automatiquement après un rechargement.</span>');
      return `<tr data-cv-job="${job.id}">
        <td class="nowrap">${escapeHtml(job.created_at || "—").replace("T", " ")}</td>
        <td><a href="${escapeHtml(job.url)}" target="_blank" rel="noopener">${escapeHtml(job.url).slice(0, 100)}</a></td>
        <td>${escapeHtml(cvJobStatus(job))}</td><td>${result}</td></tr>`;
    }).join("")}</tbody></table>`;
}

async function generateCv(url, button, sendEmail) {
  const box = document.getElementById("cv-" + url);
  const label = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = "génération…"; }
  try {
    const res = await fetch("/api/cv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, send_email: !!sendEmail }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erreur");
    if (box) box.insertAdjacentHTML("beforeend",
      `<span class="muted small" data-cvstatus="${data.job_id}">moteur lancé${sendEmail ? " (PDF + email)" : " (PDF seulement)"}…</span>`);
    rememberCvJob({ id: data.job_id, url, status: "running", payload: null,
      created_at: new Date().toISOString().slice(0, 19) });
    renderCvJobs();
    pollCv(data.job_id, box);
  } catch (err) {
    if (button) { button.disabled = false; button.textContent = label; }
    if (box) box.insertAdjacentHTML("beforeend", `<div class="error small">${escapeHtml(err.message)}</div>`);
  }
}

function pollCv(jobId, box = null) {
  if (cvPollers[jobId]) return;
  const tick = async () => {
    let res;
    try {
      res = await fetch(`/api/cv/${jobId}`);
    } catch (_) {
      return;
    }
    if (!res.ok) return;
    const job = await res.json();
    rememberCvJob(job);
    renderCvJobs();
    const label = box ? box.querySelector(`[data-cvstatus="${jobId}"]`) : null;
    if (job.status === "running") {
      if (label) label.textContent = " génération du CV en cours…";
      return;
    }
    clearInterval(cvPollers[jobId]); delete cvPollers[jobId];
    const payload = job.payload || {};
    if (label) label.remove();
    if (job.status === "done") {
      const info = [
        payload.pages ? `${payload.pages} page(s)` : "",
        payload.headline ? `titre : « ${payload.headline} »` : "",
        (payload.emphasis || []).length ? `priorités : ${payload.emphasis.join(", ")}` : "",
        (payload.warnings || []).length ? `${payload.warnings.length} avertissement(s)` : "",
        payload.email ? `email : ${payload.email}` : "",
      ].filter(Boolean).join(" — ");
      if (box) box.insertAdjacentHTML("beforeend",
        `<div><a class="mini" href="/api/cv/${jobId}/pdf" target="_blank">Télécharger le CV PDF</a></div>
         <div class="muted small">${escapeHtml(info)}</div>
         ${(payload.gaps || []).length ? `<div class="muted small">écarts signalés : ${escapeHtml(payload.gaps.join(" | "))}</div>` : ""}`);
    } else if (box) {
      box.insertAdjacentHTML("beforeend",
        `<div class="error small">moteur CV : ${escapeHtml((payload.error || "échec").slice(0, 400))}</div>`);
    }
  };
  cvPollers[jobId] = setInterval(tick, 3000);
  tick();
}

/* ------------------------------------------------------------------ chargement */

async function loadDashboard() {
  const [stats, history, offers, cvJobs] = await Promise.all([
    fetch("/api/stats").then((r) => r.json()),
    fetch("/api/history").then((r) => r.json()),
    fetch("/api/offers").then((r) => r.json()),
    fetch("/api/cv?limit=20").then((r) => r.json()),
  ]);
  renderKpis(stats);
  renderDistribution(stats);
  renderGates(stats);
  renderCriteriaStats(stats);
  renderHistory(history);
  offersCache = offers.offers || [];
  renderOffers();
  cvJobsCache = cvJobs.jobs || [];
  renderCvJobs();
  cvJobsCache.filter((job) => job.status === "running")
    .forEach((job) => pollCv(job.id));
}

document.addEventListener("click", (event) => {
  const expand = event.target.closest("[data-expand-run]");
  if (expand) { toggleRunRow(expand.dataset.expandRun, expand); return; }

  const runLink = event.target.closest("[data-run]");
  if (runLink) {
    event.preventDefault();
    fetch(`/api/runs/${runLink.dataset.run}`).then((r) => r.json()).then((run) => {
      renderRun(run);
      $("#status").textContent = "Lot " + run.id;
      $("#results").scrollIntoView({ behavior: "smooth" });
    });
    return;
  }
  const cvButton = event.target.closest("[data-cv]");
  if (cvButton) { generateCv(cvButton.dataset.cv, cvButton, false); return; }
  const cvEmail = event.target.closest("[data-cv-email]");
  if (cvEmail) generateCv(cvEmail.dataset.cvEmail, cvEmail, true);
});

$("#run").addEventListener("click", startRun);
$("#filter").addEventListener("input", renderOffers);
$("#status_filter").addEventListener("change", renderOffers);
$("#score_filter").addEventListener("change", renderOffers);
$("#group_by_lot").addEventListener("change", renderOffers);
loadDashboard();