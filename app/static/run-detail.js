(() => {
  const { $, escapeHtml, fetchJSON, statusBadge, scoreVisual, criteriaHtml, gatesHtml, formatDate, generateCv } = JEV;
  const runId = $("#run_page").dataset.runId;
  let poller = null;

  function card(item) {
    const jev = item.jev || {}, decision = item.decision || {};
    const status = decision.status || item.status;
    return `<article class="detail-card"><div class="detail-card-head"><div><p class="eyebrow">${escapeHtml(item.company || "Entreprise inconnue")}</p><h2>${escapeHtml(item.title || item.url)}</h2><p>${escapeHtml(item.location || "Localisation inconnue")} · ${item.published_at ? `publiée ${escapeHtml(item.published_at)}` : "date non prouvée"}</p></div>${scoreVisual(jev.global_score, jev.minimum_global_score)}</div><div class="detail-status">${statusBadge(status)}<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">Offre source ↗</a></div>${item.error ? `<div class="error">${escapeHtml(item.error)}</div>` : ""}<details open><summary>Portes de vérification</summary>${gatesHtml(item.gate_results || [])}</details><details><summary>Critères Jev</summary>${criteriaHtml(jev.criteria || [], jev.minimum_confidence)}</details><div class="detail-actions">${item.cv ? `<a class="secondary-btn" href="/api/cv/${item.cv.job_id}/pdf" target="_blank">CV existant</a>` : ""}<button data-cv="${escapeHtml(item.url)}">Générer le CV</button><button class="secondary-btn" data-cv-email="${escapeHtml(item.url)}">CV + email</button></div></article>`;
  }

  async function load() {
    try {
      const run = await fetchJSON(`/api/runs/${runId}`), summary = run.summary || {};
      $("#run_header").innerHTML = `<div><p class="eyebrow">Lot ${escapeHtml(run.id)}</p><h1>${run.status === "running" ? "Évaluation en cours" : "Résultats du lot"}</h1><p>Lancé le ${formatDate(run.created_at)} · ${run.progress}/${run.total} offres traitées</p></div>${statusBadge(run.status)}`;
      const progress = run.total ? Math.round((run.progress / run.total) * 100) : 0;
      $("#run_progress").innerHTML = run.status === "running" ? `<div class="progress large"><span style="width:${progress}%"></span></div>` : "";
      $("#run_controls").innerHTML = run.status === "running" ? '<button class="secondary-btn" data-run-cancel>Annuler le lot</button>' : ["failed", "interrupted", "cancelled"].includes(run.status) ? '<button data-run-retry>Relancer les offres manquantes</button>' : "";
      $("#run_summary").innerHTML = [["Score moyen", summary.avg_score ?? "—"], ["Meilleur", summary.best_score ?? "—"], ["Qualifiées", summary.qualified || 0], ["Refusées", summary.rejected || 0], ["Exclues", summary.jev_excluded || 0], ["Erreurs", summary.errors || 0]].map(([label, value]) => `<div class="kpi"><strong>${value}</strong><span>${label}</span></div>`).join("");
      const sorted = [...(run.results || [])].sort((a, b) => (b.jev?.global_score ?? -1) - (a.jev?.global_score ?? -1));
      $("#run_offers").innerHTML = sorted.length ? sorted.map(card).join("") : '<div class="empty-state"><strong>Traitement en attente</strong><p>Les premières offres apparaîtront ici.</p></div>';
      if (run.status !== "running" && poller) { clearInterval(poller); poller = null; JEV.refreshNavBadges(); }
    } catch (error) { $("#run_offers").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  }
  $("#run_offers").addEventListener("click", (event) => { const cv = event.target.closest("[data-cv]"); const email = event.target.closest("[data-cv-email]"); if (cv) generateCv(cv.dataset.cv, false, cv); if (email) generateCv(email.dataset.cvEmail, true, email); });
  $("#run_controls").addEventListener("click", async (event) => {
    const retry = event.target.closest("[data-run-retry]");
    const cancel = event.target.closest("[data-run-cancel]");
    const button = retry || cancel;
    if (!button) return;
    button.disabled = true;
    try {
      await fetchJSON(`/api/runs/${runId}/${retry ? "retry" : "cancel"}`, { method: "POST" });
      if (retry && !poller) poller = setInterval(load, 2000);
      await load();
    } catch (error) { JEV.showToast(error.message, "error"); button.disabled = false; }
  });
  load(); poller = setInterval(load, 2000);
})();
