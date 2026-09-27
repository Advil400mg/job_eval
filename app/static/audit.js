(() => {
  const { $, escapeHtml, fetchJSON, paginationHtml, formatDate, updateQuery } = JEV;
  const params = new URLSearchParams(location.search);
  const state = {
    event_type: params.get("event_type") || "",
    actor_id: params.get("actor_id") || "",
    success: params.get("success") || "",
    days: params.get("days") || "",
    page: Math.max(1, Number(params.get("page")) || 1),
    limit: 50,
  };
  const labels = {
    "auth.login_failed": "Connexion refusée", "auth.login_succeeded": "Connexion réussie",
    "auth.logout": "Déconnexion", "auth.password_changed": "Mot de passe modifié",
    "auth.password_change_failed": "Modification du mot de passe refusée",
    "auth.sessions_revoked": "Sessions révoquées", "user.first_admin_created": "Premier administrateur créé",
    "user.registered": "Compte créé", "user.activation_changed": "État du compte modifié",
    "user.deleted": "Compte supprimé", "invitation.created": "Invitation créée",
    "invitation.revoked": "Invitation révoquée", "profile.updated": "Profil modifié",
    "profile.restored": "Profil restauré", "backup.created": "Sauvegarde créée",
    "backup.deleted": "Sauvegarde supprimée", "backup.verified": "Sauvegarde vérifiée",
    "backup.verification_failed": "Vérification de sauvegarde échouée",
    "backup.restored": "Sauvegarde restaurée", "backup.restore_failed": "Restauration échouée",
    "evaluation.started": "Évaluation lancée", "evaluation.retried": "Évaluation relancée",
    "evaluation.cancel_requested": "Annulation d’évaluation demandée", "cv.started": "Génération CV lancée",
    "cv.retried": "Génération CV relancée", "cv.cancel_requested": "Annulation CV demandée",
    "onboarding.started": "Initialisation du profil lancée", "application.created": "Candidature créée",
    "application.updated": "Candidature modifiée", "application.deleted": "Candidature supprimée",
  };

  function eventRow(item) {
    const metadata = Object.entries(item.metadata || {}).map(([key, value]) =>
      `<span><strong>${escapeHtml(key)}</strong> ${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</span>`).join("");
    return `<article class="audit-event ${item.success ? "is-ok" : "is-error"}">
      <div><span class="admin-pill ${item.success ? "invite-active" : "invite-revoked"}">${item.success ? "Réussite" : "Échec"}</span><strong>${escapeHtml(labels[item.event_type] || item.event_type)}</strong><code>${escapeHtml(item.event_type)}</code></div>
      <div><time datetime="${escapeHtml(item.created_at)}">${escapeHtml(formatDate(item.created_at))}</time><span>Auteur : ${escapeHtml(item.actor_username || item.actor_user_id || "système")}</span><span>Sujet : ${escapeHtml(item.subject_type || "—")} ${escapeHtml(item.subject_id || "")}</span></div>
      ${metadata ? `<div class="audit-metadata">${metadata}</div>` : ""}
    </article>`;
  }

  function fillOptions(select, rows, value, labeler) {
    const first = select.options[0].outerHTML;
    select.innerHTML = first + rows.map((row) => `<option value="${escapeHtml(row.id || row)}">${escapeHtml(labeler(row))}</option>`).join("");
    select.value = value;
  }

  async function load(push = false) {
    updateQuery({ ...state, limit: null }, !push);
    const query = new URLSearchParams();
    if (state.event_type) query.set("event_type", state.event_type);
    if (state.actor_id) query.set("actor_id", state.actor_id);
    if (state.success) query.set("success", state.success);
    if (state.days) query.set("days", state.days);
    query.set("limit", state.limit); query.set("offset", (state.page - 1) * state.limit);
    try {
      const payload = await fetchJSON(`/api/admin/audit?${query}`);
      fillOptions($("#audit_type"), payload.event_types || [], state.event_type, (row) => labels[row] || row);
      fillOptions($("#audit_actor"), payload.actors || [], state.actor_id, (row) => `@${row.username}`);
      $("#audit_success").value = state.success; $("#audit_days").value = state.days;
      $("#audit_summary").textContent = `${payload.total} événement${payload.total > 1 ? "s" : ""}`;
      $("#audit_events").innerHTML = payload.events.length ? payload.events.map(eventRow).join("") : '<div class="empty-state"><strong>Aucun événement</strong><p>Modifiez les filtres ou effectuez une action auditable.</p></div>';
      $("#audit_pagination").innerHTML = paginationHtml(state.page, Math.max(1, Math.ceil(payload.total / state.limit)));
    } catch (error) {
      $("#audit_events").innerHTML = `<div class="error" role="alert">${escapeHtml(error.message)}</div>`;
    }
  }

  for (const [id, key] of [["audit_type", "event_type"], ["audit_actor", "actor_id"], ["audit_success", "success"], ["audit_days", "days"]]) {
    $("#" + id).addEventListener("change", (event) => { state[key] = event.target.value; state.page = 1; load(true); });
  }
  $("#audit_pagination").addEventListener("click", (event) => {
    const button = event.target.closest("[data-page]");
    if (!button || button.disabled) return;
    state.page = Number(button.dataset.page); load(true); window.scrollTo({ top: 0, behavior: "smooth" });
  });
  load();
})();
