(() => {
  const { $, escapeHtml, fetchJSON, formatDate, showToast } = JEV;

  function row(item) {
    const size = item.size > 1024 * 1024 ? `${(item.size / 1024 / 1024).toFixed(1)} Mo` : `${Math.ceil(item.size / 1024)} Ko`;
    return `<div class="backup-row"><div><strong>${escapeHtml(item.name)}</strong><small class="muted">${formatDate(item.created_at)} · ${size}</small></div><a class="secondary-btn" href="/api/backups/${encodeURIComponent(item.name)}">Télécharger</a><button class="secondary-btn" data-delete="${escapeHtml(item.name)}">Supprimer</button></div>`;
  }

  async function load() {
    try {
      const payload = await fetchJSON("/api/backups");
      $("#backup_list").innerHTML = payload.backups.length ? payload.backups.map(row).join("") : '<div class="empty-state"><strong>Aucune sauvegarde</strong><p>Crée une archive avant une opération importante.</p></div>';
    } catch (error) {
      $("#backup_list").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    }
  }

  $("#backup_create").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await fetchJSON("/api/backups", { method: "POST" });
      showToast("Sauvegarde créée.", "success");
      await load();
    } catch (error) { showToast(error.message, "error"); }
    finally { button.disabled = false; }
  });

  $("#backup_list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete]");
    if (!button || !window.confirm("Supprimer cette sauvegarde ?")) return;
    button.disabled = true;
    try {
      await fetchJSON(`/api/backups/${encodeURIComponent(button.dataset.delete)}`, { method: "DELETE" });
      showToast("Sauvegarde supprimée.", "success");
      await load();
    } catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });

  $("#restore_form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#restore_file").files[0];
    const confirmation = $("#restore_confirmation").value.trim();
    if (!file || confirmation !== "RESTAURER") {
      showToast("Sélectionne une archive et saisis RESTAURER.", "error");
      return;
    }
    if (!window.confirm("Remplacer toutes les données persistantes par cette sauvegarde ?")) return;
    const button = event.submitter;
    button.disabled = true;
    const body = new FormData();
    body.append("archive", file);
    body.append("confirmation", confirmation);
    try {
      await fetchJSON("/api/backups/restore", { method: "POST", body });
      showToast("Restauration terminée. Rechargement…", "success");
      setTimeout(() => window.location.reload(), 800);
    } catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });

  load();
})();
