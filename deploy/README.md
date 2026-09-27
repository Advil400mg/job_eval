# Déployer et exploiter JEV avec Ansible

Ce dossier contient le déploiement de production de JEV pour Ubuntu 24.04/26.04 LTS
ou Debian 12 amd64. Il installe une pile Docker Compose derrière Caddy, configure
HTTPS, écrit les secrets hors du dépôt et active des sauvegardes quotidiennes.

## Vue d’ensemble

Deux machines interviennent :

- **machine de contrôle** : machine depuis laquelle les commandes Ansible sont lancées ;
- **serveur cible** : VPS qui héberge JEV et sur lequel Ansible se connecte en SSH.

Architecture déployée :

```text
Internet
   |
   | TCP 80/443, UDP 443
   v
Caddy ───── HTTPS automatique
   |
   | réseau Docker privé
   v
JEV :8000 ── volume jev-data
   |
   └──────── accès sortant OpenRouter et SMTP/IMAP optionnels
```

Le port applicatif 8000 n’est jamais publié sur l’hôte. Caddy est le seul composant
accessible depuis Internet.

## Ce qu’Ansible installe

| Élément | Emplacement ou nom |
|---|---|
| Releases immuables | `/opt/jev/releases/<version>` |
| Release active | `/opt/jev/current` |
| Configuration d’exécution | `/etc/jev/production.env` |
| Secrets individuels | `/etc/jev/secrets/*` |
| Sauvegardes | `/var/backups/jev` |
| Données applicatives | volume Docker `jev-data` |
| Certificats Caddy | volumes `jev-caddy-data` et `jev-caddy-config` |
| Commandes d’exploitation | `/usr/local/sbin/jev-*` |
| Sauvegarde planifiée | `jev-backup.timer` |

Ansible installe également Docker si nécessaire. Il ne gère UFW que lorsque
`jev_manage_firewall: true` est explicitement configuré.

## 1. Prérequis

### Machine de contrôle

- dépôt JEV cloné ;
- `uv` installé ;
- clé SSH permettant d’accéder au serveur ;
- mot de passe `sudo` du serveur si le compte n’a pas de sudo sans mot de passe.

Ansible n’a pas besoin d’être installé globalement : les commandes ci-dessous utilisent
`uv run --with ansible-core==2.18.9`.

### Serveur cible

- Ubuntu 24.04/26.04 LTS ou Debian 12 amd64 ;
- au moins 2 Go de RAM et 10 Go de stockage ;
- accès SSH par clé ;
- ports TCP 80 et 443 libres ;
- port UDP 443 libre si HTTP/3 est souhaité ;
- règles réseau du fournisseur autorisant SSH, TCP 80/443 et éventuellement UDP 443.

Vérification utile sur le serveur :

```bash
cat /etc/os-release
uname -m
sudo ss -ltnup | grep -E ':(80|443)\b' || true
```

## 2. Domaine ou sous-domaine sslip.io

Caddy a besoin d’un nom DNS pour obtenir un certificat HTTPS public.

Avec un domaine personnel, crée un enregistrement A pointant vers l’IPv4 du serveur.
Pour un déploiement sans domaine, une IP comme `51.83.120.42` peut utiliser :

```text
51-83-120-42.sslip.io
```

Le domaine est toujours configuré sans `https://` et sans port.

## 3. Préparer les fichiers Ansible

Toutes les commandes suivantes sont lancées depuis la machine de contrôle :

```bash
cd /chemin/vers/job_eval/deploy/ansible
cp inventory.example.ini inventory.ini
cp group_vars/all/main.example.yml group_vars/all/main.yml
cp group_vars/all/vault.example.yml group_vars/all/vault.yml
```

Les fichiers réels `inventory.ini`, `main.yml` et `vault.yml` sont ignorés par Git.

### Inventaire SSH

Éditer `inventory.ini` :

```ini
[jev]
jev-production ansible_host=51.83.120.42 ansible_user=ubuntu

[jev:vars]
ansible_become=true
```

Accepter une première fois la clé SSH du serveur :

```bash
ssh ubuntu@51.83.120.42
exit
```

### Configuration non secrète

Éditer `group_vars/all/main.yml` :

```yaml
---
jev_version: "2.4.1"
jev_domain: "51-83-120-42.sslip.io"
jev_acme_email: "admin@example.com"
jev_timezone: "Europe/Paris"

jev_admin_username: "admin"
jev_admin_email: "admin@example.com"

jev_backup_schedule: "*-*-* 03:15:00"
jev_backup_retention_days: 14

jev_manage_firewall: false
jev_ssh_port: 22
```

