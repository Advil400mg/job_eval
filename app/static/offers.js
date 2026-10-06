(() => {
  const { $, $$, escapeHtml, fetchJSON, statusBadge, scoreVisual, criteriaVisual,
    criteriaHtml, gatesHtml, paginationHtml, updateQuery, formatDate, generateCv,
    applicationStatusBadge, showToast, trapFocus, offerReason } = JEV;
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
  let drawerTrigger = null;
  let drawerRequest = 0;

  function syncControls() {
    $("#filter_q").value = state.q; $("#filter_status").value = state.status;
    $("#filter_company").value = state.company; $("#filter_location").value = state.location;
    $("#filter_score_min").value = state.score_min; $("#filter_score_max").value = state.score_max;
    $("#filter_scored").value = state.scored; $("#filter_cv").value = state.has_cv;
    $("#filter_view").value = state.view; $("#sort").value = state.sort;
    const quick = state.status === "review_required" ? "review" : state.status;
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
    return `<article class="offer-row" data-url="${escapeHtml(offer.url)}" tabindex="0" role="button" aria-label="Ouvrir le détail de ${escapeHtml(offer.title || offer.url)}">
      <div class="offer-identity"><div class="offer-title-line"><a href="${escapeHtml(offer.url)}" target="_blank" rel="noopener" data-external>${escapeHtml(offer.title || offer.url)}</a>${offer.evaluation_count > 1 ? `<span class="count-badge">${offer.evaluation_count} évaluations</span>` : ""}</div><strong>${escapeHtml(offer.company || "Entreprise inconnue")}</strong><span>${escapeHtml(offer.location || "Localisation inconnue")} · évaluée le ${formatDate(offer.evaluated_at)}</span><div class="offer-issues">${issues.length ? issues.map((issue) => `<span>${escapeHtml(issue)}</span>`).join("") : offer.status === "qualified" ? '<span class="positive">qualifiée pour le profil utilisé</span>' : '<span>analyse à consulter</span>'}</div><p class="offer-reason">${escapeHtml(offerReason(offer))}</p></div>
      <div class="offer-score">${scoreVisual(offer.score, offer.minimum_global_score, true)}</div>
      <div class="offer-criteria">${criteriaVisual(offer.criteria, offer.minimum_confidence)}</div>
      <div class="offer-status">${statusBadge(offer.status)}${offer.application ? applicationStatusBadge(offer.application.status) : ""}<span>${offer.published_at ? `publiée ${escapeHtml(offer.published_at)}` : "date non prouvée"}</span></div>
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

  function factsHtml(offer) {
    const names = { contract: "Contrat", experience_min: "Expérience minimale",
      experience_max: "Expérience maximale", experience_preferred: "Expérience souhaitée",
      junior: "Accès junior" };
    const rows = Object.entries(names).map(([key, name]) => {
      const fact = offer.facts?.[key];
      if (!fact) return "";
      const value = fact.status !== "known" ? "À vérifier"
        : typeof fact.value === "boolean" ? (fact.value ? "Oui" : "Non")
        : typeof fact.value === "number" ? `${fact.value} an(s)` : String(fact.value);
      return `<div class="fact-row"><strong>${name}</strong><span>${escapeHtml(value)}${fact.status === "contradictory" ? " · contradictoire" : ""}</span>${fact.evidence ? `<small>« ${escapeHtml(fact.evidence)} »</small>` : ""}</div>`;
    }).join("");
    const missing = (offer.missing_information || []).filter((item) => !names[item.field]);
    return rows || missing.length ? `<section><h3>Faits et informations manquantes</h3><div class="fact-list">${rows}${missing.map((item) => `<div class="fact-row"><strong>${escapeHtml(item.field)}</strong><span>À vérifier</span>${item.evidence ? `<small>« ${escapeHtml(item.evidence)} »</small>` : ""}</div>`).join("")}</div></section>` : "";
  }

  function reviewHtml(offer) {
    const reasons = offer.review_reasons || [];
    const reservations = offer.confidence_reservations || [];
    if (!reasons.length && !reservations.length) return "";
    return `<section><h3>Réserves et revue</h3>${reasons.length ? `<ul class="review-reasons">${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>` : ""}${reservations.length ? `<p class="muted">Confiance à contrôler : ${reservations.map(escapeHtml).join(" ; ")}</p>` : ""}</section>`;
  }

  function feedbackHtml(offer) {
    if (!offer.run_id || !offer.url) return "";
    return `<section><h3>Votre retour sur cette évaluation</h3><form id="feedback_form"><label>Verdict corrigé<select name="verdict" required><option value="">Choisir…</option><option value="correct">Évaluation correcte</option><option value="false_positive">Qualifiée à tort</option><option value="false_negative">Refusée à tort</option><option value="bad_extraction">Extraction incorrecte</option><option value="bad_reason">Justification incorrecte</option></select></label><label>Précision facultative<textarea name="note" maxlength="2000" rows="3"></textarea></label><div class="action-row"><button type="submit">Enregistrer le retour</button><span id="feedback_state" role="status">Chargement…</span></div></form></section>`;
  }

  function historyLine(item) {
    return `<a href="/runs/${item.run_id}" class="history-line"><span>${formatDate(item.evaluated_at)}</span>${statusBadge(item.status)}<strong>${typeof item.score === "number" ? item.score.toFixed(1) : "—"}</strong></a>`;
  }

  async function bindFeedback(offer) {
    const form = $("#feedback_form");
    if (!form) return;
    const status = $("#feedback_state", form);
    const button = $("button[type='submit']", form);
    button.disabled = true;
    const endpoint = `/api/evaluations/${encodeURIComponent(offer.run_id)}/feedback`;
    let revision = 0;
    try {
      const result = await fetchJSON(`${endpoint}?url=${encodeURIComponent(offer.url)}`);
      if (!form.isConnected) return;
      if (result.feedback) {
        $("select[name='verdict']", form).value = result.feedback.verdict;
        $("textarea[name='note']", form).value = result.feedback.note || "";
        revision = result.feedback.revision;
        status.textContent = "Retour précédent chargé.";
      } else status.textContent = "Aucun retour enregistré.";
      button.disabled = false;
    } catch (error) {
      if (form.isConnected) { status.textContent = `Retour indisponible : ${error.message}`; status.classList.add("error"); }
      return;
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); button.disabled = true; status.textContent = "Enregistrement…";
      try {
        const saved = await fetchJSON(endpoint, { method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: offer.url,
            verdict: $("select[name='verdict']", form).value,
            note: $("textarea[name='note']", form).value, revision }),
        });
        revision = saved.feedback.revision;
        status.classList.remove("error"); status.textContent = "Retour enregistré.";
      } catch (error) {
        status.textContent = error.message; status.classList.add("error");
      } finally { button.disabled = false; }
    });
  }

  async function openDrawer(url) {
    const drawer = $("#offer_drawer"), backdrop = $("#offer_drawer_backdrop");
    if (!drawer.classList.contains("open")) drawerTrigger = document.activeElement;
    drawer.setAttribute("aria-hidden", "false"); drawer.classList.add("open"); backdrop.classList.remove("hidden");
    $("#offer_detail").innerHTML = '<div class="loading-card">Chargement du détail…</div>';
    const requestId = ++drawerRequest;
    let payload;
    try {
      payload = await fetchJSON(`/api/offers/history?url=${encodeURIComponent(url)}`);
    } catch (error) {
      if (requestId === drawerRequest && drawer.classList.contains("open")) {
        $("#offer_detail").innerHTML = `<div class="error" role="alert">${escapeHtml(error.message)}<p>Fermez ce panneau et réessayez pour charger l’analyse.</p></div>`;
        $("#drawer_close").focus();
      }
      return;
    }
    if (requestId !== drawerRequest || !drawer.classList.contains("open")) return;
    const offer = payload.offer;
    updateQuery({ open: url });
    const cvReady = document.body.dataset.cvAvailable === "true";
    const cvDisabled = cvReady ? "" : " disabled title=\"Génération de CV indisponible pour ce profil ou cette instance\"";
    $("#offer_detail").innerHTML = `
      <div class="analysis-hero">
        <div class="drawer-title"><p class="eyebrow">${escapeHtml(offer.company || "Analyse d’offre")}</p><h2>${escapeHtml(offer.title || offer.url)}</h2><p>${escapeHtml(offer.location || "Localisation inconnue")}</p></div>
        <div class="drawer-status">${statusBadge(offer.status)}<a href="${escapeHtml(offer.url)}" target="_blank" rel="noopener">Voir l’offre source ↗</a></div>
        <div class="analysis-overview"><div><h3>Ce que cette évaluation indique</h3><p class="offer-reason-v3">${escapeHtml(offerReason(offer))}</p><p class="analysis-warning">Le verdict, les conditions d’éligibilité et la confiance sont distincts du score. Une qualification ne garantit pas un recrutement.</p></div><div class="drawer-score">${scoreVisual(offer.score, offer.minimum_global_score)}</div></div>
        ${offer.error ? `<div class="error">${escapeHtml(offer.error)}</div>` : ""}
      </div>
      <div class="analysis-layout">
        <div class="analysis-column">
          <section><h3>Conditions d’éligibilité</h3>${gatesHtml(offer.gates)}</section>
          ${reviewHtml(offer)}${factsHtml(offer)}
          <section><h3>Pourquoi ce score ?</h3><p class="muted small">Critères du profil chargé pour cette évaluation ; passages recopiés de l’annonce lorsqu’ils sont disponibles.</p>${offer.blocking_criteria?.length ? `<p>Critères bloquants : ${offer.blocking_criteria.map((item) => `<code>${escapeHtml(item)}</code>`).join(" ")}</p>` : '<p class="muted small">Aucun critère obligatoire bloquant enregistré ; les informations absentes restent à vérifier.</p>'}${criteriaHtml(offer.criteria, offer.minimum_confidence)}</section>
          ${offer.dimensions?.length ? `<section><h3>Dimensions complémentaires</h3><p class="muted small">Éclairages séparés du score global, sans recalcul de l’évaluation.</p>${criteriaHtml(offer.dimensions, offer.minimum_confidence)}</section>` : ""}
        </div>
        <div class="analysis-column">
          <section class="analysis-next"><p class="eyebrow">Et ensuite ?</p><h3>Suivi de candidature</h3><p class="muted small">Décidez après lecture des preuves et des réserves. Ajouter au suivi n’envoie aucune candidature.</p><div class="drawer-actions">${offer.application ? `${applicationStatusBadge(offer.application.status)}<a class="secondary-btn" href="/applications?open=${encodeURIComponent(offer.application.id)}">Ouvrir le suivi</a>` : '<button data-track-offer>Ajouter au suivi</button>'}</div></section>
          <section><h3>Préparer mon CV</h3><div class="drawer-actions">${offer.cv ? `<a class="secondary-btn" href="/api/cv/${offer.cv.job_id}/pdf" target="_blank" rel="noopener">Télécharger le CV existant</a>` : ""}<button data-drawer-cv${cvDisabled}>Générer PDF</button><button class="secondary-btn" data-drawer-email${cvDisabled}>PDF + email</button></div>${cvReady ? '<p class="muted small">L’envoi par email est une action distincte, déclenchée uniquement par le bouton « PDF + email ».</p>' : '<p class="muted small">Un CV source et un moteur disponibles sont nécessaires. La consultation et le suivi restent accessibles.</p>'}</section>
          <section><h3>Historique · ${payload.history.length} évaluation(s)</h3><p class="muted small">Les scores historiques ne sont pas recalculés avec le profil actuel.</p><div class="history-lines">${payload.history.map(historyLine).join("")}</div></section>
          ${feedbackHtml(offer)}
        </div>
      </div>`;
    $("[data-drawer-cv]").addEventListener("click", (event) => generateCv(offer.url, false, event.currentTarget));
    $("[data-drawer-email]").addEventListener("click", (event) => generateCv(offer.url, true, event.currentTarget));
    const track = $("[data-track-offer]");
    if (track) track.addEventListener("click", async () => {
      track.disabled = true;
      try {
        await fetchJSON("/api/applications", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: offer.url, title: offer.title || "", company: offer.company || "", location: offer.location || "" }) });
        showToast("Offre ajoutée au suivi.", "success"); await loadOffers(); await openDrawer(url);
      } catch (error) { showToast(error.message, "error"); track.disabled = false; }
    });
    bindFeedback(offer);
    $("#drawer_close").focus();
  }

  function closeDrawer() {
    drawerRequest += 1;
    updateQuery({ open: null });
    $("#offer_drawer").classList.remove("open"); $("#offer_drawer").setAttribute("aria-hidden", "true"); $("#offer_drawer_backdrop").classList.add("hidden");
    if (drawerTrigger?.isConnected) drawerTrigger.focus();
    drawerTrigger = null;
  }

  const controlMap = { filter_status: "status", filter_company: "company", filter_location: "location", filter_score_min: "score_min", filter_score_max: "score_max", filter_scored: "scored", filter_cv: "has_cv", filter_view: "view", sort: "sort" };
  Object.entries(controlMap).forEach(([id, key]) => $("#" + id).addEventListener("change", (event) => { state[key] = event.target.value; state.page = 1; loadOffers(true); }));
  $("#filter_q").addEventListener("input", (event) => { clearTimeout(debounce); debounce = setTimeout(() => { state.q = event.target.value.trim(); state.page = 1; loadOffers(true); }, 300); });
  $("#filters_reset").addEventListener("click", () => { Object.assign(state, { page: 1, q: "", status: "", company: "", location: "", run_id: "", score_min: "", score_max: "", scored: "", has_cv: "", view: "latest", sort: "newest" }); syncControls(); loadOffers(true); });
  $("#quick_filters").addEventListener("click", (event) => { const button = event.target.closest("[data-quick]"); if (!button) return; state.status = button.dataset.quick === "review" ? "review_required" : button.dataset.quick; state.page = 1; syncControls(); loadOffers(true); });
  $("#offers_pagination").addEventListener("click", (event) => { const button = event.target.closest("[data-page]"); if (!button || button.disabled) return; state.page = Number(button.dataset.page); loadOffers(true); window.scrollTo({ top: 0, behavior: "smooth" }); });
  $("#offers_list").addEventListener("click", (event) => { if (event.target.closest("[data-external]")) return; const row = event.target.closest("[data-url]"); if (row) openDrawer(row.dataset.url).catch((error) => JEV.showToast(error.message, "error")); });
  $("#offers_list").addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-url]")) {
      event.preventDefault();
      openDrawer(event.target.dataset.url).catch((error) => showToast(error.message, "error"));
    }
  });
  $("#drawer_close").addEventListener("click", closeDrawer); $("#offer_drawer_backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    const drawer = $("#offer_drawer");
    if (!drawer.classList.contains("open")) return;
    if (event.key === "Escape") closeDrawer();
    else trapFocus(drawer, event);
  });
  $("#filters_open").addEventListener("click", () => {
    $("#filters").classList.add("open"); $("#filters_open").setAttribute("aria-expanded", "true");
  });
  $("#filters_close").addEventListener("click", () => {
    $("#filters").classList.remove("open"); $("#filters_open").setAttribute("aria-expanded", "false");
  });
  window.addEventListener("popstate", () => location.reload());
  syncControls();
  loadOffers().then(() => {
    const open = params.get("open");
    if (open) return openDrawer(open);
  }).catch((error) => showToast(error.message, "error"));
})();
