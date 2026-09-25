(() => {
  const { $, escapeHtml, fetchJSON, applicationStatusBadge, paginationHtml,
    updateQuery, formatDate, showToast } = JEV;
  const params = new URLSearchParams(location.search);
  const state = {
    page: Number(params.get("page")) || 1,
    page_size: 25,
    q: params.get("q") || "",
    status: params.get("status") || "",
    due: params.get("due") || "",
    sort: params.get("sort") || "updated",
  };
  const initiallyOpen = params.get("open") || "";
  let debounce = null;
  let drawerTrigger = null;

  function queryString() {
    const query = new URLSearchParams();
    Object.entries(state).forEach(([key, value]) => { if (value !== "") query.set(key, value); });
    return query.toString();
  }

  function card(item) {
    const followUp = item.follow_up_at
      ? `<span class="${item.overdue ? "bad-text" : ""}">Relance ${escapeHtml(item.follow_up_at)}${item.overdue ? " · en retard" : ""}</span>`
      : '<span class="muted">Aucune relance prévue</span>';
    return `<article class="application-card ${item.overdue ? "overdue" : ""}" data-app-id="${escapeHtml(item.id)}" tabindex="0">
      <div><div class="offer-title-line"><strong>${escapeHtml(item.title || item.url)}</strong>${item.overdue ? '<span class="count-badge danger">relance en retard</span>' : ""}</div><span>${escapeHtml(item.company || "Entreprise inconnue")} · ${escapeHtml(item.location || "Localisation inconnue")}</span><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" data-external>Voir l’offre source ↗</a></div>
      <div>${applicationStatusBadge(item.status)}${followUp}</div>
      <div><span class="muted">Modifiée ${formatDate(item.updated_at)}</span><button class="icon-btn" data-open-app aria-label="Ouvrir la candidature">→</button></div>
    </article>`;
  }

  function renderKpis(counts = {}) {
    const labels = { to_review: "À étudier", cv_ready: "CV prêts", applied: "Envoyées", interview: "Entretiens", rejected: "Refus", offer: "Offres" };
    $("#application_kpis").innerHTML = Object.entries(labels).map(([key, label]) => `<button class="kpi" data-kpi-status="${key}"><strong>${counts[key] || 0}</strong><span>${label}</span></button>`).join("");
  }

  async function load(push = false) {
    updateQuery(state, !push);
    try {
      const payload = await fetchJSON(`/api/applications?${queryString()}`);
      $("#applications_list").innerHTML = payload.applications.length ? payload.applications.map(card).join("") : '<div class="empty-state"><strong>Aucune candidature</strong><p>Ajoutez une offre au suivi depuis la page Offres.</p></div>';
      $("#applications_pagination").innerHTML = paginationHtml(payload.page, payload.pages);
      renderKpis(payload.counts);
    } catch (error) {
      $("#applications_list").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    }
  }

  function eventLine(event) {
    const label = event.event_type === "created" ? "Ajout au suivi"
      : event.event_type === "cv_ready" ? "CV généré"
      : event.event_type === "status_changed" ? "Changement de statut" : "Mise à jour";
    const transition = event.from_status !== event.to_status
      ? `${applicationStatusBadge(event.from_status)} → ${applicationStatusBadge(event.to_status)}` : "";
    return `<div class="application-event"><span>${formatDate(event.created_at)}</span><strong>${label}</strong><div>${transition}</div></div>`;
  }

  async function openDrawer(applicationId) {
    const drawer = $("#application_drawer"), backdrop = $("#application_drawer_backdrop");
    if (!drawer.classList.contains("open")) drawerTrigger = document.activeElement;
    drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); backdrop.classList.remove("hidden");
    $("#application_detail").innerHTML = '<div class="loading-card">Chargement…</div>';
    const item = await fetchJSON(`/api/applications/${applicationId}`);
    $("#application_detail").innerHTML = `<div class="drawer-title"><p class="eyebrow">${escapeHtml(item.company || "Candidature")}</p><h2>${escapeHtml(item.title || item.url)}</h2><p>${escapeHtml(item.location || "Localisation inconnue")}</p></div>
      <div class="drawer-status">${applicationStatusBadge(item.status)}<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">Offre source ↗</a></div>
      <form id="application_form" class="stack-form">
        <input type="hidden" name="revision" value="${item.revision}">
        <label>Statut<select name="status"><option value="to_review">À étudier</option><option value="cv_ready">CV prêt</option><option value="applied">Candidature envoyée</option><option value="interview">Entretien</option><option value="rejected">Refus</option><option value="offer">Offre reçue</option></select></label>
        <label>Poste<input name="title" maxlength="300" value="${escapeHtml(item.title || "")}"></label>
        <div class="form-grid"><label>Entreprise<input name="company" maxlength="300" value="${escapeHtml(item.company || "")}"></label><label>Localisation<input name="location" maxlength="300" value="${escapeHtml(item.location || "")}"></label></div>
        <div class="form-grid"><label>Date de candidature<input name="applied_at" type="date" value="${escapeHtml(item.applied_at || "")}"></label><label>Prochaine relance<input name="follow_up_at" type="date" value="${escapeHtml(item.follow_up_at || "")}"></label></div>
        <div class="form-grid"><label>Contact<input name="contact_name" maxlength="300" value="${escapeHtml(item.contact_name || "")}"></label><label>Email du contact<input name="contact_email" type="email" maxlength="320" value="${escapeHtml(item.contact_email || "")}"></label></div>
        <label>Notes<textarea name="notes" rows="8" maxlength="10000">${escapeHtml(item.notes || "")}</textarea></label>
        <div class="action-row"><button type="submit">Enregistrer</button><button type="button" class="secondary-btn" data-delete-app>Supprimer du suivi</button></div>
      </form>
      <section><h3>Historique</h3><div class="application-events">${(item.events || []).map(eventLine).join("") || '<p class="muted">Aucun événement.</p>'}</div></section>`;
    $("#application_form [name=status]").value = item.status;
    $("#application_drawer_close").focus();
    $("#application_form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const body = {
        revision: Number(form.get("revision")), status: form.get("status"),
        title: form.get("title"), company: form.get("company"), location: form.get("location"),
        applied_at: form.get("applied_at"), follow_up_at: form.get("follow_up_at"),
        contact_name: form.get("contact_name"), contact_email: form.get("contact_email"),
        notes: form.get("notes"),
      };
      const submit = event.submitter || $("#application_form button[type=submit]");
      submit.disabled = true;
      try {
        await fetchJSON(`/api/applications/${applicationId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        showToast("Candidature mise à jour.", "success");
        await load(); await openDrawer(applicationId);
      } catch (error) { showToast(error.message, "error"); submit.disabled = false; }
    });
    $("[data-delete-app]").addEventListener("click", async () => {
      if (!window.confirm("Supprimer définitivement cette candidature et son historique ?")) return;
      try {
        await fetchJSON(`/api/applications/${applicationId}`, { method: "DELETE" });
        closeDrawer(); await load(); showToast("Candidature supprimée.", "success");
      } catch (error) { showToast(error.message, "error"); }
    });
  }

  function closeDrawer() {
    $("#application_drawer").classList.remove("open");
    $("#application_drawer").setAttribute("aria-hidden", "true");
    $("#application_drawer_backdrop").classList.add("hidden");
    if (drawerTrigger?.isConnected) drawerTrigger.focus();
    drawerTrigger = null;
  }

  $("#app_q").value = state.q; $("#app_status").value = state.status;
  $("#app_due").value = state.due; $("#app_sort").value = state.sort;
  $("#app_q").addEventListener("input", (event) => { clearTimeout(debounce); debounce = setTimeout(() => { state.q = event.target.value.trim(); state.page = 1; load(true); }, 300); });
  for (const [id, key] of [["app_status", "status"], ["app_due", "due"], ["app_sort", "sort"]]) {
    $("#" + id).addEventListener("change", (event) => { state[key] = event.target.value; state.page = 1; load(true); });
  }
  $("#application_kpis").addEventListener("click", (event) => { const button = event.target.closest("[data-kpi-status]"); if (!button) return; state.status = button.dataset.kpiStatus; state.page = 1; $("#app_status").value = state.status; load(true); });
  $("#applications_pagination").addEventListener("click", (event) => { const button = event.target.closest("[data-page]"); if (!button || button.disabled) return; state.page = Number(button.dataset.page); load(true); });
  $("#applications_list").addEventListener("click", (event) => { if (event.target.closest("[data-external]")) return; const card = event.target.closest("[data-app-id]"); if (card) openDrawer(card.dataset.appId).catch((error) => showToast(error.message, "error")); });
  $("#applications_list").addEventListener("keydown", (event) => { if (event.key === "Enter" && event.target.matches("[data-app-id]")) openDrawer(event.target.dataset.appId); });
  $("#application_drawer_close").addEventListener("click", closeDrawer);
  $("#application_drawer_backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
  window.addEventListener("popstate", () => location.reload());
  load().then(() => { if (initiallyOpen) openDrawer(initiallyOpen).catch((error) => showToast(error.message, "error")); });
})();
