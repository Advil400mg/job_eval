(() => {
  const { $, escapeHtml, fetchJSON, formatDate, showToast } = JEV;
  let profile = JSON.parse($("#profile_data").textContent);
  let revision = $("#profile_form").dataset.revision;

  const lines = (value) => String(value || "").split(/\n+/).map((item) => item.trim()).filter(Boolean);

  function criterionRow(criterion = {}) {
    return `<article class="criterion-edit" data-criterion>
      <div class="criterion-edit-head"><strong>${escapeHtml(criterion.name || "Nouveau critère")}</strong><button class="secondary-btn" type="button" data-remove-criterion>Supprimer</button></div>
      <div class="form-grid three"><label>Identifiant<input data-field="id" maxlength="64" pattern="[a-z][a-z0-9_-]{0,63}" required value="${escapeHtml(criterion.id || "")}"></label><label>Nom<input data-field="name" maxlength="200" required value="${escapeHtml(criterion.name || "")}"></label><label>Poids<input data-field="weight" type="number" min="0.1" max="100" step="0.1" required value="${escapeHtml(criterion.weight ?? 1)}"></label></div>
      <label>Description<textarea data-field="description" maxlength="2000" rows="3" required>${escapeHtml(criterion.description || "")}</textarea></label>
      <div class="form-grid"><label class="check-label"><input data-field="required" type="checkbox" ${criterion.required ? "checked" : ""}> Critère obligatoire</label><label>Score minimum<input data-field="min_score" type="number" min="0" max="100" step="0.1" value="${escapeHtml(criterion.min_score ?? 60)}"></label></div>
    </article>`;
  }

  function renderProfile() {
    const search = profile.search || {};
    const experience = search.experience_filter || {};
    $("#minimum_global_score").value = profile.minimum_global_score ?? 68;
    $("#minimum_confidence").value = profile.minimum_confidence ?? .5;
    $("#max_age_days").value = search.max_age_days ?? 30;
    $("#target_roles").value = (search.target_roles || []).join("\n");
    $("#locations").value = (search.locations || []).join("\n");
    $("#reject_experience_years").value = experience.reject_if_minimum_required_years_gte ?? 2;
    $("#internships_count").checked = !!experience.internships_count_as_professional_experience;
    $("#hard_rejection_rules").value = (profile.hard_rejection_rules || []).join("\n");
    $("#criteria_editor").innerHTML = (profile.criteria || []).map(criterionRow).join("");
    $("#profile_revision").textContent = revision.slice(0, 12);
  }

  function collectProfile() {
    const updated = structuredClone(profile);
    updated.minimum_global_score = Number($("#minimum_global_score").value);
    updated.minimum_confidence = Number($("#minimum_confidence").value);
    updated.hard_rejection_rules = lines($("#hard_rejection_rules").value);
    updated.search = updated.search || {};
    updated.search.target_roles = lines($("#target_roles").value);
    updated.search.locations = lines($("#locations").value);
    updated.search.max_age_days = Number($("#max_age_days").value);
    updated.search.experience_filter = {
      reject_if_minimum_required_years_gte: Number($("#reject_experience_years").value),
      internships_count_as_professional_experience: $("#internships_count").checked,
    };
    updated.criteria = [...document.querySelectorAll("[data-criterion]")].map((row) => ({
      id: $("[data-field=id]", row).value.trim(),
      name: $("[data-field=name]", row).value.trim(),
      description: $("[data-field=description]", row).value.trim(),
      weight: Number($("[data-field=weight]", row).value),
      required: $("[data-field=required]", row).checked,
      min_score: Number($("[data-field=min_score]", row).value),
    }));
    return updated;
  }

  async function loadHistory() {
    try {
      const payload = await fetchJSON("/api/profile/history?limit=30");
      $("#profile_history").innerHTML = payload.versions.map((item) => `<div class="profile-version"><div><strong>${formatDate(item.created_at)}</strong><span>${escapeHtml(item.source)} · <code>${escapeHtml(item.revision.slice(0, 12))}</code></span></div>${item.revision === revision ? '<span class="badge ok">Actuelle</span>' : `<button class="secondary-btn" type="button" data-restore-profile="${escapeHtml(item.id)}">Restaurer</button>`}</div>`).join("") || '<div class="empty-state">Aucune version.</div>';
    } catch (error) { $("#profile_history").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  }

  $("#profile_form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#profile_save"); button.disabled = true;
    $("#profile_errors").classList.add("hidden");
    try {
      const result = await fetchJSON("/api/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile: collectProfile(), expected_revision: revision }) });
      profile = result.profile; revision = result.revision; $("#profile_form").dataset.revision = revision;
      renderProfile(); await loadHistory(); showToast(result.changed ? "Profil enregistré." : "Aucune modification.", "success");
    } catch (error) {
      $("#profile_errors").textContent = error.message; $("#profile_errors").classList.remove("hidden");
    } finally { button.disabled = false; }
  });

  $("#criterion_add").addEventListener("click", () => {
    $("#criteria_editor").insertAdjacentHTML("beforeend", criterionRow({ weight: 1, required: false, min_score: 60 }));
    const rows = document.querySelectorAll("[data-criterion]"); rows[rows.length - 1].querySelector("input").focus();
  });
  $("#criteria_editor").addEventListener("click", (event) => { const button = event.target.closest("[data-remove-criterion]"); if (button && document.querySelectorAll("[data-criterion]").length > 1) button.closest("[data-criterion]").remove(); });
  $("#profile_history").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-restore-profile]");
    if (!button || !window.confirm("Restaurer cette version du profil ?")) return;
    button.disabled = true;
    try {
      const result = await fetchJSON(`/api/profile/history/${button.dataset.restoreProfile}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision }) });
      profile = result.profile; revision = result.revision; renderProfile(); await loadHistory(); showToast("Version restaurée.", "success");
    } catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });

  function backupRow(item) {
    const size = item.size > 1024 * 1024 ? `${(item.size / 1024 / 1024).toFixed(1)} Mo` : `${Math.ceil(item.size / 1024)} Ko`;
    return `<div class="backup-row"><div><strong>${escapeHtml(item.name)}</strong><small class="muted">${formatDate(item.created_at)} · ${size}</small></div><a class="secondary-btn" href="/api/backups/${encodeURIComponent(item.name)}">Télécharger</a><button class="secondary-btn" data-delete="${escapeHtml(item.name)}">Supprimer</button></div>`;
  }
  async function loadBackups() {
    try { const payload = await fetchJSON("/api/backups"); $("#backup_list").innerHTML = payload.backups.length ? payload.backups.map(backupRow).join("") : '<div class="empty-state"><strong>Aucune sauvegarde</strong></div>'; }
    catch (error) { $("#backup_list").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  }
  $("#backup_create").addEventListener("click", async (event) => { const button = event.currentTarget; button.disabled = true; try { await fetchJSON("/api/backups", { method: "POST" }); await loadBackups(); showToast("Sauvegarde créée.", "success"); } catch (error) { showToast(error.message, "error"); } finally { button.disabled = false; } });
  $("#backup_list").addEventListener("click", async (event) => { const button = event.target.closest("[data-delete]"); if (!button || !window.confirm("Supprimer cette sauvegarde ?")) return; button.disabled = true; try { await fetchJSON(`/api/backups/${encodeURIComponent(button.dataset.delete)}`, { method: "DELETE" }); await loadBackups(); } catch (error) { showToast(error.message, "error"); button.disabled = false; } });
  $("#restore_form").addEventListener("submit", async (event) => { event.preventDefault(); const file = $("#restore_file").files[0]; const confirmation = $("#restore_confirmation").value.trim(); if (!file || confirmation !== "RESTAURER") { showToast("Sélectionne une archive et saisis RESTAURER.", "error"); return; } if (!window.confirm("Remplacer toutes les données persistantes par cette sauvegarde ?")) return; const button = event.submitter; button.disabled = true; const body = new FormData(); body.append("archive", file); body.append("confirmation", confirmation); try { await fetchJSON("/api/backups/restore", { method: "POST", body }); window.location.reload(); } catch (error) { showToast(error.message, "error"); button.disabled = false; } });

  renderProfile(); loadHistory(); loadBackups();
})();