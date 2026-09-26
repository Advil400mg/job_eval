#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 /chemin/production.env https://domaine [--insecure]" >&2
  exit 2
fi

ENV_FILE="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1")"
BASE_URL="${2%/}"
INSECURE="${3:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="$ROOT/deploy/compose.production.yml"
PROJECT="jev-v24-smoke"
CURL=(curl --fail --silent --show-error)
[[ "$INSECURE" == "--insecure" ]] && CURL+=(-k)

[[ -f "$ENV_FILE" ]] || { echo "Fichier d’environnement absent: $ENV_FILE" >&2; exit 2; }

COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d --build

for _ in $(seq 1 40); do
  if health="$("${CURL[@]}" "$BASE_URL/healthz" 2>/dev/null)"; then
    break
  fi
  sleep 2
done

printf '%s' "${health:-}" | python3 -c '
import json,sys
from pathlib import Path
health=json.load(sys.stdin)
namespace={}
exec(Path("app/version.py").read_text(), namespace)
assert health == {"ok": True, "version": namespace["APP_VERSION"], "auth_required": True}, health
'

jev_container="$("${COMPOSE[@]}" ps -q jev)"
published_port="$(docker inspect "$jev_container" | python3 -c 'import json,sys; info=json.load(sys.stdin)[0]; ports=info.get("NetworkSettings", {}).get("Ports") or {}; print(ports.get("8000/tcp") or "")')"
if [[ -n "$published_port" ]]; then
  echo "Le port applicatif 8000 ne doit pas être publié: $published_port" >&2
  exit 1
fi

"${COMPOSE[@]}" exec -T jev python -c \
  'import urllib.request; assert urllib.request.urlopen("https://example.com", timeout=10).status == 200'

printf 'Smoke production OK: %s\n' "$health"
