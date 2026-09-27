# Changelog

## 2.5.0 — 2026-09-27

- Ajout d’un journal d’audit SQLite v7, filtrable et limité aux métadonnées autorisées.
- Traçage des connexions, comptes, invitations, profils, candidatures, évaluations, CV et sauvegardes.
- Ajout d’une page de diagnostic administrateur : SQLite, disque, tâches, utilisateurs, fichiers et sauvegardes.
- Vérification manuelle des sauvegardes, rotation par rétention et alerte sur les sauvegardes planifiées trop anciennes.
- Remplacement des confirmations natives par des dialogues accessibles, navigation clavier, lien d’évitement et restauration du focus.
- Ajout de tests E2E Playwright Chromium et d’une CI GitHub Actions couvrant Python, JavaScript, navigateur, Compose et Docker.
- Correction de la validation CSRF derrière un reverse proxy HTTPS de confiance.

## 2.4.3 — 2026-09-27

- Ajout de la suppression définitive d’un utilisateur par un administrateur.
- Suppression transactionnelle des données SQLite et purge du répertoire de fichiers isolé.
- Récupération automatique des répertoires de suppression après un arrêt brutal ou un échec de nettoyage.
- Confirmation par nom d’utilisateur, refus de l’auto-suppression et blocage pendant une tâche active.
- Avertissement explicite : les sauvegardes existantes ne sont pas modifiées.

## 2.4.2 — 2026-09-27

- Ajout d’un état d’onboarding persistant par utilisateur pendant l’analyse du CV.
- Reprise de l’interface après actualisation, avec suivi automatique, refus des doublons et récupération après redémarrage.
- Migration du schéma SQLite vers la version 6.

## 2.4.1 — 2026-09-27

- Prise en charge d’Ubuntu 26.04 LTS par le rôle Ansible de production.
- Correction de la validation de l’adresse email ACME et affichage de la précondition en échec.
- Ajout d’un playbook de décommission avec conservation ou purge explicite des données.
- Réécriture du guide de déploiement, d’exploitation et de décommission.
- Maintien de la disponibilité HTTP pendant l’analyse initiale d’un CV.

## 2.4.0 — 2026-09-26

- Ajout d’un déploiement de production automatisé par Ansible pour Ubuntu 24.04 et Debian 12.
- Ajout d’une pile Docker Compose de production derrière Caddy avec HTTPS automatique.
- Ajout de sauvegardes planifiées, de contrôles de santé, d’une procédure de mise à jour et de rollback.
- Centralisation de la version applicative et passage de l’application à 2.4.0.

## 2.3.0 — 2026-09-25

- Ajout des comptes multi-utilisateur créés uniquement sur invitation.
- Hachage des mots de passe avec Argon2id et connexion par email ou nom d’utilisateur.
- Sessions signées contenant l’identifiant utilisateur et une version révocable.
- Création du premier administrateur par variables d’environnement ou interface dédiée.
- Invitations à usage unique, expirables, révocables, copiables ou envoyables par SMTP.
- Interface d’administration pour les comptes et invitations.
- Migration SQLite v5 avec rattachement des données existantes au premier administrateur.
- Isolation stricte des lots, résultats, profils, CV, candidatures et historiques par utilisateur.
- Fichiers persistants déplacés sous `data/users/<user_id>/`.
- Sauvegardes globales adaptées à l’arborescence multi-utilisateur.
- Version de l’application et de l’image Docker portée à 2.3.0.
