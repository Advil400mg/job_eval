(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const fold = (value) => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const decisions = { qualified: ['Compatible', 'ok'], review: ['À vérifier', 'warn'], excluded: ['Incompatible', 'bad'] };
  const offers = [
    { id: 'atlas', title: 'Analyste données', company: 'Atelier Atlas', place: 'Lyon, France', contract: 'CDI', score: 84, confidence: 89, status: 'qualified', years: 2,
      reason: 'Missions et expérience en accord avec le profil fictif.',
      body: 'Poste d’analyste données en CDI à Lyon. Deux ans d’expérience professionnelle minimum sont requis. Vous analysez les ventes avec SQL et Python et construisez des tableaux de bord. Un accompagnement est prévu sur les outils de l’équipe.',
      quote: 'Deux ans d’expérience professionnelle minimum sont requis.',
      language: 'Aucune langue obligatoire identifiée dans cet exemple.', metrics: [['Missions et métier', 92, 'SQL, analyse des ventes et tableaux de bord'], ['Compétences', 86, 'Python et SQL correspondent aux déclarations fictives'], ['Développement professionnel', 75, 'Accompagnement décrit, progression à approfondir']] },
    { id: 'horizon', title: 'Business Data Analyst', company: 'Horizon Exemple', place: 'Paris, France', contract: 'CDD', score: 78, confidence: 82, status: 'review', years: 2,
      reason: 'Anglais C1 demandé ; niveau B2 dans le profil fictif.',
      body: 'CDD de Business Data Analyst à Paris. Two years of experience required. English C1 required for client workshops. You use SQL and Python to produce operational reports.',
      quote: 'English C1 required for client workshops.', language: 'Niveau requis C1 ; niveau déclaré B2 : à approfondir.',
      metrics: [['Missions et métier', 88, 'Analyse des données opérationnelles'], ['Compétences', 84, 'SQL et Python'], ['Compatibilité linguistique', 45, 'Exigence C1 face à un niveau B2 déclaré']] },
    { id: 'meridian', title: 'Senior Data Scientist', company: 'Méridien Fictif', place: 'Bordeaux, France', contract: 'CDI', score: null, confidence: null, status: 'excluded', years: 5,
      reason: 'Minimum de 5 ans requis ; 3 ans déclarés dans le profil.',
      body: 'Poste Senior Data Scientist en CDI à Bordeaux. Minimum de 5 ans d’expérience professionnelle exigé. Vous concevez et mettez en production des modèles prédictifs.',
      quote: 'Minimum de 5 ans d’expérience professionnelle exigé.', language: 'Sans objet pour cet exemple exclu par une porte.', metrics: [] },
    { id: 'rivage', title: 'Analyste reporting', company: 'Rivage Démo', place: 'Toulouse, France', contract: 'CDI', score: 81, confidence: 87, status: 'qualified', years: 2,
      reason: 'Profil et périmètre cohérents ; conditions à confirmer en entretien.',
      body: 'CDI d’analyste reporting à Toulouse. Deux ans d’expérience minimum requis. Vous préparez les indicateurs avec SQL, validez la qualité des données et améliorez les tableaux de bord.',
      quote: 'Vous préparez les indicateurs avec SQL, validez la qualité des données et améliorez les tableaux de bord.', language: 'Aucune langue obligatoire identifiée dans cet exemple.',
      metrics: [['Missions et métier', 89, 'Indicateurs et qualité des données'], ['Compétences', 83, 'SQL et reporting'], ['Clarté de l’offre', 73, 'Outils BI et conditions pratiques à confirmer']] },
  ];
  const profile = { name: 'Camille Exemple', role: 'Analyste données', years: '3', skills: 'SQL\nPython\nAnalyse de données', languages: 'Français C2, anglais B2', places: 'France', preferred: 'Lyon\nParis', contracts: ['permanent', 'fixed_term'], confirmed: true };
  let step = 'facts';
  let toastTimer;
  let dialogTrigger;
  const heading = (eyebrow, title, subtitle, action = '') => `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;
  const badge = (status) => `<span class="badge ${decisions[status][1]}">${decisions[status][0]}</span>`;
  const card = (offer) => `<a class="offer-card" href="#detail/${offer.id}" aria-label="Voir l’analyse : ${escape(offer.title)} chez ${escape(offer.company)}"><div><h3>${escape(offer.title)}</h3><div class="offer-meta"><span>${escape(offer.company)}</span><span>${escape(offer.place)}</span><span>${offer.contract}</span></div>${badge(offer.status)}<p class="offer-reason">${escape(offer.reason)}</p></div><div class="offer-score"><strong>${offer.score ?? '—'}</strong><small>${offer.score === null ? 'Pas notée' : '/100 · exemple'}</small></div></a>`;
  function home() {
    return heading('VOTRE RECHERCHE', 'Bonjour Camille.', 'Un aperçu pour savoir quoi examiner et quelle action mener ensuite.', '<a href="#evaluate" class="button primary">＋ Analyser une offre</a>') +
      `<div class="kpi-grid"><div class="kpi"><small>Offres analysées</small><strong>4</strong><span>Échantillon fictif</span></div><div class="kpi"><small>Compatibles</small><strong>2</strong><span>À examiner avant candidature</span></div><div class="kpi"><small>À vérifier</small><strong>1</strong><span>Une question linguistique</span></div></div>
      <div class="columns"><section class="panel"><div class="section-title"><h2>Votre sélection</h2><a href="#offers">Toutes les offres →</a></div><div class="offer-list">${offers.slice(0, 2).map(card).join('')}</div></section><div class="stack"><section class="panel focus-card"><p class="eyebrow">PROCHAINE ACTION</p><h2>Clarifier avant de postuler.</h2><p class="muted">L’exemple Horizon correspond au métier, mais demande un niveau d’anglais supérieur à celui déclaré.</p><a class="button" href="#detail/horizon">Voir ce qui reste à vérifier →</a></section><section class="panel"><h2>Le profil utilisé</h2><dl class="profile-summary"><div><dt>Poste visé</dt><dd>${escape(profile.role)}</dd></div><div><dt>Expérience déclarée</dt><dd>${escape(profile.years)} ans</dd></div><div><dt>Lieux acceptés</dt><dd>${escape(profile.places)}</dd></div></dl><div class="action-row"><a href="#profile">Vérifier mon profil →</a></div></section></div></div>`;
  }
  function offerPage() {
    return heading('EXAMINER ET DÉCIDER', 'Mes offres', 'Le verdict d’abord, puis le score et sa justification. Toutes les annonces ci-dessous sont fictives.', '<a href="#evaluate" class="button primary">＋ Analyser une offre</a>') +
      `<div class="toolbar"><div><label for="search_offers">Rechercher</label><input id="search_offers" type="search" placeholder="Poste, entreprise ou ville…"></div><div><label for="filter_decision">Décision</label><select id="filter_decision"><option value="">Toutes</option><option value="qualified">Compatible</option><option value="review">À vérifier</option><option value="excluded">Incompatible</option></select></div><div><label for="sort_offers">Trier</label><select id="sort_offers"><option value="recent">Ordre initial</option><option value="score">Meilleur score</option></select></div></div><p class="result-count" id="result_count" role="status">4 offres fictives</p><div class="offer-list" id="offer_results">${offers.map(card).join('')}</div>`;
  }
  function updateOffers() {
    const query = fold($('#search_offers').value.trim());
    const status = $('#filter_decision').value;
    const list = offers.filter((offer) => (!status || offer.status === status) && fold(`${offer.title} ${offer.company} ${offer.place}`).includes(query));
    if ($('#sort_offers').value === 'score') list.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    $('#offer_results').innerHTML = list.length ? list.map(card).join('') : '<div class="empty"><strong>Aucun exemple ne correspond.</strong><p>Modifiez la recherche ou le filtre de décision.</p></div>';
    $('#result_count').textContent = `${list.length} offre${list.length > 1 ? 's' : ''} fictive${list.length > 1 ? 's' : ''}`;
  }
  function detail(id) {
    const offer = offers.find((item) => item.id === id);
    if (!offer) return heading('EXEMPLE INTROUVABLE', 'Cette offre n’existe pas.', 'Choisissez une annonce parmi les quatre exemples.', '<a class="button" href="#offers">Retour aux offres</a>');
    const excluded = offer.status === 'excluded';
    const cls = decisions[offer.status][1];
    const gate = (title, copy, label, css = 'ok') => `<div class="gate-row"><div><strong>${title}</strong><p>${copy}</p></div><span class="badge ${css}">${label}</span></div>`;
    return `<a class="back-link" href="#offers">← Mes offres</a>` + heading('ANALYSE D’EXEMPLE', escape(offer.title), `${escape(offer.company)} · ${escape(offer.place)} · ${offer.contract}`, '<button class="button" data-help>Comment lire l’analyse ?</button>') +
      `<div class="columns"><div class="stack"><section class="panel"><div class="detail-summary"><div class="decision-copy">${badge(offer.status)}<h2 style="margin-top:14px">${excluded ? 'Une exigence explicitement incompatible.' : offer.status === 'review' ? 'Un point à clarifier avant de candidater.' : 'Une offre à considérer.'}</h2><p>${escape(offer.reason)}</p></div><div class="score-display"><strong>${offer.score ?? '—'}</strong><span>${excluded ? '' : '/100'}</span><small>${excluded ? 'Jev non sollicité dans ce scénario' : 'Score fictif d’adéquation'}</small></div></div><div class="notice ${cls}">${excluded ? 'La porte d’expérience suffit à exclure cet exemple. Un titre attirant ou un bon score ne doit pas annuler un minimum obligatoire.' : offer.status === 'review' ? 'Le score ne tranche pas l’incertitude. Vérifiez l’exigence linguistique avec le recruteur.' : 'Compatible ne signifie ni candidature envoyée ni recrutement garanti. Relisez les preuves et les conditions de l’offre.'}</div><p class="muted" style="font-size:12px">${offer.confidence === null ? 'Pas de score ni de confiance modèle dans cet exemple.' : `Confiance modèle fictive : ${offer.confidence} % · Ce n’est pas une probabilité de recrutement.`}</p></section>
      <section class="panel"><h2>Conditions vérifiées</h2>${gate('Contrat', `${offer.contract} · accepté dans le profil fictif.`, 'Compatible')}${gate('Expérience', `${offer.years} ans exigés, 3 ans déclarés dans le profil figé de l’exemple.`, excluded ? 'Bloquant' : 'Compatible', excluded ? 'bad' : 'ok')}${gate('Localisation', `${escape(offer.place)} · lieu explicitement indiqué dans le texte fictif.`, 'Compatible')}${gate('Langues', escape(offer.language), offer.status === 'review' ? 'À vérifier' : 'Information', offer.status === 'review' ? 'warn' : 'neutral')}</section>
      ${offer.metrics.length ? `<section class="panel"><h2>Pourquoi ce score ?</h2><p class="muted" style="font-size:12px">Illustration de la présentation ; ces sous-scores ne sont pas un calcul du moteur.</p>${offer.metrics.map(([name, score, reason]) => `<div class="metric-row"><div><strong>${name}</strong><small>${reason}</small><div class="meter"><span style="width:${score}%"></span></div></div><strong>${score}/100</strong></div>`).join('')}</section>` : ''}
      <section class="panel"><h2>La preuve, dans l’annonce</h2><blockquote>${escape(offer.quote)}</blockquote><p class="muted" style="font-size:12px">Extrait recopié du texte fictif ci-dessous.</p><details><summary>Lire le texte source de l’exemple</summary><p>${escape(offer.body)}</p></details></section></div>
      <div class="stack"><section class="panel focus-card"><p class="eyebrow">ET ENSUITE ?</p><h2>${excluded ? 'Choisir un autre exemple.' : offer.status === 'review' ? 'Préparer la bonne question.' : 'Passer de l’analyse à l’action.'}</h2><p class="muted">${excluded ? 'Une expérience inférieure au minimum obligatoire reste incompatible dans ce scénario.' : offer.status === 'review' ? '« Le niveau C1 est-il indispensable pour tous les ateliers, ou un niveau B2 peut-il être accepté ? »' : 'Dans l’application future : ouvrir l’annonce, préparer un CV et suivre la candidature. Rien n’est envoyé dans cette maquette.'}</p><a href="#${excluded ? 'offers' : 'profile'}" class="button">${excluded ? 'Revenir aux offres' : 'Relire le profil utilisé'}</a></section><section class="panel"><h2>Traçabilité</h2><dl class="profile-summary"><div><dt>Origine</dt><dd>Annonce entièrement fictive</dd></div><div><dt>Profil</dt><dd>Camille Exemple · 3 ans d’expérience</dd></div><div><dt>Historique</dt><dd>Pas d’évaluation réelle ni d’ancien lot modifié</dd></div></dl></section></div></div>`;
  }
  function profileSummary() {
    const names = { permanent: 'CDI', fixed_term: 'CDD', freelance: 'Indépendant', internship: 'Stage / alternance' };
    return `<dl class="profile-summary"><div><dt>Poste visé</dt><dd>${escape(profile.role)}</dd></div><div><dt>Expérience</dt><dd>${escape(profile.years || 'Non renseignée')}${profile.years ? ' ans' : ''}</dd></div><div><dt>Lieux acceptés</dt><dd>${escape(profile.places || 'Sans restriction')}</dd></div><div><dt>Contrats acceptés</dt><dd>${escape(profile.contracts.map((c) => names[c]).join(', ') || 'Tous')}</dd></div><div><dt>Langues déclarées</dt><dd>${escape(profile.languages || 'Non renseignées')}</dd></div></dl>`;
  }
  const field = (key, title, textarea = false, hint = '') => `<div><label for="sample_${key}">${title}</label>${textarea ? `<textarea id="sample_${key}" name="${key}" rows="3" data-profile ${hint ? `aria-describedby="hint_${key}"` : ''}>${escape(profile[key])}</textarea>` : `<input id="sample_${key}" name="${key}" data-profile value="${escape(profile[key])}" ${hint ? `aria-describedby="hint_${key}"` : ''} ${key === 'years' ? 'type="number" min="0" max="60" step="0.5"' : 'type="text" maxlength="500"'}>`}${hint ? `<span class="hint" id="hint_${key}">${hint}</span>` : ''}</div>`;
  function profilePage() {
    let body;
    if (step === 'facts') body = `<h2>Ce que JEV doit savoir sur vous</h2><p class="muted">Déclarations du profil d’exemple. Une correction ici ne modifierait pas le CV source.</p><div class="field-grid">${field('name', 'Nom affiché')}${field('role', 'Poste visé')}${field('years', 'Années d’expérience professionnelle')}${field('languages', 'Langues et niveaux', false, 'Un niveau par langue : Français C2, English B2…')}${field('skills', 'Compétences', true, 'Une compétence par ligne.')}</div><p class="profile-note">CV source : aucun document personnel utilisé dans la maquette.</p>`;
    else if (step === 'preferences') body = `<h2>Ce que vous recherchez</h2><p class="muted">Distinguer les contraintes bloquantes et les préférences.</p><div class="field-grid">${field('places', 'Lieux acceptés', true, 'Une ville ou un pays par ligne ; vide = sans restriction.')}${field('preferred', 'Lieux préférés', true, 'Priorités uniquement : les autres lieux acceptés restent possibles.')}<fieldset class="full" style="border:0;padding:0;margin:0"><legend>Contrats acceptés</legend>${[['permanent', 'CDI'], ['fixed_term', 'CDD'], ['freelance', 'Indépendant'], ['internship', 'Stage / alternance']].map(([value, label]) => `<label class="check-label"><input type="checkbox" data-contract value="${value}" ${profile.contracts.includes(value) ? 'checked' : ''}>${label}</label>`).join('')}<p class="hint">Aucun choix = tous les contrats.</p></fieldset></div>`;
    else body = `<h2>Règles avancées et confirmation</h2><p class="muted">Ces réglages sont présentés comme une seconde lecture, pas comme un prérequis pour comprendre l’application.</p><div class="field-grid"><label>Score global minimum<input type="number" value="68" min="0" max="100" disabled><span class="hint">Réglage illustratif non éditable dans cette première maquette.</span></label><label>Confiance minimale<input type="number" value="0.5" min="0" max="1" step="0.1" disabled></label></div><div class="notice">Les portes d’éligibilité sont distinctes du score. Une exigence obligatoire incompatible reste bloquante.</div><label class="check-label"><input id="sample_confirmed" type="checkbox" ${profile.confirmed ? 'checked' : ''}>J’ai vérifié les faits et les préférences de cet exemple.</label><details style="margin-top:18px"><summary>Exemple de critères transmis au moteur</summary><p>Missions : comparer aux postes visés. Compétences : comparer aux déclarations. Localisation : comparer aux lieux acceptés et préférés. Ne pas transformer une donnée absente en succès.</p></details>`;
    return heading('PERSONNALISER L’ANALYSE', 'Mon profil', 'Des informations factuelles, des préférences explicites, puis les règles avancées.') +
      `<div class="step-tabs" aria-label="Sections du profil">${[['facts', '1 · Mon expérience'], ['preferences', '2 · Ma recherche'], ['rules', '3 · Règles & confirmation']].map(([id, label]) => `<button data-step="${id}" aria-pressed="${step === id}">${label}</button>`).join('')}</div><div class="columns"><form id="sample_profile_form" class="panel">${body}<div class="action-row"><button type="submit" class="button primary">Tester l’enregistrement</button><span class="hint">Simulation uniquement ; aucune donnée envoyée.</span></div><p id="profile_feedback" role="status" style="margin-top:12px"></p></form><section class="panel"><p class="eyebrow">APERÇU DES DÉCLARATIONS</p><h2>Ce qui serait utilisé</h2><div id="profile_summary">${profileSummary()}</div><div class="notice">Les annonces et analyses restent des exemples figés : modifier ce profil ne recalcule pas leurs scores.</div></section></div>`;
  }
  function evaluatePage() {
    return heading('UNE NOUVELLE ANALYSE', 'Analyser une offre', 'Deux entrées dans un même parcours : une URL ou le texte de l’annonce.') +
      `<div class="columns"><form class="panel" id="sample_evaluation_form"><h2>Collez les liens des offres</h2><label>URLs à analyser<textarea id="sample_urls" rows="7" placeholder="https://entreprise.example/offre/…">https://atelier-atlas.example.test/jobs/analyste\nhttps://horizon.example.test/jobs/analyst</textarea></label><p class="hint" id="url_counter" role="status">2 URLs d’exemple · aucun téléchargement</p><div class="notice">Profil sélectionné : <strong>${escape(profile.role)}</strong> · ${escape(profile.years)} ans déclarés.<br><a href="#profile">Vérifier les critères avant de lancer →</a></div><details><summary>Le site est inaccessible ? Utiliser le texte</summary><label style="margin-top:12px">Texte de l’annonce<textarea id="sample_job_text" rows="5" placeholder="Copiez les missions, exigences, contrat et localisation…"></textarea></label><p class="hint">Dans la version actuelle : repli manuel sans requête vers le site. Ici : champ de démonstration uniquement.</p></details><div class="action-row"><button type="submit" class="button primary">Simuler le parcours</button><span class="hint">Aucun appel au moteur</span></div><div id="evaluation_feedback" role="status" style="margin-top:16px"></div></form><div class="stack"><section class="panel"><h2>Ce qui se passe ensuite</h2><a class="task-link" href="#detail/atlas"><span><strong>1. Vérifier les conditions</strong><small>Contrat, expérience, localisation et disponibilité.</small></span><span>→</span></a><a class="task-link" href="#detail/atlas"><span><strong>2. Comprendre l’adéquation</strong><small>Score, preuves et réserves clairement séparés.</small></span><span>→</span></a><a class="task-link" href="#offers"><span><strong>3. Décider de la suite</strong><small>Examiner, clarifier ou écarter.</small></span><span>→</span></a></section><section class="panel"><h2>Une analyse, pas une garantie</h2><p class="muted">JEV aide à comparer une offre à votre profil. Il ne garantit ni recrutement ni exhaustivité de la page récupérée.</p><button class="button" type="button" data-help>Comprendre les verdicts</button></section></div></div>`;
  }
  function notify(message) {
    clearTimeout(toastTimer);
    $('#toast').textContent = message;
    $('#toast').hidden = false;
    toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 6000);
  }
  function menu(open, restoreFocus = true) {
    $('#navigation').classList.toggle('open', open);
    $('#mobile_backdrop').hidden = !open;
    $('#menu_toggle').setAttribute('aria-expanded', String(open));
    $('#menu_toggle').setAttribute('aria-label', open ? 'Fermer le menu' : 'Ouvrir le menu');
    if (open) $('#navigation nav a').focus();
    else if (restoreFocus) $('#menu_toggle').focus();
  }
  function route(initial = false) {
    const [requested, id] = location.hash.slice(1).split('/');
    const view = ['home', 'offers', 'detail', 'profile', 'evaluate'].includes(requested) ? requested : 'home';
    $('#content').innerHTML = view === 'detail' ? detail(id) : ({ home, offers: offerPage, profile: profilePage, evaluate: evaluatePage }[view])();
    const names = { home: 'Vue d’ensemble', offers: 'Mes offres', detail: 'Détail d’analyse', profile: 'Mon profil', evaluate: 'Analyser une offre' };
    $('#breadcrumb').textContent = 'Mon espace / ' + names[view];
    document.title = `${names[view]} — JEV maquette v3.0`;
    document.querySelectorAll('[data-nav]').forEach((link) => {
      const active = link.dataset.nav === (view === 'detail' ? 'offers' : view);
      if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    menu(false, false);
    if (!initial) { $('#content').focus(); window.scrollTo(0, 0); }
  }
  $('#content').addEventListener('click', (event) => {
    const button = event.target.closest('[data-step]');
    if (button) { step = button.dataset.step; $('#content').innerHTML = profilePage(); document.querySelector(`[data-step="${step}"]`).focus(); }
    const help = event.target.closest('[data-help]');
    if (help) { dialogTrigger = help; $('#help_dialog').showModal(); }
  });
  function profileInput(target) {
    if (target.matches('[data-profile]')) profile[target.name] = target.value;
    if (target.matches('[data-contract]')) profile.contracts = [...document.querySelectorAll('[data-contract]:checked')].map((item) => item.value);
    if (target.id === 'sample_confirmed') profile.confirmed = target.checked;
    if ($('#profile_summary')) $('#profile_summary').innerHTML = profileSummary();
  }
  $('#content').addEventListener('input', (event) => {
    const target = event.target;
    profileInput(target);
    if (['search_offers', 'filter_decision', 'sort_offers'].includes(target.id)) updateOffers();
    if (target.id === 'sample_urls') {
      const urls = target.value.split(/\n+/).map((line) => line.trim()).filter(Boolean);
      $('#url_counter').textContent = `${urls.length} ligne${urls.length > 1 ? 's' : ''} · aucune requête sortante`;
    }
  });
  $('#content').addEventListener('change', (event) => {
    profileInput(event.target);
    if (['filter_decision', 'sort_offers'].includes(event.target.id)) updateOffers();
  });
  $('#content').addEventListener('submit', (event) => {
    event.preventDefault();
    if (event.target.id === 'sample_profile_form') {
      const text = 'Simulation terminée : aucune donnée enregistrée dans l’application.';
      $('#profile_feedback').textContent = text;
      notify(text);
    }
    if (event.target.id === 'sample_evaluation_form') {
      const lines = $('#sample_urls').value.split(/\n+/).map((line) => line.trim()).filter(Boolean);
      const invalid = lines.some((line) => { try { return !['https:', 'http:'].includes(new URL(line).protocol); } catch (_) { return true; } });
      if ((!lines.length && !$('#sample_job_text').value.trim()) || invalid) {
        $('#evaluation_feedback').textContent = 'Saisissez une URL HTTP(S) par ligne ou un texte pour tester le parcours.';
        return;
      }
      $('#evaluation_feedback').innerHTML = '<div class="notice ok"><strong>Parcours simulé, aucun appel Jev.</strong><p>Ouvrez l’exemple déjà préparé ; il ne correspond pas aux liens que vous venez de saisir.</p><a class="button" href="#detail/atlas">Ouvrir l’exemple d’analyse →</a></div>';
    }
  });
  $('#theme_toggle').addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    setTheme(theme);
    try { localStorage.setItem('jev-ui-v3-theme', theme); } catch (_) { /* File mode may deny storage. */ }
  });
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $('#theme_toggle').setAttribute('aria-label', `Activer le thème ${theme === 'light' ? 'sombre' : 'clair'}`);
  }
  try { const saved = localStorage.getItem('jev-ui-v3-theme'); if (['light', 'dark'].includes(saved)) setTheme(saved); } catch (_) { /* No persistence is required. */ }
  $('#menu_toggle').addEventListener('click', () => menu(!$('#navigation').classList.contains('open')));
  $('#mobile_backdrop').addEventListener('click', () => menu(false));
  document.addEventListener('keydown', (event) => {
    if (!$('#navigation').classList.contains('open')) return;
    if (event.key === 'Escape') { menu(false); return; }
    if (event.key === 'Tab') {
      const links = [...$('#navigation').querySelectorAll('a[href]')];
      const first = links[0], last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
      else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
    }
  });
  $('#help_dialog').addEventListener('close', () => { if (dialogTrigger?.isConnected) dialogTrigger.focus(); });
  window.addEventListener('hashchange', () => route());
  route(true);
})();
