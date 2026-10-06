(() => {
  "use strict";
  const { $, escapeHtml, fetchJSON, statusBadge, scoreVisual, offerReason } = JEV;
  const detailLink = (url) => `/offers?open=${encodeURIComponent(url)}`;
  function offerCard(offer) {
    return `<a class="dashboard-offer" href="${detailLink(offer.url)}"><div><h3>${escapeHtml(offer.title || offer.url)}</h3><p>${escapeHtml(offer.company || "Entreprise inconnue")} · ${escapeHtml(offer.location || "Lieu non renseigné")}</p>${statusBadge(offer.status)}<p>${escapeHtml(offerReason(offer))}</p></div>${scoreVisual(offer.score, offer.minimum_global_score, true)}</a>`;
  }
  function renderSelection(payload) {
    $("#dashboard_selection").innerHTML = payload.offers.length
      ? payload.offers.slice(0, 3).map(offerCard).join("")
      : '<div class="empty-state"><strong>Pas encore d’offre qualifiée</strong><p><a href="/offers">Examiner les résultats existants</a> ou <a href="/">lancer une évaluation</a>.</p></div>';
  }
  function renderActions(reviews, overdue) {
    const actions = [];
    if (reviews) {
      reviews.offers.slice(0, 2).forEach((offer) => actions.push(`<a class="dashboard-task" href="${detailLink(offer.url)}"><strong>Vérifier : ${escapeHtml(offer.title || offer.url)}</strong><small>${escapeHtml(offerReason(offer))}</small></a>`));
      if (reviews.total > 2) actions.push(`<a class="dashboard-task" href="/offers?status=review_required"><strong>Voir les ${reviews.total} offres en revue</strong><small>Une information inconnue n’est pas un succès présumé.</small></a>`);
    } else actions.push('<p class="error">La liste des offres à vérifier est momentanément indisponible.</p>');
    if (overdue) {
      if (overdue.total) actions.push(`<a class="dashboard-task" href="/applications?due=overdue"><strong>${overdue.total} relance${overdue.total > 1 ? "s" : ""} en retard</strong><small>Vérifier les candidatures et leurs dates de suivi.</small></a>`);
    } else actions.push('<p class="error">Les relances sont momentanément indisponibles.</p>');
    if (reviews && overdue && !actions.length) actions.push('<p class="muted">Aucune offre en revue ni relance en retard dans les données actuelles.</p><a class="dashboard-task" href="/"><strong>Explorer de nouvelles offres →</strong><small>Le moteur utilisera votre profil actuel.</small></a>');
    $("#dashboard_actions").innerHTML = actions.join("");
  }
  async function load() {
    const endpoints = [
      "/api/offers?view=latest&page_size=10",
      "/api/offers?view=latest&status=qualified&sort=score_desc&page_size=10",
      "/api/offers?view=latest&status=review_required&page_size=10",
      "/api/applications?due=overdue&page_size=5",
    ];
    const results = await Promise.allSettled(endpoints.map((url) => fetchJSON(url)));
    const payloads = results.map((result) => result.status === "fulfilled" ? result.value : null);
    ["dashboard_total", "dashboard_qualified", "dashboard_review"].forEach((id, index) => {
      if (payloads[index]) $("#" + id).textContent = payloads[index].total;
      else { $("#" + id).textContent = "Indisponible"; $("#" + id).classList.add("dashboard-unavailable"); }
    });
    if (payloads[1]) renderSelection(payloads[1]);
    else $("#dashboard_selection").innerHTML = '<div class="error" role="alert">Les offres n’ont pas pu être chargées. <a href="/offers">Ouvrir la liste</a> ou actualiser cette page.</div>';
    renderActions(payloads[2], payloads[3]);
  }
  load().catch((error) => {
    $("#dashboard_selection").innerHTML = `<div class="error" role="alert">${escapeHtml(error.message)}</div>`;
    $("#dashboard_actions").textContent = "Les prochaines actions ne sont pas disponibles. Actualisez la page pour réessayer.";
  });
})();
