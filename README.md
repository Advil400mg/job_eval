# Évaluateur d'offres d'emploi — Jev

Application web autonome : vous collez une ou plusieurs URLs d'offres, l'appli récupère
chaque page, en extrait l'offre, applique les portes objectives (contrat, expérience,
fraîcheur, disponibilité), puis la fait noter par **Jev** (TypeSafe, via OpenRouter) sur
les critères du profil. Elle affiche score global, score et confiance par critère,
critères obligatoires en échec, verdict final, et sait générer un CV adapté.

Tout est configurable par un seul fichier `config.toml` : aucun chemin propre à une
machine n'est codé en dur, et l'application démarre même sans fichier de configuration.

## Arborescence

```
jev-webapp/
├── run-local.sh             # lancement local en une commande (venv + config + serveur)
├── config.example.toml      # modèle de configuration commenté  → copier en config.toml
├── .env.example             # variables d'environnement (clé API, SMTP) → copier en .env
├── Dockerfile               # image auto-portante
├── docker-compose.yml       # l'unique fichier compose
├── requirements.txt         # fastapi, uvicorn, jinja2 + moteur de CV (reportlab, pymupdf)
├── PROFILE.json             # critères, seuils, règles de rejet dur
├── app/                     # sources de l'application web
│   ├── config.py            # lecture de config.toml + surcharges d'environnement
│   ├── main.py              # routes HTTP (dashboard, évaluation, CV, exports)
│   ├── extract.py           # récupération de page + extraction (titre, employeur, dates)
│   ├── gates.py             # portes contrat / expérience / fraîcheur / disponibilité
│   ├── jev.py               # appel du script de notation Jev
│   ├── analytics.py         # agrégats du dashboard
│   ├── cv.py                # exécution du moteur de CV configuré
│   ├── pipeline.py          # fetch -> extract -> gates -> Jev -> verdict
│   ├── store.py             # SQLite (lots, résultats, jobs CV)
│   ├── templates/index.html
│   └── static/{app.js,style.css}
├── engine/                  # moteur de CV embarqué (aucune dépendance Hermes)
│   ├── tailor_cv.py         # sélection/reformulation bornée par le master + validation
│   ├── render_cv_pdf.py     # rendu PDF une page
│   ├── validate_tailoring.py# anti-invention : rien qui ne soit dans le master
│   ├── CV_MASTER.json       # base de faits du candidat  ← à remplacer pour partager
│   └── fonts/               # Liberation Sans embarquée (+ licence) : rendu identique partout
├── scripts/
│   ├── evaluate_job.py      # notation Jev (script du skill Job Hunt + surcharges optionnelles)
│   └── serve.py             # démarrage : affiche la config effective puis lance uvicorn
└── tests/                   # 66 tests hors ligne (Python + Node)
```

## Ce que fait l'application

1. **Récupération** de chaque URL (HTTP, User-Agent navigateur, 1 nouvelle tentative).
2. **Extraction** : titre, employeur, localisation, date de publication prouvée
   (JSON-LD `datePosted`, sinon « offre publiée le », « en ligne depuis le »), texte de l'offre.
3. **Portes** (jamais fusionnées avec le score) :
   - `contract_type` : stage / alternance / statut étudiant = échec dur ;
   - `experience` : minimum ≥ 2 ans = échec dur ; fourchette au-delà de 2 ans sans mention
     junior = échec dur ; silence total = *inconnu* (jamais compté comme un succès) ;
   - `freshness` : date non prouvable ou hors fenêtre (`max_age_days`) = échec dur ;
   - `availability` : offre retirée / date limite dépassée = échec dur.
4. **Notation Jev** déléguée à `scripts/evaluate_job.py` — le script du skill Job Hunt
   (même validation, mêmes retries, même score pondéré). L'application ne recalcule ni
   n'ajuste jamais un score ; seuls l'endpoint, le modèle et la clé viennent de la config.
