# Évaluation v2.6 — mesures exploratoires du 28 septembre 2026

Le fichier `evaluation-v2.6.json` conserve les 147 lignes mesurées (classes, portes, coût), les métriques et les empreintes des deux corpus. Les annonces et le profil sont synthétiques ; le corpus principal a été relu par l'agent à la demande de Tanguy, et le holdout a aussi été écrit/annoté par l'agent. Ni l'un ni l'autre n'est un test indépendant sur des annonces réelles. Les chiffres ne prouvent pas une précision de 100 % en production.

## Comparaison A/B

Même script de banc, mêmes annonces et profil fictif, modèle `typesafe/jev-1.13-20260917`, deux arbres distincts : tag publié `v2.5.0` et code v2.6 de la branche `dev`. Un appel modèle par offre/version, jamais un verdict fabriqué à partir du corrigé. Les portes du holdout ont été annotées après les appels ; leur exactitude a été recalculée sur les portes réellement enregistrées, sans modifier les annonces ni réappeler le modèle.

| Jeu | Verdicts v2.5 → v2.6 | Faux positifs v2.5 → v2.6 | Portes annotées v2.5 → v2.6 | Coût USD v2.5 → v2.6 |
|---|---:|---:|---:|---:|
| Corpus principal (30) | 14/30 → 30/30 | 3 → 0 | 4/11 → 11/11 | 0,002976 → 0,007677 |
| Holdout (12) | 6/12 → 12/12 | 3 → 0 | 22/24 → 24/24 | 0,001196 → 0,003177 |

La distribution v2.5 du holdout était de 7 compatibles, 4 ambiguës et 1 incompatible ; celle de v2.6 est de 4 par classe. Une meilleure détection de l'incertitude déplace des offres vers « revue requise » : c'est une différence de décision, pas nécessairement un gain de jugement sur des offres inédites. Le nombre de portes annotées du corpus principal (11) reste limité.

## Stabilité et preuves

- Après correction d'une instabilité sur une mission de conseil dont le premier client est inconnu, 3 répétitions des 9 cas difficiles du corpus ont donné 27/27 décisions attendues, aucun cas instable ; coût 0,006887 USD.
- Trois répétitions des 12 cas du holdout ont donné 36/36 décisions attendues, aucun cas instable ; coût 0,009531 USD.
- Les 4 reformulations à sens constant testées avec les réponses Jev enregistrées conservent la classe « ambiguë ». Elles contrôlent les règles déterministes sans nouveau coût modèle ; elles restent écrites par le même agent.
- Sur les appels A/B v2.6, 434 extraits affichables ont été vérifiés dans leur annonce source : 0 citation absente. Cette propriété n'est pas une mesure de pertinence des passages choisis.

Un premier contrôle de stabilité avait révélé `SYNTH-024-A` instable : deux revues et un rejet selon la confiance Jev au seuil. La correction préserve la revue quand l'absence de première mission est prouvée par l'annonce, sauf porte bloquante ou rejet technique clair. Les répétitions chiffrées ci-dessus ont été faites après cette correction. Une nouvelle variation sur un cas critique ou une reformulation qui change la classe bloquerait la livraison.

## Reproduction et limites

Le mode hors ligne ne mesure que les portes/faits annotés, sans appeler Jev ni calculer de conformité des verdicts :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/benchmark_evaluation.py --mode offline
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/benchmark_evaluation.py --mode offline --corpus tests/holdout/v1
```

Le mode live est volontaire, payant et exclu de la CI. Il exige `OPENROUTER_API_KEY` dans l'environnement du processus :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/benchmark_evaluation.py --mode live --workers 2
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/benchmark_evaluation.py --mode live --corpus tests/holdout/v1 --workers 2
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/benchmark_evaluation.py --mode live --critical-only --repetitions 3 --workers 2
```

Pour refaire une comparaison A/B, extraire le tag v2.5.0 dans un second arbre et y recopier le même script de banc et les mêmes corpus avant d'exécuter les mêmes commandes. Les appels sont indépendants et le modèle peut varier ; conserver les effectifs, la distribution des classes et les coûts avec tout pourcentage. Les JSON détaillés de réponses modèle n'ont pas été ajoutés au dépôt ; le fichier de synthèse versionné garde les décisions par cas et les empreintes des corpus. Une validation externe sur des offres réelles anonymisées reste à faire avant de revendiquer une précision générale.
