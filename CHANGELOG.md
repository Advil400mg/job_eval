# Changelog

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
