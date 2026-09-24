(() => {
  const { $, $$, escapeHtml, fetchJSON, statusBadge, scoreVisual, criteriaVisual,
    criteriaHtml, gatesHtml, paginationHtml, updateQuery, formatDate, generateCv } = JEV;
  const params = new URLSearchParams(location.search);
  const state = {
    page: Number(params.get("page")) || 1, page_size: 25,
    q: params.get("q") || "", status: params.get("status") || "",
    company: params.get("company") || "", location: params.get("location") || "",
    run_id: params.get("run_id") || "", score_min: params.get("score_min") || "",
    score_max: params.get("score_max") || "", scored: params.get("scored") || "",
    has_cv: params.get("has_cv") || "", view: params.get("view") || "latest",
    sort: params.get("sort") || "newest",
  };
  let debounce = null;

  function syncControls() {
    $("#filter_q").value = state.q; $("#filter_status").value = state.status;
    $("#filter_company").value = state.company; $("#filter_location").value = state.location;
    $("#filter_score_min").value = state.score_min; $("#filter_score_max").value = state.score_max;
    $("#filter_scored").value = state.scored; $("#filter_cv").value = state.has_cv;
    $("#filter_view").value = state.view; $("#sort").value = state.sort;
    const quick = state.status === "unverified" ? "review" : state.status;
    $$("[data-quick]").forEach((button) => button.classList.toggle("active", button.dataset.quick === quick));
  }

  function queryString() {
    const query = new URLSearchParams();
    Object.entries(state).forEach(([key, value]) => { if (value !== "") query.set(key, value); });
    return query.toString();
  }

  function offerCard(offer) {
    const issues = [];
    if (offer.blocking_criteria?.length) issues.push(`${offer.blocking_criteria.length} critère(s) bloquant(s)`);
    if (offer.gate_failures?.length) issues.push(`${offer.gate_failures.length} porte(s) en échec`);
    if (offer.low_confidence_criteria?.length) issues.push("confiance faible");
    if (offer.error) issues.push("détail de l’erreur disponible");
    return `<article class="offer-row" data-url="${escapeHtml(offer.url)}" tabindex="0">
      <div class="offer-identity"><div class="offer-title-line"><a href="${escapeHtml(offer.url)}" target="_blank" rel="noopener" data-external>${escapeHtml(offer.title || offer.url)}</a>${offer.evaluation_count > 1 ? `<span class="count-badge">${offer.evaluation_count} évaluations</span>` : ""}</div><strong>${escapeHtml(offer.company || "Entreprise inconnue")}</strong><span>${escapeHtml(offer.location || "Localisation inconnue")} · évaluée le ${formatDate(offer.evaluated_at)}</span><div class="offer-issues">${issues.length ? issues.map((issue) => `<span>${escapeHtml(issue)}</span>`).join("") : '<span class="positive">aucun blocage détecté</span>'}</div></div>
      <div class="offer-score">${scoreVisual(offer.score, offer.minimum_global_score, true)}</div>
      <div class="offer-criteria">${criteriaVisual(offer.criteria, offer.minimum_confidence)}</div>
      <div class="offer-status">${statusBadge(offer.status)}<span>${offer.published_at ? `publiée ${escapeHtml(offer.published_at)}` : "date non prouvée"}</span></div>
      <div class="offer-actions"><button class="icon-btn" data-open-offer title="Voir le détail">→</button></div>
    </article>`;
  }

  function fillSelect(select, rows, selected) {
    const first = select.options[0].outerHTML;
    select.innerHTML = first + rows.map((row) => `<option value="${escapeHtml(row[Object.keys(row)[0]])}">${escapeHtml(row[Object.keys(row)[0]])} (${row.count})</option>`).join("");
    select.value = selected;
  }

  function activeFiltersText() {
    const labels = [];
    if (state.q) labels.push(`recherche « ${state.q} »`);
    if (state.status) labels.push($("#filter_status").selectedOptions[0]?.textContent);
    if (state.company) labels.push(state.company);
    if (state.location) labels.push(state.location);
    if (state.score_min) labels.push(`score ≥ ${state.score_min}`);
    if (state.score_max) labels.push(`score ≤ ${state.score_max}`);
    if (state.run_id) labels.push(`lot ${state.run_id}`);
    return labels.length ? `· ${labels.join(" · ")}` : "";
  }

  async function loadOffers(push = false) {
    $("#offers_list").classList.add("loading");
    updateQuery(state, !push);
    try {
      const payload = await fetchJSON(`/api/offers?${queryString()}`);
      $("#offers_total").textContent = `${payload.total} offre${payload.total > 1 ? "s" : ""}`;
      $("#active_filters").textContent = activeFiltersText();
      $("#offers_list").innerHTML = payload.offers.length ? payload.offers.map(offerCard).join("") : '<div class="empty-state"><strong>Aucune offre</strong><p>Modifiez les filtres ou lancez une nouvelle évaluation.</p></div>';
      $("#offers_pagination").innerHTML = paginationHtml(payload.page, payload.pages);
      fillSelect($("#filter_company"), payload.facets.companies, state.company);
      fillSelect($("#filter_location"), payload.facets.locations, state.location);
    } catch (error) {
      $("#offers_list").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    } finally { $("#offers_list").classList.remove("loading"); }
  }

  function historyLine(item) {
    return `<a href="/runs/${item.run_id}" class="history-line"><span>${formatDate(item.evaluated_at)}</span>${statusBadge(item.status)}<strong>${typeof item.score === "number" ? item.score.toFixed(1) : "—"}</strong></a>`;
  }

  async function openDrawer(url) {
    const drawer = $("#offer_drawer"), backdrop = $("#offer_drawer_backdrop");
    drawer.setAttribute("aria-hidden", "false"); drawer.classList.add("open"); backdrop.classList.remove("hidden");
    $("#offer_detail").innerHTML = '<div class="loading-card">Chargement du détail…</div>';
    const payload = await fetchJSON(`/api/offers/history?url=${encodeURIComponent(url)}`);
    const offer = payload.offer;
    $("#offer_detail").innerHTML = `<div class="drawer-title"><p class="eyebrow">${escapeHtml(offer.company || "Offre")}</p><h2>${escapeHtml(offer.title || offer.url)}</h2><p>${escapeHtml(offer.location || "Localisation inconnue")}</p></div><div class="drawer-score">${scoreVisual(offer.score, offer.minimum_global_score)}</div><div class="drawer-status">${statusBadge(offer.status)}<a href="${escapeHtml(offer.url)}" target="_blank" rel="noopener">Voir l’offre source ↗</a></div>${offer.error ? `<div class="error">${escapeHtml(offer.error)}</div>` : ""}<section><h3>Décision</h3>${offer.blocking_criteria?.length ? `<p>Critères bloquants : ${offer.blocking_criteria.map((item) => `<code>${escapeHtml(item)}</code>`).join(" ")}</p>` : '<p class="muted">Aucun critère obligatoire bloquant.</p>'}${gatesHtml(offer.gates)}</section><section><h3>Critères Jev</h3>${criteriaHtml(offer.criteria, offer.minimum_confidence)}</section><section><h3>CV</h3><div class="drawer-actions">${offer.cv ? `<a class="secondary-btn" href="/api/cv/${offer.cv.job_id}/pdf" target="_blank">Télécharger le CV existant</a>` : ""}<button data-drawer-cv>Générer PDF</button><button class="secondary-btn" data-drawer-email>PDF + email</button></div></section><section><h3>Historique · ${payload.history.length} évaluation(s)</h3><div class="history-lines">${payload.history.map(historyLine).join("")}</div></section>`;
    $("[data-drawer-cv]").addEventListener("click", (event) => generateCv(offer.url, false, event.currentTarget));
    $("[data-drawer-email]").addEventListener("click", (event) => generateCv(offer.url, true, event.currentTarget));
  }

  function closeDrawer() {
    $("#offer_drawer").classList.remove("open"); $("#offer_drawer").setAttribute("aria-hidden", "true"); $("#offer_drawer_backdrop").classList.add("hidden");
  }

  const controlMap = { filter_status: "status", filter_company: "company", filter_location: "location", filter_score_min: "score_min", filter_score_max: "score_max", filter_scored: "scored", filter_cv: "has_cv", filter_view: "view", sort: "sort" };
  Object.entries(controlMap).forEach(([id, key]) => $("#" + id).addEventListener("change", (event) => { state[key] = event.target.value; state.page = 1; loadOffers(true); }));
  $("#filter_q").addEventListener("input", (event) => { clearTimeout(debounce); debounce = setTimeout(() => { state.q = event.target.value.trim(); state.page = 1; loadOffers(true); }, 300); });
  $("#filters_reset").addEventListener("click", () => { Object.assign(state, { page: 1, q: "", status: "", company: "", location: "", run_id: "", score_min: "", score_max: "", scored: "", has_cv: "", view: "latest", sort: "newest" }); syncControls(); loadOffers(true); });
  $("#quick_filters").addEventListener("click", (event) => { const button = event.target.closest("[data-quick]"); if (!button) return; state.status = button.dataset.quick === "review" ? "unverified" : button.dataset.quick; state.page = 1; syncControls(); loadOffers(true); });
  $("#offers_pagination").addEventListener("click", (event) => { const button = event.target.closest("[data-page]"); if (!button || button.disabled) return; state.page = Number(button.dataset.page); loadOffers(true); window.scrollTo({ top: 0, behavior: "smooth" }); });
  $("#offers_list").addEventListener("click", (event) => { if (event.target.closest("[data-external]")) return; const row = event.target.closest("[data-url]"); if (row) openDrawer(row.dataset.url).catch((error) => JEV.showToast(error.message, "error")); });
  $("#offers_list").addEventListener("keydown", (event) => { if (event.key === "Enter" && event.target.matches("[data-url]")) openDrawer(event.target.dataset.url); });
  $("#drawer_close").addEventListener("click", closeDrawer); $("#offer_drawer_backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
  $("#filters_open").addEventListener("click", () => $("#filters").classList.add("open")); $("#filters_close").addEventListener("click", () => $("#filters").classList.remove("open"));
  window.addEventListener("popstate", () => location.reload());
  syncControls(); loadOffers();
})();
