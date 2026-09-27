(() => {
  const { $, escapeHtml, fetchJSON, formatDate } = JEV;
  const bytes = (value) => {
    let size = Number(value) || 0;
    const units = ["o", "Ko", "Mo", "Go", "To"];
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index++; }
    return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
  };
  const valueRows = (rows) => rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? "—")}</dd></div>`).join("");
  const counts = (items = {}) => Object.entries(items).map(([status, count]) => `<span class="admin-pill">${escapeHtml(status)} : ${count}</span>`).join(" ") || '<span class="muted">Aucune tâche</span>';

  function render(payload) {
    $("#diagnostics_status").className = `diagnostics-status is-${payload.status}`;
    $("#diagnostics_status").textContent = `État global : ${payload.status === "ok" ? "sain" : payload.status === "warning" ? "attention requise" : "erreur"} · généré ${formatDate(payload.generated_at)}`;
    $("#diagnostics_checks").innerHTML = payload.checks.map((check) => `<article class="diagnostic-check is-${escapeHtml(check.status)}"><span>${check.status === "ok" ? "✓" : check.status === "warning" ? "!" : "×"}</span><div><strong>${escapeHtml(check.label)}</strong><p>${escapeHtml(check.detail)}</p></div></article>`).join("");
    $("#diagnostics_app").innerHTML = valueRows([
      ["Version JEV", payload.app.version], ["Schéma SQLite", payload.app.schema_version],
      ["PRAGMA quick_check", payload.database.quick_check], ["Base", payload.database.path_name],
      ["Taille de la base", bytes(payload.database.size)], ["Journal WAL", bytes(payload.database.wal_size)],
      ["Mémoire partagée", bytes(payload.database.shm_size)], ["Comptes actifs", `${payload.users.active} / ${payload.users.total}`],
    ]);
    $("#diagnostics_storage").innerHTML = valueRows([
      ["Disque total", bytes(payload.disk.total)], ["Utilisé", bytes(payload.disk.used)], ["Disponible", bytes(payload.disk.free)],
      ["Répertoires attendus", payload.storage.expected_user_directories], ["Répertoires présents", payload.storage.present_user_directories],
      ["Manquants", payload.storage.missing_user_directories.join(", ") || "Aucun"], ["Orphelins", payload.storage.orphan_user_directories.join(", ") || "Aucun"],
      ["Suppressions en attente", payload.storage.pending_deletions.join(", ") || "Aucune"],
    ]);
    $("#diagnostics_jobs").innerHTML = `<div class="diagnostic-job"><strong>Évaluations</strong><div>${counts(payload.jobs.runs)}</div></div><div class="diagnostic-job"><strong>CV</strong><div>${counts(payload.jobs.cv)}</div></div><div class="diagnostic-job"><strong>Initialisations</strong><div>${counts(payload.jobs.onboarding)}</div></div>`;
    const latest = payload.backups.latest;
    const scheduled = payload.backups.latest_scheduled;
    $("#diagnostics_backups").innerHTML = valueRows([
      ["Archives", payload.backups.count], ["Taille totale", bytes(payload.backups.total_size)],
      ["Rétention", `${payload.backups.retention_days} jours`], ["Seuil d’alerte", `${payload.backups.stale_after_hours} heures`],
      ["Dernière sauvegarde", latest ? `${formatDate(latest.created_at)} (${latest.kind})` : "Aucune"],
      ["Dernière planifiée", scheduled ? formatDate(scheduled.created_at) : "Aucune"],
    ]);
    $("#diagnostics_capabilities").textContent = payload.capabilities.note;
  }

  async function load(force = false) {
    const button = $("#diagnostics_refresh"); button.disabled = true;
    try { render(await fetchJSON(`/api/admin/diagnostics${force ? "?refresh=true" : ""}`)); }
    catch (error) { $("#diagnostics_status").className = "diagnostics-status is-error"; $("#diagnostics_status").textContent = error.message; }
    finally { button.disabled = false; }
  }
  $("#diagnostics_refresh").addEventListener("click", () => load(true));
  load();
})();
