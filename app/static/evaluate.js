(() => {
  const { $, escapeHtml, fetchJSON, statusBadge, scoreVisual, formatDate } = JEV;
  const textarea = $("#urls");
  let activePoller = null;

  function parsedUrls() {
    const values = textarea.value.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean);
    const valid = [], invalid = [], seen = new Set();
    for (const value of values) {
      try {
        const url = new URL(value);
        if (!/^https?:$/.test(url.protocol)) throw new Error();
        [...url.searchParams.keys()].forEach((key) => {
          if (key.toLowerCase().startsWith("utm_") || ["fbclid", "gclid", "ref"].includes(key.toLowerCase())) url.searchParams.delete(key);
        });
        url.hash = "";
        const key = url.toString().replace(/\/$/, "");
        if (!seen.has(key)) { seen.add(key); valid.push(value); }
      } catch (_) { invalid.push(value); }
    }
    return { valid, invalid, duplicates: values.length - valid.length - invalid.length };
  }

  function updateCount() {
    const parsed = parsedUrls();
    $("#url_count").textContent = `${parsed.valid.length} URL${parsed.valid.length > 1 ? "s" : ""}`;
    const messages = [];
    if (parsed.duplicates) messages.push(`${parsed.duplicates} doublon${parsed.duplicates > 1 ? "s" : ""} ignoré${parsed.duplicates > 1 ? "s" : ""}`);
    if (parsed.invalid.length) messages.push(`${parsed.invalid.length} URL invalide${parsed.invalid.length > 1 ? "s" : ""}`);
    $("#url_feedback").innerHTML = messages.map((message) => `<span>${escapeHtml(message)}</span>`).join("");
  }

  function runCard(run) {
    const progress = run.total ? Math.round((run.progress / run.total) * 100) : 0;
    return `<a class="run-card" href="/runs/${run.id}"><div class="run-card-main"><div><strong>Lot du ${formatDate(run.created_at)}</strong><span>${run.offers || run.progress}/${run.total} offre(s)</span></div>${statusBadge(run.status)}</div><div class="run-metrics"><span><b>${run.qualified || 0}</b> qualifiées</span><span><b>${run.rejected || 0}</b> refusées</span><span><b>${run.errors || 0}</b> erreurs</span><span><b>${run.best_score ?? "—"}</b> meilleur score</span></div>${run.status === "running" ? `<div class="progress"><span style="width:${progress}%"></span></div>` : ""}</a>`;
  }

  async function loadRecent() {
    const payload = await fetchJSON("/api/history?page_size=5");
    $("#recent_runs").innerHTML = payload.runs.length ? payload.runs.map(runCard).join("") : '<div class="empty-state"><strong>Aucun lot</strong><p>Les évaluations apparaîtront ici.</p></div>';
    const running = payload.runs.find((run) => run.status === "running");
    if (running) watchRun(running.id);
  }

  function watchRun(runId) {
    if (activePoller) clearInterval(activePoller);
    const panel = $("#active_run");
    panel.classList.remove("hidden");
    const tick = async () => {
      const run = await fetchJSON(`/api/runs/${runId}`);
      const progress = run.total ? Math.round((run.progress / run.total) * 100) : 0;
      panel.innerHTML = `<div class="section-heading"><div><h2>Lot en cours</h2><p>${run.progress}/${run.total} offres traitées</p></div><a href="/runs/${run.id}">Voir le détail</a></div><div class="progress large"><span style="width:${progress}%"></span></div><div class="live-scores">${(run.results || []).slice(-4).reverse().map((item) => `<div><span>${escapeHtml(item.title || item.url)}</span>${scoreVisual(item.jev?.global_score, item.jev?.minimum_global_score, true)}</div>`).join("")}</div>`;
      if (run.status !== "running") { clearInterval(activePoller); activePoller = null; loadRecent(); JEV.refreshNavBadges(); }
    };
    tick(); activePoller = setInterval(tick, 1800);
  }

  async function startRun() {
    const parsed = parsedUrls();
    if (!parsed.valid.length || parsed.invalid.length) {
      $("#status").textContent = parsed.invalid.length ? "Corrigez les URLs invalides." : "Ajoutez au moins une URL.";
      return;
    }
    $("#run").disabled = true; $("#status").textContent = "Création du lot…";
    try {
      const result = await fetchJSON("/api/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ urls: parsed.valid }) });
      window.location.href = result.url;
    } catch (error) {
      $("#status").textContent = error.message; $("#run").disabled = false;
    }
  }

  textarea.addEventListener("input", updateCount);
  $("#run").addEventListener("click", startRun);
  updateCount(); loadRecent().catch((error) => { $("#recent_runs").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; });
})();
