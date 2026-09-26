# Déploiement de production JEV v2.4

Ce dossier déploie une instance JEV sur Ubuntu 24.04 LTS ou Debian 12 amd64 :

- application FastAPI dans un conteneur non privilégié ;
- Caddy comme seul service publié sur les ports 80 et 443 ;
- HTTPS automatique avec renouvellement des certificats ;
- volume Docker nommé pour les données ;
- répertoire hôte séparé pour les sauvegardes ;
- sauvegarde quotidienne vérifiée par systemd ;
- sauvegarde préalable et image de rollback avant chaque mise à jour.

## 1. Prérequis

Sur la machine de contrôle :

- Ansible Core 2.16 ou plus récent ;
- accès SSH par clé ;
- accès `sudo` sur le serveur.

Sur le serveur :

- Ubuntu 24.04 LTS ou Debian 12 amd64 ;
- au moins 2 Go de RAM et 10 Go de stockage disponible ;
- ports TCP 22, 80 et 443 accessibles ;
- port UDP 443 recommandé pour HTTP/3 ;
- enregistrement DNS A/AAAA du domaine pointant déjà vers le serveur.

Le port 8000 de JEV n’est jamais publié sur l’hôte.

## 2. Préparer Ansible

Depuis `deploy/ansible` :

```bash
cp inventory.example.ini inventory.ini
mkdir -p group_vars/all
cp group_vars/all/main.example.yml group_vars/all/main.yml
cp group_vars/all/vault.example.yml group_vars/all/vault.yml
```

Adapter `inventory.ini` et `group_vars/all/main.yml`, puis chiffrer les secrets :

```bash
ansible-vault encrypt group_vars/all/vault.yml
```

Les trois fichiers réels sont ignorés par Git. Seuls les exemples doivent être versionnés.

Variables obligatoires :

- `jev_domain` : nom DNS sans `https://` ;
- `jev_acme_email` : adresse utilisée par l’autorité de certification ;
- `jev_openrouter_api_key` : clé OpenRouter, dans le Vault ;
- `jev_session_secret` : valeur aléatoire stable d’au moins 32 caractères, dans le Vault ;
- `jev_admin_bootstrap_password` : mot de passe initial d’au moins 12 caractères.

Une valeur de secret peut être générée avec :

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Après création du premier administrateur, `jev_admin_bootstrap_password` peut être vidé et le
playbook rejoué. Le mot de passe du compte est conservé sous forme Argon2id dans la base.

## 3. Vérifier avant le premier déploiement

```bash
ansible-playbook --syntax-check site.yml
ansible-lint .
ansible all -m ping --ask-vault-pass
```

Le rôle refuse explicitement :

- une distribution ou une architecture non prise en charge ;
- un domaine contenant un schéma ou un port ;
- un secret de session trop court ;
- une clé OpenRouter absente ;
- un mot de passe initial trop court.

## 4. Premier déploiement

La source de production par défaut est l’archive immuable du tag `v2.4.0` :

```bash
ansible-playbook site.yml --ask-vault-pass
```

Pour une recette de préversion seulement, il est possible de surcharger temporairement
`jev_release_url` avec l’archive de la branche `dev`. Une production doit toujours revenir à
une archive taguée et, idéalement, définir `jev_release_checksum`.

Le playbook :

1. installe Docker depuis le dépôt officiel ;
2. crée `/opt/jev`, `/etc/jev`, `/etc/jev/secrets` et `/var/backups/jev` ;
3. télécharge et extrait la release ;
4. écrit l’environnement non secret dans `/etc/jev/production.env` (`0600`) et les
   secrets dans des fichiers individuels `/etc/jev/secrets/*` (`0400`) ;
5. construit l’image JEV ;
6. démarre JEV et Caddy ;
7. attend `https://<domaine>/healthz` avec un certificat valide ;
8. vérifie que la version retournée est exactement celle demandée.

Le pare-feu n’est pas activé par défaut afin de ne jamais couper un port SSH personnalisé.
Pour laisser le rôle gérer UFW :

