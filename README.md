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
├── requirements.txt         # dépendances web, import PDF et moteur de CV
├── app/                     # sources de l'application web
│   ├── config.py            # lecture de config.toml + surcharges d'environnement
│   ├── onboarding.py        # premier lancement : PDF → master + profil
│   ├── main.py              # routes HTTP (dashboard, évaluation, CV, exports)
│   ├── extract.py           # récupération de page + extraction (titre, employeur, dates)
│   ├── gates.py             # portes contrat / expérience / fraîcheur / disponibilité
│   ├── jev.py               # appel du script de notation Jev
│   ├── analytics.py         # agrégats du dashboard
│   ├── cv.py                # exécution du moteur de CV configuré
│   ├── pipeline.py          # fetch -> extract -> gates -> Jev -> verdict
│   ├── store.py             # SQLite, migration, pagination et déduplication
│   ├── templates/           # pages Évaluer, Offres, Lots, CV, Analyses et Profil
│   └── static/              # shell commun + scripts spécialisés par page
├── engine/                  # moteur de CV embarqué (aucune dépendance Hermes)
│   ├── tailor_cv.py         # sélection/reformulation bornée par le master + validation
│   ├── render_cv_pdf.py     # rendu PDF une page
│   ├── validate_tailoring.py# anti-invention : rien qui ne soit dans le master
│   └── fonts/               # Liberation Sans embarquée (+ licence) : rendu identique partout
├── scripts/
│   ├── evaluate_job.py      # notation Jev (script du skill Job Hunt + surcharges optionnelles)
│   └── serve.py             # démarrage : affiche la config effective puis lance uvicorn
└── tests/                   # 194 tests hors ligne (Python + Node)
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
6. **CV adapté** à la demande, via le moteur embarqué configurable.
7. **Profil éditable et historisé** : rôles, lieux, seuils, critères et règles de rejet,
   avec validation, écriture atomique, restauration et protection contre les conflits d'onglets.
8. **Multi-utilisateur isolé** : comptes créés sur invitation, mots de passe Argon2id,
   sessions révocables et données SQLite/fichiers séparées par utilisateur.
9. **Suivi des candidatures** lié aux offres : `À étudier`, `CV prêt`, candidature envoyée,
   entretien, refus ou offre reçue, avec journal d'événements, relances et exports CSV/JSON.
10. **Fallback manuel** pour les sites dynamiques ou inaccessibles au serveur : coller le texte
   de l'annonce sans requête sortante ni navigateur Chromium dans l'image.

### Premier lancement

Au premier démarrage, l'interface crée le premier administrateur si les variables de bootstrap
ne sont pas définies. Les comptes suivants sont créés uniquement avec une invitation à usage
unique, expirables et révocables. Tant que le profil de l'utilisateur connecté n'existe pas,
l'interface demande un CV PDF avec une couche texte. Le CV
est extrait puis analysé par le modèle CV configuré ; aucun fait absent du document ne doit
être ajouté. L'utilisateur complète uniquement les préférences non déductibles du CV
(postes, localisations et seuils). L'application écrit dans
`<data_dir>/users/<user_id>/` :

- `CV_MASTER.json`, source factuelle du générateur de CV ;
- `PROFILE.json`, critères et préférences d'évaluation ;
- `source_cv.pdf`, copie du document importé.

Ces fichiers sont des données d'instance, ignorées par Git et persistées dans le volume Docker.
Les API d'évaluation et de CV répondent `428` tant que l'initialisation n'est pas terminée.

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
| `profile` | `path` | ancien chemin mono-utilisateur | source migrée automatiquement en v2.3 |
| `profile` | `evaluator` | `./scripts/evaluate_job.py` | script de notation |
| `fetch` | `max_workers` | `4` | offres évaluées en parallèle (1-8) |
| `cv` | `enabled` | `true` | `false` = bouton CV désactivé, avec explication |
| `cv` | `command` | `cv-tailor {url} …` | commande du moteur, placeholders `{url}` `{out_dir}` `{extra}` |
| `cv` | `out_dir` | ancien chemin mono-utilisateur | source migrée automatiquement en v2.3 |
| `cv` | `env_file` | — | fichier `KEY=VALUE` chargé pour le moteur (clé, emails SMTP) |
| `security` | `session_hours` | `12` | durée du cookie de session signé |
| `security` | `login_attempts` | `5` | tentatives de connexion par fenêtre de cinq minutes |
| `jobs` | `max_attempts` | `3` | reprises maximales d'un lot après redémarrage |

