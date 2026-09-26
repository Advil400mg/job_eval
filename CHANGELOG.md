# Changelog

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