```yaml
jev_manage_firewall: true
jev_ssh_port: 22
```

## 5. Mise à jour

Modifier `jev_version`, ainsi que `jev_release_checksum` lorsqu’il est utilisé, puis rejouer :

```bash
ansible-playbook site.yml --ask-vault-pass
```

Avant la mise à jour, le rôle :

- conserve l’image en cours sous le tag local `jev-webapp:rollback` ;
- crée une sauvegarde applicative ;
- vérifie l’archive et l’intégrité SQLite.

Si le nouvel endpoint HTTPS ne devient pas sain, le rôle restaure automatiquement la release,
l’environnement, l’image et le snapshot de données précédents, puis vérifie à nouveau le
healthcheck avant de signaler l’échec du déploiement.

## 6. Sauvegardes

Le timer `jev-backup.timer` déclenche quotidiennement `/usr/local/sbin/jev-backup`.
La planification et la rétention sont configurables :

```yaml
jev_backup_schedule: "*-*-* 03:15:00"
jev_backup_retention_days: 14
```

Commandes d’exploitation :

```bash
systemctl status jev-backup.timer
systemctl list-timers jev-backup.timer
sudo jev-backup
journalctl -u jev-backup.service
```

Les archives sont placées dans `/var/backups/jev`. Chaque sauvegarde contient :

- une copie cohérente de SQLite réalisée par l’API de sauvegarde SQLite ;
- les profils, CV sources, CV générés et journaux utilisateur ;
- un manifeste avec taille et SHA-256 de chaque fichier.

Après création, `deploy/scripts/verify-backup.py` contrôle les empreintes, les chemins ZIP et
`PRAGMA integrity_check`. Une archive invalide fait échouer le service de sauvegarde.

La rotation locale n’est pas une sauvegarde hors site. Pour une production importante, copier
`/var/backups/jev` vers un stockage distant chiffré avec l’outil d’infrastructure choisi.

## 7. Restauration

La restauration est volontairement explicite :

```bash
sudo jev-restore /var/backups/jev/jev-backup-YYYYMMDDTHHMMSS-manual-xxxxxx.zip
```

Le script :

1. vérifie l’archive hors du conteneur ;
2. demande à JEV de créer une sauvegarde de sécurité `pre-restore` ;
3. refuse la restauration si une tâche est active ;
4. restaure les fichiers atomiquement ;
5. redémarre JEV et attend son healthcheck.

## 8. Rollback manuel

L’image précédant la dernière mise à jour réussie ou tentée est conservée localement :

```bash
sudo jev-rollback
```

Le script crée d’abord une sauvegarde de l’état courant, restaure le snapshot associé à la
release précédente, échange atomiquement les liens `current`/`previous` et les environnements,
réassocie l’image `rollback`, puis vérifie `/healthz`. La sauvegarde créée au début devient le
snapshot du prochain retour arrière, ce qui permet de revenir dans l’autre sens.

## 9. Diagnostic

```bash
cd /opt/jev/current
docker compose --project-name jev --env-file /etc/jev/production.env \
  -f deploy/compose.production.yml ps
docker compose --project-name jev --env-file /etc/jev/production.env \
  -f deploy/compose.production.yml logs --since=30m jev caddy
curl -fsS https://votre-domaine/healthz
```

Réponse attendue :

```json
{"ok": true, "version": "2.4.0", "auth_required": true}
```

Caddy est le seul service publié. Si le port 8000 apparaît dans `docker ps` sous la forme
`0.0.0.0:8000->8000`, la pile utilisée n’est pas la pile de production.

## 10. Vérifications du dépôt

Depuis la racine :

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_app_js.mjs
ansible-playbook -i deploy/ansible/inventory.example.ini deploy/ansible/site.yml --syntax-check
ansible-lint deploy/ansible
docker compose --env-file /chemin/vers/un/env-de-test \
  -f deploy/compose.production.yml config --quiet
```