Surcharges d'environnement acceptées : `OPENROUTER_API_KEY`, `JEV_CONFIG`, `HOST`, `PORT`,
`JEV_DATA_DIR`, `JEV_DB`, `JEV_PROFILE`, `JEV_EVALUATOR`, `CV_MASTER`, `CV_COMMAND`, `CV_OUT_DIR`,
`CV_TAILOR_BIN` (ancien nom, conservé), `HERMES_ENV_FILE`, `JEV_ADMIN_USERNAME`,
`JEV_ADMIN_EMAIL`, `JEV_AUTH_PASSWORD`,
`JEV_SESSION_SECRET`, `JEV_COOKIE_SECURE`, `JEV_TRUST_PROXY` et
`JEV_ALLOW_INSECURE_REMOTE`.

### Sécurité de l'interface

L'authentification est obligatoire. `JEV_AUTH_PASSWORD` (12 caractères minimum) sert à
créer automatiquement le premier administrateur avec `JEV_ADMIN_USERNAME` et
`JEV_ADMIN_EMAIL`; sans ces variables, une page de création est proposée. Les mots de passe
sont hachés en Argon2id et la connexion accepte l'email ou le nom d'utilisateur. Le cookie de
session contient l'identifiant et une version révocable, est signé, `HttpOnly` et
`SameSite=Strict`. `JEV_SESSION_SECRET` doit contenir au moins 32 caractères pour une écoute
distante et conserver les sessions après redémarrage. Utiliser `JEV_COOKIE_SECURE=true`
derrière HTTPS et `JEV_TRUST_PROXY=true` uniquement derrière un reverse proxy de confiance.

Une écoute non locale sans secret de session stable est refusée par défaut. Ne définir
`JEV_ALLOW_INSECURE_REMOTE=true` que pour un environnement de développement isolé.
Les URL d'offres sont validées contre les destinations privées, locales, réservées et les
métadonnées cloud ; chaque redirection est revalidée avant connexion.

## Portabilité

Pour faire tourner l'application ailleurs, il faut **les sources et une clé API** — rien d'autre :

1. copier le dépôt sans les éléments régénérables (`.venv/`, `data/`, `__pycache__/`,
   `config.toml` et `.env`) ;
2. créer `config.toml` depuis `config.example.toml` et `.env` depuis `.env.example` ;
3. démarrer, ouvrir l'interface puis importer le CV PDF demandé.

Les données personnelles ne font donc pas partie des sources. Pour déplacer une instance déjà
initialisée, copier son `data_dir` ou son volume Docker en plus du dépôt.

Aucune installation Hermes n'est requise : le moteur de CV est embarqué, ses polices aussi,
et tous les chemins par défaut sont relatifs au dossier. Le moteur reste désactivable
(`[cv] enabled = false`) ; dans ce cas la génération de CV est annoncée comme indisponible
avec le motif, sans que le reste de l'application en souffre.

