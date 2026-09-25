(() => {
  const { $, escapeHtml, fetchJSON, statusBadge, paginationHtml, formatDate } = JEV;
  let page = 1, status = "";
  function card(job) {
    const payload = job.payload || {};
    let result = '<span class="muted">Le suivi continue automatiquement.</span><button class="secondary-btn" data-cancel="' + job.id + '">Annuler</button>';
    if (job.status === "done") result = `<a class="primary-link" href="/api/cv/${job.id}/pdf" target="_blank">Télécharger le PDF</a>`;
    if (["failed", "interrupted", "cancelled"].includes(job.status)) result = `<div class="error small">${escapeHtml(payload.error || job.last_error || "Échec sans détail")}</div><button data-retry="${job.id}">Relancer</button>`;
    return `<article class="job-card" data-job-id="${job.id}"><div><p class="eyebrow">${formatDate(job.created_at)} · tentative ${job.attempts || 1}</p><a href="${escapeHtml(job.url)}" target="_blank" rel="noopener">${escapeHtml(job.url)}</a></div><div>${statusBadge(job.status)}</div><div>${result}${payload.headline ? `<p class="muted">Titre retenu : ${escapeHtml(payload.headline)}</p>` : ""}</div></article>`;
  }
  async function load() {
    try {
      const payload = await fetchJSON(`/api/cv?page=${page}&page_size=25${status ? `&status=${status}` : ""}`);
      $("#cv_jobs").innerHTML = payload.jobs.length ? payload.jobs.map(card).join("") : '<div class="empty-state"><strong>Aucun CV</strong><p>La génération se lance depuis une offre ou un lot.</p></div>';
      $("#cv_pagination").innerHTML = paginationHtml(payload.page, payload.pages);
      payload.jobs.filter((job) => job.status === "running").forEach((job) => JEV.pollCv(job.id));
    } catch (error) { $("#cv_jobs").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  }
  $("#cv_status").addEventListener("change", (event) => { status = event.target.value; page = 1; load(); });
  $("#cv_pagination").addEventListener("click", (event) => { const button = event.target.closest("[data-page]"); if (!button || button.disabled) return; page = Number(button.dataset.page); load(); });
  $("#cv_jobs").addEventListener("click", async (event) => {
    const retry = event.target.closest("[data-retry]");
    const cancel = event.target.closest("[data-cancel]");
    const button = retry || cancel;
    if (!button) return;
    button.disabled = true;
    try {
      await fetchJSON(`/api/cv/${retry ? retry.dataset.retry : cancel.dataset.cancel}/${retry ? "retry" : "cancel"}`, { method: "POST" });
      await load();
    } catch (error) { JEV.showToast(error.message, "error"); button.disabled = false; }
  });
  document.addEventListener("jev:cv-updated", load);
  load();
})();
