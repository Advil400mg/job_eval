(() => {
  const { $, escapeHtml, fetchJSON, formatDate, showToast } = JEV;
  let profile = JSON.parse($("#profile_data").textContent);
  let revision = $("#profile_form").dataset.revision;
  const structured = profile.search?.policy_version === 2;

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
    $("#reject_experience_years").value = experience.reject_if_minimum_required_years_gte ?? (structured ? "" : 2);
    if (structured) {
      $("#preferred_locations").value = (search.preferred_locations || []).join("\n");
      $("#seniority").value = search.seniority || "any";
      const accepted = new Set(search.contract_types || []);
      [...$("#contract_types").options].forEach((option) => { option.selected = accepted.has(option.value); });
      $("#candidate_years").value = experience.candidate_years ?? "";
      const facts = profile.candidate_facts || {};
      $("#candidate_name").value = facts.name || "";
      $("#candidate_headline").value = facts.headline || "";
      $("#candidate_skills").value = (facts.skills || []).join("\n");
      $("#candidate_languages").value = facts.languages_line || "";
      $("#profile_confirmed").checked = !!search.confirmed;
    }
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
      reject_if_minimum_required_years_gte: structured && $("#reject_experience_years").value === "" ? null : Number($("#reject_experience_years").value),
      internships_count_as_professional_experience: $("#internships_count").checked,
      ...(structured ? { candidate_years: $("#candidate_years").value === "" ? null : Number($("#candidate_years").value) } : {}),
    };
    if (structured) {
      updated.search.preferred_locations = lines($("#preferred_locations").value);
      updated.search.seniority = $("#seniority").value;
      updated.search.contract_types = [...$("#contract_types").selectedOptions].map((option) => option.value);
      updated.search.confirmed = $("#profile_confirmed").checked;
      updated.candidate_facts = {
        name: $("#candidate_name").value.trim(), headline: $("#candidate_headline").value.trim(),
        skills: lines($("#candidate_skills").value), languages_line: $("#candidate_languages").value.trim(),
      };
    }
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

  let previewTimer;
  let previewRequest = 0;
  async function updatePreview() {
    if (!structured) return;
    const requestId = ++previewRequest;
    try {
      const result = await fetchJSON("/api/profile/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: collectProfile(), expected_revision: revision }),
      });
      if (requestId !== previewRequest) return;
      const context = result.profile_context;
      $("#profile_preview").textContent = [
        `Postes visés : ${context.target_roles.join(", ")}`,
        `Niveau : ${context.seniority} · Expérience déclarée : ${context.candidate_years ?? "inconnue"}`,
        `Lieux acceptés : ${context.accepted_locations.join(", ") || "tous"}`,
        `Lieux préférés : ${context.preferred_locations.join(", ") || "aucun"}`,
        `Contrats acceptés : ${context.contract_types.join(", ") || "tous"}`,
        `Langues déclarées : ${context.languages || "inconnues"}`,
        ...result.criteria.map((criterion) => `${criterion.name} : ${criterion.description}`),
      ].join("\n");
    } catch (error) {
      if (requestId === previewRequest) $("#profile_preview").textContent = "Aperçu indisponible : " + error.message;
    }
  }
  if (structured) $("#profile_form").addEventListener("input", () => {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(updatePreview, 350);
  });
  if (structured) $("#profile_form").addEventListener("change", () => {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(updatePreview, 350);
  });

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
      renderProfile(); await loadHistory(); await updatePreview(); showToast(result.changed ? "Profil enregistré." : "Aucune modification.", "success");
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
    if (!button) return;
    const confirmed = await JEV.confirmAction({
      title: "Restaurer le profil",
      message: "Restaurer cette version du profil ? La version actuelle restera dans l’historique.",
      confirmLabel: "Restaurer",
    });
    if (!confirmed) return;
    button.disabled = true;
    try {
      const result = await fetchJSON(`/api/profile/history/${button.dataset.restoreProfile}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision }) });
      profile = result.profile; revision = result.revision; $("#profile_form").dataset.revision = revision; renderProfile(); await loadHistory(); await updatePreview(); showToast("Version restaurée.", "success");
    } catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });

  function backupRow(item) {
    const size = item.size > 1024 * 1024 ? `${(item.size / 1024 / 1024).toFixed(1)} Mo` : `${Math.ceil(item.size / 1024)} Ko`;
    const kind = { manual: "manuelle", scheduled: "planifiée", "pre-restore": "avant restauration", "pre-deploy": "avant déploiement" }[item.kind] || item.kind || "inconnue";
    return `<div class="backup-row"><div><strong>${escapeHtml(item.name)}</strong><small class="muted">${formatDate(item.created_at)} · ${size} · ${escapeHtml(kind)}${item.manifest_valid ? " · manifeste valide" : " · manifeste illisible"}</small></div><a class="secondary-btn" href="/api/backups/${encodeURIComponent(item.name)}">Télécharger</a><button class="secondary-btn" data-verify="${escapeHtml(item.name)}">Vérifier</button><button class="secondary-btn" data-delete="${escapeHtml(item.name)}">Supprimer</button></div>`;
  }
  async function loadBackups() {
    try { const payload = await fetchJSON("/api/backups"); $("#backup_list").innerHTML = payload.backups.length ? payload.backups.map(backupRow).join("") : '<div class="empty-state"><strong>Aucune sauvegarde</strong></div>'; }
    catch (error) { $("#backup_list").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  }
  $("#backup_create").addEventListener("click", async (event) => { const button = event.currentTarget; button.disabled = true; try { await fetchJSON("/api/backups", { method: "POST" }); await loadBackups(); showToast("Sauvegarde créée.", "success"); } catch (error) { showToast(error.message, "error"); } finally { button.disabled = false; } });
  $("#backup_list").addEventListener("click", async (event) => {
    const verify = event.target.closest("[data-verify]");
    if (verify) {
      verify.disabled = true;
      try {
        await fetchJSON(`/api/backups/${encodeURIComponent(verify.dataset.verify)}/verify`, { method: "POST" });
        showToast("Sauvegarde vérifiée : archive et base SQLite intègres.", "success");
      } catch (error) { showToast(error.message, "error"); }
      finally { verify.disabled = false; }
      return;
    }
    const button = event.target.closest("[data-delete]");
    if (!button) return;
    const confirmed = await JEV.confirmAction({
      title: "Supprimer la sauvegarde",
      message: `Supprimer définitivement ${button.dataset.delete} ?`,
      confirmLabel: "Supprimer",
      danger: true,
    });
    if (!confirmed) return;
    button.disabled = true;
    try { await fetchJSON(`/api/backups/${encodeURIComponent(button.dataset.delete)}`, { method: "DELETE" }); await loadBackups(); }
    catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });
  $("#restore_form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#restore_file").files[0];
    const confirmation = $("#restore_confirmation").value.trim();
    if (!file || confirmation !== "RESTAURER") { showToast("Sélectionne une archive et saisis RESTAURER.", "error"); return; }
    const confirmed = await JEV.confirmAction({
      title: "Restaurer toutes les données",
      message: "Remplacer toutes les données persistantes par cette sauvegarde ? Une sauvegarde de sécurité sera créée avant le remplacement.",
      confirmLabel: "Restaurer",
      danger: true,
    });
    if (!confirmed) return;
    const button = event.submitter; button.disabled = true;
    const body = new FormData(); body.append("archive", file); body.append("confirmation", confirmation);
    try { await fetchJSON("/api/backups/restore", { method: "POST", body }); window.location.reload(); }
    catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });

  if (!structured) $("#profile_adopt").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const confirmed = await JEV.confirmAction({
      title: "Adopter un profil personnalisable",
      message: "Créer une nouvelle version à vérifier ? Votre profil actuel et les évaluations précédentes resteront dans l'historique. Aucune nouvelle évaluation ne sera lancée avant votre confirmation des faits, du niveau, des contrats et des critères.",
      confirmLabel: "Créer la version à vérifier",
    });
    if (!confirmed) return;
    button.disabled = true;
    try {
      await fetchJSON("/api/profile/adopt", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision }) });
      window.location.reload();
    } catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });

  renderProfile(); updatePreview(); loadHistory(); loadBackups();
})();