Vérifié sur une instance vierge : 194 tests hors ligne, isolation entre deux comptes,
migration SQLite v5 et chemins utilisateur sous `/data/users/`.

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
cp .env.example .env                  # y mettre OPENROUTER_API_KEY et JEV_SESSION_SECRET
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
| `GET` | `/` | nouvelle évaluation et reprise des lots en cours |
| `GET` | `/offers` | espace de travail paginé, filtré et dédupliqué par URL |
| `GET` | `/runs`, `/runs/{id}` | historique et détail des lots |
| `GET` | `/cv`, `/analytics`, `/profile`, `/applications` | CV persistants, analyses, profil éditable et candidatures |
| `GET` | `/api/onboarding` | état du premier lancement et fichiers manquants |
| `POST` | `/api/onboarding` | formulaire multipart avec `cv_pdf` et préférences → initialise le profil |
| `POST` | `/api/evaluate` | `{"urls": ["https://…", …]}` → `{"run_id": …}` |
| `POST` | `/api/evaluate/manual` | URL + texte collé d'une offre dynamique → évaluation persistée |
| `GET` | `/api/runs/{run_id}` | état du lot + résultats complets + résumé agrégé |
| `GET` | `/api/stats?view=latest\|all&days=N` | KPI filtrables, scores, critères et portes |
| `GET` | `/api/offers` | pagination, recherche, filtres, tri et vue dernière/toutes les évaluations |
| `GET` | `/api/offers/history?url=…` | détail et historique des évaluations d'une URL normalisée |
| `GET` | `/api/history?page=N` | lots paginés, filtrables par état |
| `GET` | `/api/criteria` | critères et seuils du profil chargé |
| `GET`, `PUT` | `/api/profile` | lecture et mise à jour validée du profil avec révision optimiste |
| `GET` | `/api/profile/history` | historique des versions du profil |
| `POST` | `/api/profile/history/{id}/restore` | restauration d'une version du profil |
| `GET`, `POST` | `/api/applications` | recherche/liste paginée et création d'une candidature |
| `GET`, `PATCH`, `DELETE` | `/api/applications/{id}` | détail, mise à jour et suppression d'une candidature |
| `GET` | `/api/applications/export?fmt=csv\|json` | export du suivi des candidatures |
| `POST` | `/api/cv` | `{"url": "…", "send_email": false}` → `{"job_id": …}` |
| `GET` | `/api/cv` | jobs CV récents, y compris ceux en cours (permet de reprendre le suivi après reload) |
| `GET` | `/api/cv/{job_id}` | état du job CV + résumé du moteur (pages, titre, écarts) |
| `GET` | `/api/cv/{job_id}/pdf` | le PDF généré (404 si absent, 403 hors du répertoire de sortie) |
| `POST` | `/api/runs/{run_id}/cancel`, `/retry` | annulation ou reprise des offres manquantes |
| `POST` | `/api/cv/{job_id}/cancel`, `/retry` | annulation ou relance explicite d'un CV interrompu |
| `GET`, `POST` | `/api/backups` | liste et création de sauvegardes intègres |
| `GET`, `DELETE` | `/api/backups/{name}` | téléchargement et suppression d'une sauvegarde |
| `POST` | `/api/backups/restore` | restauration validée, avec sauvegarde de sécurité préalable |
| `GET` | `/api/runs/{run_id}/export?fmt=json\|csv` | export |
| `GET` | `/healthz` | état + configuration effective **sans aucun secret** |
| `GET`, `POST` | `/setup-admin` | création du premier administrateur si aucun compte actif |
| `GET`, `POST` | `/register?token=…` | création d'un compte avec une invitation valide |
| `GET` | `/admin` | gestion basique des comptes et invitations (administrateur) |
| `GET` | `/api/auth/me` | compte actuellement connecté |
| `POST` | `/api/auth/change-password`, `/api/auth/logout-all` | mot de passe et révocation des sessions |
| `GET`, `POST`, `DELETE` | `/api/admin/invitations` | création, liste et révocation des invitations |
| `GET`, `PATCH` | `/api/admin/users` | liste et activation/désactivation des comptes |

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
LLM bornée par `<data_dir>/users/<user_id>/CV_MASTER.json`, validateur anti-invention, rendu PDF une page avec les
polices embarquées). L'application ne fabrique rien : elle affiche ce que le moteur renvoie
(pages, titre retenu, priorités, écarts, avertissements) et, en cas d'échec, son message
d'erreur tel quel. Variables lues par le moteur : `CV_MASTER`, `CV_PROFILE`, `CV_DATA_DIR`,
`CV_OUT_DIR`, `CV_RUNS`, `CV_JEV`, `CV_MODEL`, `CV_FONTDIR` — toutes dérivées de `config.toml`
par l'application.

## Interface multipage

- **Évaluer** : saisie des URLs, déduplication avant envoi, lot actif et derniers lots.
- **Offres** : pagination serveur, recherche, filtres, tri, dernière évaluation par URL par
  défaut et accès à tout l'historique dans un panneau latéral.
- **Lots** : progression persistée, reprise après redémarrage, annulation, relance des URL
  manquantes, compteurs, exports et détail complet des résultats.
- **CV** : tâches en cours, PDF terminés et erreurs, avec reprise du polling après rechargement ;
  après un redémarrage, un CV interrompu attend une relance manuelle pour éviter un email en double.
- **Analyses** : période et vue dernière/toutes les évaluations, KPI cliquables, distribution,
  portes et critères.
- **Profil** : identité issue du master, seuils, critères et sauvegardes/restaurations.

Les scores gardent un affichage visuel : valeur numérique, barre colorée et marqueur du seuil.
Les petits indicateurs de critères ont désormais une légende textuelle (`bloquant`,
`confiance faible`, `satisfait`) afin de ne pas dépendre uniquement de la couleur.

SQLite migre automatiquement les anciennes bases vers le schéma v5, rattache les données au
premier administrateur et remplace les unicités globales par des unicités par utilisateur.
Les résultats JSON complets restent conservés ; aucune ancienne évaluation n'est supprimée.
Les paramètres `utm_*`, `fbclid`, `gclid`, fragments et slash final sont ignorés pour
regrouper les réévaluations d'une même URL.

## Tests

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_app_js.mjs
```

Les 184 tests Python et 10 tests JavaScript sont hors ligne et n'utilisent aucune clé API. Ils
couvrent notamment migration SQLite, authentification, SSRF, reprise des jobs, sauvegardes,
API, score visuel et pagination.

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
