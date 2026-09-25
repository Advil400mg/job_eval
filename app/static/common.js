(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const num = (value, digits = 1) => typeof value === "number" ? value.toFixed(digits) : "—";
  const formatDate = (value) => value ? String(value).replace("T", " ") : "—";

  async function fetchJSON(url, options) {
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* non-JSON error */ }
    if (!response.ok) {
      if (response.status === 401) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?next=${next}`;
      }
      const detail = typeof payload.detail === "string" ? payload.detail
        : payload.detail?.message || `Erreur HTTP ${response.status}`;
      throw new Error(detail);
    }
    return payload;
  }

  const statusMap = {
    qualified: ["Qualifiée", "ok"],
    jev_excluded: ["Exclue par une porte", "warn"],
    rejected: ["Refusée Jev", "bad"],
    unverified: ["Non vérifiée", "unknown"],
    error: ["Erreur technique", "unknown"],
    running: ["En cours", "running"],
    done: ["Terminé", "ok"],
    failed: ["Échec", "bad"],
    interrupted: ["Interrompu", "warn"],
    cancelled: ["Annulé", "unknown"],
  };
  function statusBadge(status) {
    const [label, css] = statusMap[status] || [status || "Inconnu", "unknown"];
    return `<span class="badge ${css}">${escapeHtml(label)}</span>`;
  }

  function scoreVisual(score, threshold = 68, compact = false) {
    if (typeof score !== "number") {
      return `<div class="score-visual ${compact ? "compact" : ""} score-na"><strong>—</strong><span>sans score</span></div>`;
    }
    const safeScore = Math.max(0, Math.min(100, score));
    const safeThreshold = Math.max(0, Math.min(100, threshold ?? 68));
    const css = score >= safeThreshold ? "pass" : "fail";
    return `<div class="score-visual ${compact ? "compact" : ""} ${css}" aria-label="Score ${num(score)} sur 100, seuil ${safeThreshold}">
      <div class="score-number"><strong>${num(score)}</strong><span>/100</span></div>
      <div class="score-track"><span style="width:${safeScore}%"></span><i style="left:${safeThreshold}%" title="seuil ${safeThreshold}"></i></div>
      <small>seuil ${safeThreshold}</small>
    </div>`;
  }

  function criteriaVisual(criteria = [], minimumConfidence = 0.5) {
    if (!criteria.length) return '<span class="muted">aucun critère</span>';
    const blocks = criteria.map((criterion) => {
      const low = typeof criterion.confidence === "number" && criterion.confidence < minimumConfidence;
      const css = criterion.required && !criterion.passed ? "bad" : low ? "warn" : "ok";
      return `<span class="criterion-dot ${css}" title="${escapeHtml(criterion.name || criterion.id)} : ${num(criterion.score)}/100 · confiance ${num(criterion.confidence, 2)}"></span>`;
    }).join("");
    const blocking = criteria.filter((criterion) => criterion.required && !criterion.passed).length;
    const low = criteria.filter((criterion) => typeof criterion.confidence === "number" && criterion.confidence < minimumConfidence).length;
    const label = blocking ? `${blocking} bloquant${blocking > 1 ? "s" : ""}`
      : low ? `${low} confiance${low > 1 ? "s" : ""} faible${low > 1 ? "s" : ""}` : "critères satisfaits";
    return `<div class="criteria-visual"><div>${blocks}</div><small>${label}</small></div>`;
  }

  function gatesHtml(gates = []) {
    if (!gates.length) return '<p class="muted">Aucune porte enregistrée.</p>';
    return `<div class="gate-list">${gates.map((gate) => {
      const symbol = { pass: "✓", fail: "×", warn: "!" }[gate.status] || "?";
      return `<div class="gate-row ${escapeHtml(gate.status)}"><span>${symbol}</span><div><strong>${escapeHtml(gate.gate)}</strong><p>${escapeHtml(gate.reason)}</p></div></div>`;
    }).join("")}</div>`;
  }

  function criteriaHtml(criteria = [], minimumConfidence = 0.5) {
    if (!criteria.length) return '<p class="muted">Aucun critère enregistré.</p>';
    return `<div class="criterion-list">${criteria.map((criterion) => {
      const low = typeof criterion.confidence === "number" && criterion.confidence < minimumConfidence;
      const css = criterion.required && !criterion.passed ? "bad" : low ? "warn" : "ok";
      const score = Math.max(0, Math.min(100, criterion.score || 0));
      return `<div class="criterion-row ${css}"><div class="criterion-copy"><strong>${escapeHtml(criterion.name || criterion.id)}</strong><code>${escapeHtml(criterion.id)}</code><span>${criterion.required ? `obligatoire · seuil ${criterion.min_score}` : "non obligatoire"}${low ? " · confiance faible" : ""}</span></div><div class="criterion-score"><strong>${num(criterion.score)}</strong><div class="mini-track"><span style="width:${score}%"></span></div><small>confiance ${num(criterion.confidence, 2)}</small></div></div>`;
    }).join("")}</div>`;
  }

  function paginationHtml(page, pages) {
    if (pages <= 1) return "";
    const buttons = [];
    buttons.push(`<button data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>←</button>`);
    const start = Math.max(1, page - 2);
    const end = Math.min(pages, page + 2);
    if (start > 1) buttons.push('<button data-page="1">1</button><span>…</span>');
    for (let current = start; current <= end; current++) {
      buttons.push(`<button data-page="${current}" class="${current === page ? "active" : ""}">${current}</button>`);
    }
    if (end < pages) buttons.push(`<span>…</span><button data-page="${pages}">${pages}</button>`);
    buttons.push(`<button data-page="${page + 1}" ${page >= pages ? "disabled" : ""}>→</button>`);
    return buttons.join("");
  }

  function showToast(message, kind = "info") {
    const region = $("#toast_region");
    if (!region) return;
    const toast = document.createElement("div");
    toast.className = `toast ${kind}`;
    toast.textContent = message;
    region.append(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  function updateQuery(values, replace = true) {
    const url = new URL(window.location.href);
    Object.entries(values).forEach(([key, value]) => {
      if (value === "" || value === null || value === undefined) url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    });
    history[replace ? "replaceState" : "pushState"]({}, "", url);
  }

  async function generateCv(url, sendEmail, button) {
    const previous = button?.textContent;
    if (button) { button.disabled = true; button.textContent = "Lancement…"; }
    try {
      const job = await fetchJSON("/api/cv", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, send_email: !!sendEmail }),
      });
      showToast(`CV lancé${sendEmail ? " avec envoi email" : ""}.`, "success");
      pollCv(job.job_id);
      await refreshNavBadges();
      return job;
    } catch (error) {
      showToast(error.message, "error");
      throw error;
    } finally {
      if (button) { button.disabled = false; button.textContent = previous; }
    }
  }

  const cvPollers = new Set();
  function pollCv(jobId) {
    if (cvPollers.has(jobId)) return;
    cvPollers.add(jobId);
    const tick = async () => {
      try {
        const job = await fetchJSON(`/api/cv/${jobId}`);
        document.dispatchEvent(new CustomEvent("jev:cv-updated", { detail: job }));
        if (job.status === "running") return;
        clearInterval(timer);
        cvPollers.delete(jobId);
        showToast(job.status === "done" ? "CV prêt au téléchargement." : "La génération du CV a échoué.", job.status === "done" ? "success" : "error");
        refreshNavBadges();
      } catch (_) { /* transient network error: keep polling */ }
    };
    const timer = setInterval(tick, 3000);
    tick();
  }

  async function refreshNavBadges() {
    try {
      const [runs, cvs] = await Promise.all([
        fetchJSON("/api/history?status=running&page_size=5"),
        fetchJSON("/api/cv?status=running&limit=20"),
      ]);
      const runBadge = $("#nav_runs_badge");
      const cvBadge = $("#nav_cv_badge");
      if (runBadge) { runBadge.textContent = runs.total; runBadge.classList.toggle("hidden", !runs.total); }
      if (cvBadge) { cvBadge.textContent = cvs.total; cvBadge.classList.toggle("hidden", !cvs.total); }
      (cvs.jobs || []).forEach((job) => pollCv(job.id));
    } catch (_) { /* navigation remains usable offline */ }
  }

  window.JEV = {
    $, $$, escapeHtml, num, formatDate, fetchJSON, statusBadge, scoreVisual,
    criteriaVisual, criteriaHtml, gatesHtml, paginationHtml, showToast,
    updateQuery, generateCv, pollCv, refreshNavBadges,
  };
  refreshNavBadges();
  setInterval(refreshNavBadges, 15000);
})();
