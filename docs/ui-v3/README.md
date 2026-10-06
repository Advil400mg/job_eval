# JEV v3.0 — première maquette interactive

Statut : proposition à valider, pas une interface intégrée à l’application.
Base applicative inchangée : release `v2.6.0`, commit de fusion `91346cb`.

## Ouvrir

Ouvrir `index.html` directement dans un navigateur, ou servir ce dossier :

```sh
python3 -m http.server 18830 --bind 127.0.0.1 --directory docs/ui-v3
```

Puis ouvrir `http://127.0.0.1:18830/` sur la même machine. Depuis une autre machine,
utiliser un tunnel SSH ; ne pas exposer ce serveur de prévisualisation sur Internet.

## Parcours présents

- Vue d’ensemble : sélection fictive, point à clarifier, résumé du profil.
- Mes offres : recherche, filtre de décision, tri par score, état sans résultat.
- Analyse : décision, score, confiance, portes et extraits sourcés séparés ; cas
  compatible, revue requise et exclusion par expérience (sans score inventé).
- Profil : faits, préférences, règles avancées ; aperçu mis à jour à la saisie.
- Nouvelle analyse : URL ou texte, validation de forme, navigation vers un exemple
  déjà préparé — jamais un résultat calculé à partir de la saisie.
- Navigation sur ordinateur ou menu au clavier sur mobile ; thèmes clair/sombre.

## Limites explicites

Toutes les identités, annonces, statistiques, scores et verdicts sont synthétiques.
Aucun appel Jev/API, téléchargement d’annonce, CV, email ou connexion réelle.
Le formulaire de profil simule une sauvegarde : les valeurs vivent uniquement en
mémoire et disparaissent au rechargement. Seul le thème peut être mémorisé par le
navigateur. Les analyses restent figées lorsque le profil d’exemple est modifié.

Les liens « candidatures », « CV », « analyses » et « administration » ne sont pas
simulés : leurs pages existent dans la v2.6 et seront traitées après validation du
socle visuel. Aucun écran existant n’est supprimé ni modifié à cette étape.

## Proposition d’intégration après validation visuelle

1. Reporter le socle dans `app/templates/base.html`, les styles partagés et
   `app/static/common.js`, en préservant les dialogues, la sécurité et les routes.
2. Refaire `offers.html`/`offers.js` et la lecture d’une analyse : action utile,
   statut réel, score et réserves sans masquer les données historiques.
3. Refaire `setup.html`/`setup.js` et `profile.html`/`profile.js` : sections guidées,
   aperçu des règles, confirmation et conflits de révision.
4. Refaire `evaluate.html`/`evaluate.js`, puis lots, CV, candidatures et analyses.
5. Harmoniser connexion, inscription, administration, audit et diagnostic.
6. Étendre les tests JS, Python et Playwright ; vérifier plusieurs largeurs, clavier,
   thèmes, états d’erreur et tâches persistantes. Aucun changement de moteur ou de
   schéma n’est inclus dans cette refonte.

## Recette de la maquette

La vérification autonome `verify.mjs` utilise Playwright déjà installé dans le
projet ; elle démarre son propre serveur sur un port éphémère et l’arrête en fin
de test. Elle ne dépend ni du serveur applicatif ni d’un compte réel.

```sh
npm run test:ui-preview
```

Captures et résultats dans `test-results/ui-v3-preview/` (ignorés par Git).

## Points de validation utilisateur

- Navigation et accès rapide aux fonctions.
- Palette claire/sombre, densité, typographie et hiérarchie des informations.
- Lecture des cas compatibles, incertains et bloquants.
- Organisation guidée du profil.

Après cette validation seulement : intégration progressive sur `dev` ; `main`
reste sur la v2.6. Le changement de numéro applicatif interviendra avec le travail
intégré, pas pour donner à une maquette le statut d’une release.
