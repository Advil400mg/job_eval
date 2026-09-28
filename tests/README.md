# Tests JEV

La suite de tests combine trois niveaux complémentaires :

1. tests Python pour la logique métier, SQLite et les API ;
2. tests JavaScript hors navigateur pour les fonctions d’interface isolables ;
3. parcours E2E Playwright Chromium pour les interactions réelles, le clavier et le responsive.

Pour la v2.6, la suite contient 331 tests Python, 21 tests JavaScript et 11 parcours E2E.
Aucune clé OpenRouter ni donnée personnelle n’est nécessaire.

## Installation

Depuis la racine du dépôt :

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
npm ci
npx playwright install chromium
```

En CI, Chromium et ses dépendances système sont installés avec :

```bash
npx playwright install --with-deps chromium
```

## Lancer toute la suite

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_app_js.mjs
npm run test:e2e
```

Vérifications complémentaires exécutées par la CI :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q app scripts tests
git diff --check
docker compose config --quiet
docker build -t jev-webapp:test .
```

## Tests Python

Les tests Python utilisent `unittest`. Ils couvrent notamment :

- migrations et isolation SQLite ;
- authentification, sessions, invitations et autorisations ;
- journal d’audit et filtrage des métadonnées sensibles ;
- diagnostic administrateur ;
- création, vérification, restauration et rétention des sauvegardes ;
- profils, candidatures, traitements asynchrones et reprise après interruption ;
- sécurité réseau, SSRF et validation CSRF ;
- routes API et rendu des pages.

Lancer un module :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_audit -v
```

Lancer un test précis :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  tests.test_diagnostics.DiagnosticsTests.test_collect_reports_schema_storage_jobs_and_backups -v
```

Les tests qui manipulent la base ou les fichiers utilisent des répertoires temporaires. Ils doivent
restaurer `store.DB_PATH`, les variables d’environnement modifiées et les caches de configuration
dans `tearDown()`.

## Tests JavaScript hors navigateur

`tests/test_app_js.mjs` charge les scripts de l’interface dans `node:vm` avec un DOM minimal simulé.
Cette suite rapide vérifie notamment :

- échappement des valeurs injectées ;
- scores, badges et pagination ;
- annonces d’erreur accessibles ;
- absence d’injection HTML dans les résultats d’administration ;
- dialogues partagés de confirmation et de saisie ;
- états persistants et polling des tâches.

Commande :

```bash
node tests/test_app_js.mjs
```

Ces tests conviennent aux fonctions de rendu déterministes. Une interaction dépendant du focus,
du clavier, de `<dialog>` ou du calcul de mise en page doit être testée avec Playwright.

## Parcours E2E Playwright

Les scénarios sont dans `tests/e2e/*.spec.js` :

- `auth.spec.js` : échec et réussite de connexion, déconnexion, redirections et droits admin ;
- `admin.spec.js` : invitation, inscription, suppression d’un compte, audit, diagnostic et sauvegarde ;
- `accessibility.spec.js` : lien d’évitement, clavier, drawers, dialogues, retour du focus et largeurs cibles ;
- `feedback.spec.js` : résultat v2.5, preuve hostile échappée, revue, retour éditable, conflit de révision,
  isolation entre comptes et contrôle mobile.

Commande complète :

```bash
npm run test:e2e
```

Lancer un fichier :

```bash
npx playwright test tests/e2e/accessibility.spec.js
```

Lancer un scénario par son nom :

```bash
npx playwright test -g 'dialogue destructif'
```

Afficher le navigateur pendant le test :

```bash
npx playwright test --headed
```

Utiliser l’interface de débogage Playwright :

```bash
npx playwright test --debug
```

## Serveur et données E2E

`playwright.config.js` démarre `tests/e2e/serve.py` sur `127.0.0.1:8769`.
Le serveur crée à chaque lancement :

- un répertoire temporaire ;
- une base SQLite neuve ;
- un administrateur et un utilisateur standard ;
- un profil et un master minimaux pour chaque compte ;
- une évaluation v2.5 sans preuve et une évaluation v2.6 avec passage hostile échappé ;
- une candidature de démonstration.

Les identifiants sont réservés aux tests et les données sont supprimées avec le processus. La suite
ne lit ni n’écrit la base de développement, `config.toml` ou le volume Docker de l’application.

Playwright teste une vraie application FastAPI, mais pas l’image Docker. La construction de l’image
et le smoke test du conteneur restent des contrôles séparés.

## Artefacts en cas d’échec

Playwright conserve une trace et une capture lorsqu’un scénario échoue. Les sorties locales se
trouvent généralement dans :

- `test-results/` pour les traces et captures ;
- `playwright-report/` pour le rapport HTML produit en CI.

Ces répertoires sont ignorés par Git.

Pour ouvrir une trace :

```bash
npx playwright show-trace test-results/<test>/trace.zip
```

## Choisir le bon niveau de test

- Ajouter un test Python pour une règle métier, une transaction, une migration ou une réponse API.
- Ajouter un test JavaScript hors navigateur pour une fonction pure ou un rendu déterministe.
- Ajouter un test Playwright pour un parcours utilisateur, une autorisation visible, le focus,
  le clavier, un dialogue ou le responsive.
- Ajouter un smoke test Docker lorsqu’il faut prouver le démarrage et le comportement de l’image.

Un correctif d’interface doit au minimum exécuter les tests Python concernés et
`node tests/test_app_js.mjs`. Toute modification du focus, des dialogues, de la navigation ou des
seuils responsive doit également exécuter `npm run test:e2e`.
