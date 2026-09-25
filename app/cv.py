"""Génération de CV : exécution d'un moteur externe configurable.

Le moteur est décrit par une commande gabarit dans config.toml :

    command = "cv-tailor {url} --json --out-dir {out_dir} --no-jev --no-telegram {extra}"

Placeholders : {url}, {out_dir}, {extra} (--dry-run quand l'email n'est pas demandé).
Par défaut, c'est le moteur `cv-tailor` du Job Hunt (LLM borné par CV_MASTER.json,
validateur anti-invention, PDF une page) ; ailleurs, n'importe quelle commande
produisant un PDF et imprimant un JSON contenant au moins {"pdf": "..."}.

Rien n'est inventé ici : si le moteur est absent ou refuse, l'API remonte son
message tel quel.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Callable

from . import config


class CvError(RuntimeError):
    pass


class CvCancelled(CvError):
    pass


def _settings() -> dict:
    return config.settings()["cv"]


def command_template() -> str:
    return str(_settings().get("command") or "")


def enabled() -> bool:
    return bool(_settings().get("enabled", True)) and bool(command_template())


def out_dir() -> str:
    return str(_settings()["out_dir"])


def _expand(template: str, url: str, directory: str, extra: str) -> list[str]:
    rendered = (template.replace("{url}", url)
                        .replace("{out_dir}", directory)
                        .replace("{extra}", extra)
                        .replace("{python}", sys.executable))
    # shlex.split : la commande est un gabarit shell simple, sans redirection ni pipe
    return shlex.split(rendered)


def available() -> tuple[bool, str]:
    """(disponible, explication) — sans exécuter la commande."""
    if not enabled():
        return False, "moteur CV désactivé ([cv] enabled = false ou command absente)"
    try:
        argv = _expand(command_template(), "URL", "OUT", "")
    except ValueError as exc:
        return False, f"commande CV illisible ({exc})"
    if not argv:
        return False, "commande CV vide"
    binary = argv[0]
    if os.path.sep in binary:
        if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
            return False, f"moteur CV introuvable ou non exécutable : {binary}"
    else:
        from shutil import which
        if not which(binary):
            return False, f"commande CV absente du PATH : {binary}"
    config_file = config.settings()["config_file"]
    return True, f"{binary} (config : {config_file})"


def _extract_summary(stdout: str) -> dict:
    """Le moteur imprime son JSON final sur plusieurs lignes (indent=2) :
    on reconstruit le dernier objet JSON complet plutôt que d'attendre une ligne."""
    lines = stdout.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == "{":
            try:
                return json.loads("\n".join(lines[index:]))
            except json.JSONDecodeError:
                continue
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    return {}


def generate(url: str, send_email: bool = False, timeout: int | None = None,
             should_cancel: Callable[[], bool] | None = None) -> dict:
    """Exécute le moteur pour une offre et renvoie son résumé JSON."""
    ok, why = available()
    if not ok:
        raise CvError(why)

    settings = _settings()
    timeout = timeout or settings["timeout_seconds"]
    directory = os.path.join(out_dir(), f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}")
    os.makedirs(directory, exist_ok=True)

    extra = "" if send_email else "--dry-run"
    argv = _expand(command_template(), url, directory, extra)
    env, _ = config.cv_environment()
    env["CV_URL"] = url

    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        cwd=str(config.APP_DIR),
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if should_cancel and should_cancel():
                proc.terminate()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                raise CvCancelled("génération annulée")
            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                raise CvError(f"délai de génération dépassé ({timeout} s)")
    payload = _extract_summary(stdout or "")
    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip().splitlines()
        message = "\n".join(detail[-4:]) if detail else f"exit {proc.returncode}"
        raise CvError(message)
    if not payload.get("pdf"):
        raise CvError("le moteur n'a pas renvoyé de chemin de PDF")
    if not os.path.isfile(payload["pdf"]):
        raise CvError(f"PDF annoncé introuvable : {payload['pdf']}")
    payload["output_dir"] = directory
    return payload
