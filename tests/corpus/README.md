# Corpus d’évaluation JEV v1

Ce corpus synthétique sert à mesurer la qualité des décisions de JEV pour un profil
junior en cybersécurité. Il ne contient aucune offre, entreprise ou donnée personnelle
réelle. Les corrigés ont été relus par l’agent à la demande de Tanguy ; seules les
classes des trois premiers cas ont été validées par lui. Consulter `../REVIEW-v1.md`
pour les preuves, corrections et limites. Les métriques sur ces cas synthétiques
restent exploratoires et ne prouvent pas la qualité sur des offres réelles.

## Composition

- 10 offres compatibles ;
- 10 offres incompatibles ;
- 10 offres ambiguës nécessitant une vérification humaine ;
- textes en français et en anglais ;
- difficultés d’expérience, séniorité, contrat, GRC, conseil vague, localisation et astreinte.

Chaque fichier de `cases/` contient :

- l’annonce synthétique et ses métadonnées ;
- la classe attendue ;
- les faits structurés attendus ;
- les statuts attendus de certaines portes ;
- des extraits qui doivent pouvoir être retrouvés dans le texte source.

`profile.json` est un profil fictif. Il ne doit pas être remplacé par un profil utilisateur réel.
Le holdout synthétique de 12 cas, annoté aussi par l'agent, est dans
`../../holdout/v1/cases/`. Les comparaisons live, les effectifs de portes, les répétitions
et leurs limites figurent dans `../../../benchmarks/evaluation-v2.6.md` ; le JSON voisin
conserve les prédictions par cas et les empreintes des corpus. Aucun de ces jeux
n'est une validation indépendante sur des annonces réelles.

## Commandes

Validation hors ligne et portes déterministes :

```bash
python3 scripts/benchmark_evaluation.py --mode offline
```

Benchmark réel avec l’évaluateur configuré :

```bash
python3 scripts/benchmark_evaluation.py --mode live \
  --output benchmarks/evaluation-v2.6.json
```

Contrôle de stabilité limité aux cas difficiles :

```bash
python3 scripts/benchmark_evaluation.py --mode live --critical-only --repetitions 3
```

Le mode `live` consomme du quota OpenRouter et n’est jamais lancé automatiquement en CI.

## Règles d’évolution

- Tout faux positif ou faux négatif reproductible doit devenir un cas synthétique minimal.
- Une citation attendue doit être une sous-chaîne exacte du texte de l’annonce.
- Une information absente doit rester `unknown` et ne jamais devenir une compatibilité certaine.
- La distribution 10/10/10 est figée pour v1 ; créer v2 pour élargir le corpus.
- Ne jamais committer de texte d’offre réel sans réécriture et anonymisation complètes.
