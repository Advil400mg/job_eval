#!/usr/bin/env bash
# Lance l'application en local, sans Docker.
#
#   ./run-local.sh                          -> config.toml du dossier (ou valeurs par défaut)
#   ./run-local.sh --config /chemin/conf.toml
#   HOST=0.0.0.0 PORT=8077 ./run-local.sh
#
# Crée le venv au premier lancement (uv si présent, sinon python -m venv), affiche
# la configuration effective, puis démarre uvicorn. La clé API vient de la variable
# OPENROUTER_API_KEY ou du fichier de configuration : rien n'est deviné ici.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f "$DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$DIR/.env"
  set +a
fi

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --config) export JEV_CONFIG="$2"; shift 2 ;;
    --config=*) export JEV_CONFIG="${1#*=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
if [ -z "${JEV_CONFIG:-}" ] && [ -f "$DIR/config.toml" ]; then
  export JEV_CONFIG="$DIR/config.toml"
fi

UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$candidate" ]; then UV="$candidate"; break; fi
  done
fi

PY="$DIR/.venv/bin/python"
if [ ! -x "$DIR/.venv/bin/uvicorn" ]; then
  if [ -d "$DIR/.venv" ]; then
    echo "→ venv incomplet détecté, recréation…"
    rm -rf "$DIR/.venv"
  else
    echo "→ création du venv et installation des dépendances…"
  fi
  if [ -n "$UV" ]; then
    "$UV" venv --python 3.12 "$DIR/.venv"
    "$UV" pip install --python "$PY" -r "$DIR/requirements.txt"
  else
    python3 -m venv "$DIR/.venv"
    "$DIR/.venv/bin/pip" install --upgrade pip
    "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
  fi
fi

exec "$PY" "$DIR/scripts/serve.py" ${ARGS+"${ARGS[@]}"}