5. **Verdict** : `qualified` / `jev_excluded` / `rejected` / `unverified` (Jev injoignable,
   aucune donnée inventée).
6. **CV adapté** à la demande, via un moteur externe configurable.

## Configuration — config.toml

Copier le modèle puis adapter :

```bash
cp config.example.toml config.toml
```

Priorité : **variables d'environnement > config.toml > valeurs par défaut**. Sans
`config.toml`, l'application tourne avec des chemins relatifs à son propre dossier.
`python3 scripts/serve.py --check` (ou `./run-local.sh` au démarrage) affiche la
configuration effective — jamais les secrets.

### Clé OpenRouter, trois possibilités

| Méthode | Réglage | Remarque |
|---|---|---|
| variable d'environnement | `export OPENROUTER_API_KEY=…` | priorité maximale, rien à écrire sur disque |
| fichier de secrets | `[openrouter] api_key_file = "/chemin/vers/.env"` | format `KEY=VALUE` ou clé brute ; utiliser un chemin propre à la machine de déploiement |
| directement dans le fichier | `[openrouter] api_key = "sk-or-…"` | déconseillé : fichier en clair (à mettre hors dépôt) |

### Clés principales

| Section | Clé | Défaut | Rôle |
|---|---|---|---|
| `app` | `host`, `port` | `127.0.0.1`, `8000` | écoute (`HOST`/`PORT` surchargent) |
| `app` | `data_dir` | `./data` | SQLite, PDF générés, caches |
| `app` | `db_file` | `<data_dir>/jev.db` | base SQLite |
| `openrouter` | `endpoint` | API OpenRouter | point d'entrée Jev |
| `openrouter` | `model` | `typesafe/jev-1.13` | modèle de notation |
| `profile` | `path` | `./PROFILE.json` | critères, seuils, rejets durs |
| `profile` | `evaluator` | `./scripts/evaluate_job.py` | script de notation |
| `fetch` | `max_workers` | `4` | offres évaluées en parallèle (1-8) |
| `cv` | `enabled` | `true` | `false` = bouton CV désactivé, avec explication |
| `cv` | `command` | `cv-tailor {url} …` | commande du moteur, placeholders `{url}` `{out_dir}` `{extra}` |
| `cv` | `out_dir` | `<data_dir>/cv` | PDF générés |
| `cv` | `env_file` | — | fichier `KEY=VALUE` chargé pour le moteur (clé, emails SMTP) |

Surcharges d'environnement acceptées : `OPENROUTER_API_KEY`, `JEV_CONFIG`, `HOST`, `PORT`,
`JEV_DATA_DIR`, `JEV_DB`, `JEV_PROFILE`, `JEV_EVALUATOR`, `CV_COMMAND`, `CV_OUT_DIR`,
`CV_TAILOR_BIN` (ancien nom, conservé), `HERMES_ENV_FILE`.

## Portabilité

Pour faire tourner l'application ailleurs, il faut **les sources et une clé API** — rien d'autre :

1. copier le dossier sans les éléments régénérables (`.venv/`, `data/`, `__pycache__/`,
   `config.toml` et `.env`) ;
2. créer `config.toml` depuis `config.example.toml` et `.env` depuis `.env.example` ;
3. adapter `PROFILE.json` et `engine/CV_MASTER.json` au candidat — les seules vraies
   dépendances métier (et les seules données personnelles du dossier).

Aucune installation Hermes n'est requise : le moteur de CV est embarqué, ses polices aussi,
et tous les chemins par défaut sont relatifs au dossier. Le moteur reste désactivable
(`[cv] enabled = false`) ; dans ce cas la génération de CV est annoncée comme indisponible
avec le motif, sans que le reste de l'application en souffre.

Vérifié en réel : copie du dossier dans un autre répertoire, `config.toml` minimal, aucune
variable d'environnement, aucun chemin Hermes → `/healthz` lisible, évaluation réelle (61,2),
et CV réellement généré (1 page, 45 474 octets) par le moteur de cette copie.

