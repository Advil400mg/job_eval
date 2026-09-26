#!/usr/bin/env python3
"""Lance l'application avec la configuration résolue (config.toml + environnement).

    python3 scripts/serve.py [--reload] [--check]

L'hôte et le port viennent de HOST / PORT, sinon de [app] dans config.toml.
`--check` affiche la configuration effective (sans aucun secret) et s'arrête.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from app import config, cv, security  # noqa: E402


def describe(settings: dict) -> str:
    cv_ok, cv_why = cv.available()
    exists = "absente (valeurs par défaut)" if not settings["config_file_exists"] else "lue"
    lines = [
        f"config     : {settings['config_file']} — {exists}",
        f"données    : {settings['data_dir'] / 'users'} — isolées par utilisateur",
        f"évaluateur : {settings['evaluator_path']}",
        f"modèle Jev : {settings['openrouter']['model']}",
        f"base       : {settings['db_file']}",
        f"clé API    : {'OK' if settings['api_key_set'] else 'ABSENTE — l’évaluation échouera'}",
        "accès web  : comptes sur invitation, authentification obligatoire",
        f"moteur CV  : {'OK' if cv_ok else 'indisponible'} — {cv_why}",
    ]
    return "\n".join("  " + line for line in lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lance l'évaluateur d'offres Jev")
    parser.add_argument("--check", action="store_true",
                        help="affiche la configuration effective puis quitte")
    parser.add_argument("--reload", action="store_true", help="rechargement à chaud")
    parser.add_argument("--host", help="adresse d'écoute (sinon HOST ou config.toml)")
    parser.add_argument("--port", type=int, help="port d'écoute (sinon PORT ou config.toml)")
    args, extra = parser.parse_known_args()
    if extra:
        print(f"arguments ignorés : {' '.join(extra)}", file=sys.stderr)

    settings = config.settings()
    print("Configuration effective :")
    print(describe(settings))
    if args.check:
        return 0

    settings["data_dir"].mkdir(parents=True, exist_ok=True)
    settings["cv"]["out_dir"].mkdir(parents=True, exist_ok=True)
    Path(settings["db_file"]).parent.mkdir(parents=True, exist_ok=True)

    host = args.host or os.environ.get("HOST") or settings["host"]
    port = int(args.port or os.environ.get("PORT") or settings["port"])
    security.validate_configuration()
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if (host not in local_hosts and not os.environ.get("JEV_SESSION_SECRET")
            and not settings["security"]["allow_insecure_remote"]):
        print(
            "ERREUR : écoute distante refusée sans JEV_SESSION_SECRET stable. "
            "Définis un secret d’au moins 32 caractères ou JEV_ALLOW_INSECURE_REMOTE=true.",
            file=sys.stderr,
        )
        return 2
    print(f"\n→ http://{host}:{port}")

    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())