L’email ACME n’est pas un secret. Il sert de contact à l’autorité de certification.

### Secrets Ansible Vault

Éditer `group_vars/all/vault.yml` avant son premier chiffrement :

```yaml
---
jev_openrouter_api_key: "CLE_OPENROUTER"
jev_session_secret: "SECRET_ALEATOIRE_DE_32_CARACTERES_MINIMUM"
jev_admin_bootstrap_password: "MOT_DE_PASSE_ADMIN_INITIAL"

jev_email_address: ""
jev_email_password: ""
jev_email_smtp_host: ""
jev_email_smtp_port: 465
jev_email_imap_host: ""
jev_email_imap_port: 993
```

Générer un secret de session :

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Depuis `deploy/ansible`, chiffrer le fichier :

```bash
uv run --with ansible-core==2.18.9 \
  ansible-vault encrypt group_vars/all/vault.yml
```

Pour le modifier plus tard :

```bash
uv run --with ansible-core==2.18.9 \
  ansible-vault edit group_vars/all/vault.yml
```

## 4. Vérifier avant le déploiement

Test SSH et inventaire :

```bash
uv run --with ansible-core==2.18.9 \
  ansible all -m ping --ask-vault-pass
```

Vérification syntaxique :

```bash
uv run --with ansible-core==2.18.9 \
  ansible-playbook site.yml --syntax-check --ask-vault-pass
```

Le rôle refuse notamment :

- une distribution ou architecture non prise en charge ;
- un domaine invalide ;
- une adresse ACME invalide ;
- une clé OpenRouter vide ;
- un secret de session inférieur à 32 caractères ;
- un mot de passe initial inférieur à 12 caractères.

## 5. Premier déploiement

Avec sudo sans mot de passe :

```bash
uv run --with ansible-core==2.18.9 \
  ansible-playbook site.yml --ask-vault-pass
```

Si sudo demande un mot de passe :

```bash
uv run --with ansible-core==2.18.9 \
  ansible-playbook site.yml --ask-vault-pass --ask-become-pass
```

Le playbook :

1. installe Docker et Compose si nécessaire ;
2. crée les répertoires, volumes et secrets ;
3. télécharge l’archive immuable du tag configuré ;
4. construit l’image JEV ;
5. démarre JEV et Caddy ;
6. obtient le certificat HTTPS ;
7. vérifie `/healthz` et la version attendue ;
8. active le timer de sauvegarde uniquement après validation du service.

Vérifier le résultat :

```bash
curl -fsS https://51-83-120-42.sslip.io/healthz
```

Réponse attendue :

```json
{"ok":true,"version":"2.4.1","auth_required":true}
```

Après la première connexion administrateur, vider le mot de passe d’amorçage dans le Vault :

```yaml
jev_admin_bootstrap_password: ""
```

Puis rejouer `site.yml`. Le mot de passe Argon2id déjà enregistré en base est conservé.

## 6. Exploitation courante

État de la pile :

```bash
cd /opt/jev/current
sudo docker compose --project-name jev \
  --env-file /etc/jev/production.env \
  -f deploy/compose.production.yml ps
```

Journaux :

```bash
sudo docker compose --project-name jev \
  --env-file /etc/jev/production.env \
  -f deploy/compose.production.yml \
  logs --since=30m jev caddy
```

Sauvegardes :

```bash
sudo systemctl status jev-backup.timer
sudo systemctl list-timers jev-backup.timer
sudo jev-backup
sudo journalctl -u jev-backup.service
```

Les sauvegardes sont vérifiées par empreinte SHA-256 et par
`PRAGMA integrity_check` sur la base SQLite.

## 7. Mise à jour

Modifier `jev_version` dans `group_vars/all/main.yml`, puis rejouer `site.yml`.

Avant chaque mise à jour, le rôle :

- crée et vérifie une sauvegarde ;
- conserve la release, l’environnement et l’image précédents ;
- déploie la nouvelle version ;
- restaure automatiquement code, configuration, image et données si le healthcheck échoue.

## 8. Restauration et rollback

Restaurer une archive :

```bash
sudo jev-restore /var/backups/jev/jev-backup-YYYYMMDDTHHMMSS-manual-xxxxxx.zip
```

La restauration vérifie l’archive, crée une sauvegarde de sécurité, refuse d’agir pendant
une tâche active et redémarre JEV après l’écriture atomique des données.

Revenir à la release précédente :

```bash
sudo jev-rollback
```

Le rollback échange la release, l’environnement, l’image et le snapshot de données associés.

## 9. Décommissionner JEV