## Démarrage sans Docker

```bash
cd /chemin/vers/jev-webapp
./run-local.sh                        # http://127.0.0.1:8000
./run-local.sh --config /autre/config.toml
HOST=0.0.0.0 PORT=8077 ./run-local.sh
```

`run-local.sh` charge automatiquement `.env`, crée le venv au premier lancement (`uv`
s'il est présent, sinon `python -m venv`), affiche la configuration effective, puis démarre
le serveur. Équivalent manuel :

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/serve.py --check     # contrôle config + clé + moteur CV
.venv/bin/python scripts/serve.py             # démarre (hôte/port depuis config.toml)
```

## Démarrage avec Docker

Un seul fichier compose, aucune dépendance externe à monter :

```bash
cd /chemin/vers/jev-webapp
cp .env.example .env                  # y mettre OPENROUTER_API_KEY
cp config.example.toml config.toml    # adapter si besoin
docker compose up -d --build          # http://localhost:8000
```

L'image contient l'application, le moteur de CV et ses polices. Le même `config.toml` sert
en local et dans le conteneur (monté en lecture seule). Les données persistantes sont dans
le volume Docker `jev-data`; `docker compose down` ne les supprime pas.

Surcharges utiles : `PORT`, `CONFIG_FILE`, `TZ`, ainsi que les variables OpenRouter,
SMTP et IMAP du fichier `.env`.

Points de portabilité vérifiés :

| Point | Pourquoi |
|---|---|
| utilisateur non privilégié de l'image | aucun uid/gid propre à la machine de déploiement |
| volume Docker `jev-data` | SQLite, PDF et journaux persistent sans problème de droits sur un bind mount |
| polices embarquées dans `engine/fonts` | rendu identique sans paquet de polices système |
| `TZ=Europe/Paris` | horodatages cohérents avec le fuseau attendu |
| `HOME=/tmp` | dossier inscriptible pour les bibliothèques tierces |

## API

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/` | interface web (dashboard + évaluation + CV) |
| `POST` | `/api/evaluate` | `{"urls": ["https://…", …]}` → `{"run_id": …}` |
| `GET` | `/api/runs/{run_id}` | état du lot + résultats complets + résumé agrégé |
| `GET` | `/api/stats` | KPI globaux, répartition des scores, agrégats par critère et par porte |
| `GET` | `/api/offers` | toutes les offres évaluées, aplaties (score, critères, portes, CV existant) |
| `GET` | `/api/history` | résumé de chaque lot (meilleur score, moyenne, compteurs) |
| `GET` | `/api/criteria` | critères et seuils du profil chargé |
| `POST` | `/api/cv` | `{"url": "…", "send_email": false}` → `{"job_id": …}` |
| `GET` | `/api/cv` | jobs CV récents, y compris ceux en cours (permet de reprendre le suivi après reload) |
| `GET` | `/api/cv/{job_id}` | état du job CV + résumé du moteur (pages, titre, écarts) |
| `GET` | `/api/cv/{job_id}/pdf` | le PDF généré (404 si absent, 403 hors du répertoire de sortie) |
| `GET` | `/api/runs/{run_id}/export?fmt=json\|csv` | export |
| `GET` | `/healthz` | état + configuration effective **sans aucun secret** |

```bash
curl -s localhost:8000/healthz | jq
curl -s localhost:8000/api/evaluate -H 'Content-Type: application/json' \
  -d '{"urls":["https://exemple.fr/offre-emploi/xyz/"]}'
curl -s localhost:8000/api/stats | jq '{avg_score, criteria: [.criteria[] | {id, avg_score, blocking}]}'
```

## Bouton CV

Chaque offre porte deux boutons, dans la table comme dans le détail d'un lot. Une section
« Générations de CV » conserve les jobs récents et reprend automatiquement le suivi de ceux
en cours après un rechargement de la page :

- **CV (PDF)** : le PDF est produit et reste dans l'application, **rien n'est envoyé**
  (`{extra}` = `--dry-run`).
- **CV + email** : en plus du PDF, le moteur envoie le CV **sur ta propre boîte**
  (`email_target`, affichée au-dessus de la table). Le CV ne part **jamais** chez le
  recruteur depuis cette application.

Le moteur est celui que vous configurez — par défaut celui embarqué dans `engine/` (sélection
LLM bornée par `engine/CV_MASTER.json`, validateur anti-invention, rendu PDF une page avec les
polices embarquées). L'application ne fabrique rien : elle affiche ce que le moteur renvoie
(pages, titre retenu, priorités, écarts, avertissements) et, en cas d'échec, son message
d'erreur tel quel. Variables lues par le moteur : `CV_MASTER`, `CV_PROFILE`, `CV_DATA_DIR`,
`CV_OUT_DIR`, `CV_RUNS`, `CV_JEV`, `CV_MODEL`, `CV_FONTDIR` — toutes dérivées de `config.toml`
par l'application.

## Dashboard

- **KPI** : offres évaluées, qualifiées, refusées Jev, validées Jev mais exclues, échecs
  techniques, score moyen / meilleur / pire, coût Jev cumulé et volume de tokens.
- **Répartition des scores** par tranche, seuil mis en évidence.
- **Portes** : pass / échec / réserve / inconnu par porte, plus le motif d'échec le plus fréquent.
- **Comportement des critères Jev** : poids, obligatoire, score moyen, confiance moyenne,
  nombre de blocages (et pourcentage), confiances sous le seuil — triés par fréquence de blocage.
- **Historique des lots** : chaque ligne se déplie (« offres ▾ ») pour montrer ses offres
  groupées, triées par score, sans quitter la page.
- **Toutes les offres évaluées** : recherche plein texte, filtre par statut, filtre par note
  (≥ seuil / sous le seuil / avec un score / sans score), case « grouper par lot », score vs
  seuil, mini-barres par critère, date de publication prouvée, critères bloquants, portes en
  échec, boutons CV.

## Tests

```bash
python3 tests/test_gates.py       # portes + parsing de dates (20 tests)
python3 tests/test_analytics.py   # agrégats du dashboard (9 tests)
python3 tests/test_cv_parse.py    # lecture de la sortie du moteur CV (4 tests)
python3 tests/test_config.py      # configuration, priorités, clé API, CV (20 tests)
python3 tests/test_store.py       # persistance et reprise des jobs CV (2 tests)
node tests/test_app_js.mjs        # filtres, groupement et états CV (11 tests)
```

Tous hors ligne, sans dépendance ni clé API. Le test JS exécute `app.js` dans un contexte
Node avec un DOM factice.

## Limites connues

- **Pages rendues en JavaScript** : l'extraction est en HTTP simple (stdlib). Une offre dont
  le contenu dépend d'un rendu JS ressort avec peu de texte ; la porte `freshness` échoue
  alors volontairement (une offre non datée n'est jamais qualifiée).
- **Moteur de CV** : il est embarqué et sans dépendance Hermes, mais garde ses propres
  dépendances (reportlab/pymupdf, polices incluses) et son master de faits. Il lui arrive
  d'échouer sur une réponse LLM vide — l'application remonte l'erreur telle quelle plutôt
  qu'un faux succès.
- **Instances multiples** : deux instances partageant le même `data_dir` partagent la base
  et les jobs CV ; un PDF produit par l'une est refusé au téléchargement par l'autre
  (garde-fou de chemin, 403). Un `data_dir` par instance.
- **Score Jev** : la confiance par critère est affichée ; une confiance sous le seuil est une
  réserve, pas un rejet. `location_fit` revient parfois avec une confiance 0,00 (bruit du modèle).
