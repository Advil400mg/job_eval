(() => {
  const { $, escapeHtml, fetchJSON, statusBadge, paginationHtml, formatDate } = JEV;
  let page = Number(new URLSearchParams(location.search).get("page")) || 1;
  let status = new URLSearchParams(location.search).get("status") || "";
  $("#run_status").value = status;

  function card(run) {
    const progress = run.total ? Math.round((run.progress / run.total) * 100) : 0;
    return `<article class="run-card block"><a href="/runs/${run.id}" class="run-card-main"><div><strong>${formatDate(run.created_at)}</strong><span>Lot ${escapeHtml(run.id)} · ${run.offers}/${run.total} offre(s)</span></div>${statusBadge(run.status)}</a><div class="run-metrics"><span><b>${run.qualified}</b> qualifiées</span><span><b>${run.rejected}</b> refusées</span><span><b>${run.jev_excluded}</b> exclues</span><span><b>${run.errors}</b> erreurs</span><span><b>${run.best_score ?? "—"}</b> meilleur</span></div>${run.status === "running" ? `<div class="progress"><span style="width:${progress}%"></span></div>` : ""}<div class="run-card-actions"><a href="/runs/${run.id}">Ouvrir</a><a href="/api/runs/${run.id}/export?fmt=csv">CSV</a><a href="/api/runs/${run.id}/export?fmt=json">JSON</a></div></article>`;
  }

  async function load() {
    JEV.updateQuery({ page, status });
    try {
      const payload = await fetchJSON(`/api/history?page=${page}&page_size=20${status ? `&status=${status}` : ""}`);
      $("#runs_list").innerHTML = payload.runs.length ? payload.runs.map(card).join("") : '<div class="empty-state"><strong>Aucun lot</strong><p>Lancez une évaluation pour commencer.</p></div>';
      $("#runs_pagination").innerHTML = paginationHtml(payload.page, payload.pages);
    } catch (error) { $("#runs_list").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  }
  $("#run_status").addEventListener("change", (event) => { status = event.target.value; page = 1; load(); });
  $("#runs_pagination").addEventListener("click", (event) => { const button = event.target.closest("[data-page]"); if (!button || button.disabled) return; page = Number(button.dataset.page); load(); });
  load();
})();