La décommission utilise `decommission.yml`. Elle exige toujours la confirmation explicite :

```text
jev_decommission_confirm=true
```

Docker et UFW ne sont jamais désinstallés ou réinitialisés par ce playbook.

### Mode standard : conserver les données

Ce mode retire l’application mais conserve les sauvegardes et volumes pour permettre une
réinstallation ultérieure :

```bash
cd /chemin/vers/job_eval/deploy/ansible
uv run --with ansible-core==2.18.9 \
  ansible-playbook decommission.yml \
  --ask-vault-pass --ask-become-pass \
  -e jev_decommission_confirm=true
```

Supprimé :

- conteneurs et réseaux du projet Compose `jev` ;
- images `jev-webapp:*` ;
- `/opt/jev` et `/etc/jev` ;
- secrets applicatifs dans `/etc/jev/secrets/*` ;
- scripts `/usr/local/sbin/jev-*` ;
- unités systemd de sauvegarde ;
- utilisateur système `jev`.

Conservé :

- `/var/backups/jev` ;
- volume `jev-data` ;
- volumes `jev-caddy-data` et `jev-caddy-config` ;
- Docker, son dépôt APT et les autres conteneurs ;
- l’image générique `caddy:2-alpine`, laissée en cache si aucun autre nettoyage Docker ne la retire ;
- UFW et toutes ses règles.

Pour réinstaller avec les données conservées, rejouer simplement `site.yml` avec les mêmes
noms de volumes.

### Mode purge : suppression irréversible des données

Ce mode ajoute la suppression des sauvegardes, de la base, des documents et des certificats :

```bash
uv run --with ansible-core==2.18.9 \
  ansible-playbook decommission.yml \
  --ask-vault-pass --ask-become-pass \
  -e jev_decommission_confirm=true \
  -e jev_decommission_purge_data=true
```

La purge supprime également :

- `/var/backups/jev` ;
- `jev-data` ;
- `jev-caddy-data` ;
- `jev-caddy-config`.

Cette opération est irréversible. Copier d’abord une archive vérifiée hors du serveur si les
données peuvent encore être utiles.

### Vérifier la décommission

```bash
sudo docker ps -a --filter label=com.docker.compose.project=jev
sudo docker volume ls --filter name=jev
sudo systemctl status jev-backup.timer
sudo test ! -e /opt/jev && echo "releases supprimées"
sudo test ! -e /etc/jev && echo "configuration supprimée"
```

En mode standard, les volumes JEV doivent encore apparaître. En mode purge, ils ne doivent
plus exister.

## 10. Pare-feu

Par défaut, `jev_manage_firewall: false` : le rôle ne modifie pas UFW.

S’il est activé, le rôle autorise le port SSH configuré, TCP 80/443 et UDP 443. La
décommission laisse ces règles intactes afin de ne pas couper un autre service. Leur retrait
reste une décision d’exploitation explicite :

```bash
sudo ufw status numbered
sudo ufw delete allow 80/tcp
sudo ufw delete allow 443/tcp
sudo ufw delete allow 443/udp
```

Ne jamais supprimer la règle SSH sans moyen d’accès alternatif.

## 11. Diagnostic

### Le certificat HTTPS ne peut pas être obtenu

Vérifier :

- que le domaine résout vers l’IP publique ;
- que TCP 80/443 est autorisé par le fournisseur et UFW ;
- qu’aucun autre service n’écoute déjà sur 80/443 ;
- que Docker peut résoudre les domaines externes.

```bash
sudo ss -ltnup | grep -E ':(80|443)\b' || true
getent hosts api.zerossl.com
sudo docker run --rm alpine:3.22 nslookup api.zerossl.com
```

### Le port 443 est déjà utilisé

```bash
sudo ss -ltnp '( sport = :443 )'
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
tailscale serve status
```

Caddy doit disposer des ports publics nécessaires, ou être configuré pour écouter seulement
sur une adresse qui n’est pas déjà utilisée.

### Voir la configuration effective

```bash
sudo docker compose --project-name jev \
  --env-file /etc/jev/production.env \
  -f /opt/jev/current/deploy/compose.production.yml config
```

## 12. Vérifications du dépôt

Depuis la racine du dépôt :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_app_js.mjs
uv run --with ansible-core==2.18.9 \
  ansible-playbook deploy/ansible/site.yml --syntax-check \
  -i deploy/ansible/inventory.example.ini
uv run --with ansible-core==2.18.9 \
  ansible-playbook deploy/ansible/decommission.yml --syntax-check \
  -i deploy/ansible/inventory.example.ini
uv run --with ansible-lint ansible-lint deploy/ansible
```
