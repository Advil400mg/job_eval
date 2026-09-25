#!/usr/bin/env python3
"""CV adapté à une offre d'emploi, livré par email (+ notification Telegram).

Usage :
    cv-tailor <url_de_l_offre> [options]

Étapes : lecture de l'offre -> sélection/réformulation LLM strictement bornée par
CV_MASTER.json -> validation anti-invention -> PDF -> évaluation Jev optionnelle
-> email -> ping Telegram. Aucun fait n'est inventé : le master est la seule source.
"""
import argparse
import base64
from html import unescape as html_unescape
import imaplib
import json
import os
import re
import smtplib
import shutil
import ssl
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import render_cv_pdf  # noqa: E402
import validate_tailoring  # noqa: E402

APP_DIR = HERE.parent
sys.path.insert(0, str(APP_DIR))
from app import network as safe_network  # noqa: E402

# Chemins configurables : par défaut tout est relatif au dossier de l'application,
# ce qui rend le moteur utilisable sans aucune installation Hermes.
# Surcharges : CV_MASTER, CV_PROFILE, CV_ENV_FILE, CV_DATA_DIR, CV_OUT_DIR, CV_RUNS, CV_JEV


def _path(env_name, default):
    raw = os.environ.get(env_name)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(default)


DATA_DIR = _path('CV_DATA_DIR', APP_DIR / 'data')
MASTER_PATH = _path('CV_MASTER', APP_DIR / 'data' / 'CV_MASTER.json')
PROFILE_PATH = _path('CV_PROFILE', APP_DIR / 'data' / 'PROFILE.json')
ENV_PATH = _path('CV_ENV_FILE', APP_DIR / '.env')
DEFAULT_OUT = _path('CV_OUT_DIR', DATA_DIR / 'cv')
RUNS = _path('CV_RUNS', DATA_DIR / 'cv-runs')
JEV = _path('CV_JEV', APP_DIR / 'scripts' / 'evaluate_job.py')
DEFAULT_MODEL = os.environ.get('CV_MODEL', 'deepseek/deepseek-v4.1-flash')

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')


def log(msg):
    print(msg, flush=True)


def read_env(names):
    """Variables demandées : environnement d'abord, puis fichier ENV_PATH s'il existe."""
    out = {name: os.environ[name] for name in names if os.environ.get(name)}
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.strip().removeprefix('export ')
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, val = line.split('=', 1)
            k, val = k.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'': 
                val = val[1:-1]
            if k in names and k not in out:
                out[k] = val
    return out


# ── 1. offre ──────────────────────────────────────────────────────────────

def html_to_text(html):
    html = re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>', ' ', html)
    html = re.sub(r'(?is)<br\s*/?>|</(p|div|li|tr|h[1-6])>', '\n', html)
    html = re.sub(r'(?s)<[^>]+>', ' ', html)
    html = html_unescape(html.replace('&nbsp;', ' '))
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in html.splitlines()]
    return '\n'.join(l for l in lines if l)


def json_ld_job(html):
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and 'JobPosting' in str(it.get('@type', '')):
                return it
    return None


def meta_content(raw, prop):
    m = re.search(r'(?is)<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]*>', raw)
    if not m:
        return ''
    c = re.search(r'(?is)content=["\'](.*?)["\']', m.group(0))
    return html_unescape(c.group(1)).strip() if c else ''


GENERIC_TITLE = re.compile(r'^(offre d.emploi|offres? d.emploi|jobs?|careers?|recrutement|'
                           r'nos offres|accueil|home)\b', re.I)


def fetch_offer(url):
    raw = safe_network.fetch_text(
        url,
        headers={'User-Agent': UA, 'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8'},
        timeout=45,
        max_bytes=5_000_000,
    )
    text = html_to_text(raw)
    job = json_ld_job(raw) or {}
    org = job.get('hiringOrganization') or {}
    loc = job.get('jobLocation') or {}
    addr = (loc.get('address') if isinstance(loc, dict) else {}) or {}
    meta = {
        'title': (job.get('title') or '').strip(),
        'company': (org.get('name') if isinstance(org, dict) else '') or '',
        'location': ', '.join(x for x in [addr.get('addressLocality'), addr.get('addressRegion'),
                                          addr.get('addressCountry')] if x),
        'published_at': (job.get('datePosted') or '').strip(),
        'contract': (job.get('employmentType') or '') if isinstance(job.get('employmentType'), str) else '',
    }
    host = re.sub(r'^www\.', '', urllib.parse.urlparse(url).netloc)
    meta['site'] = meta_content(raw, 'og:site_name') or host
    candidates = [meta_content(raw, 'og:title'), meta_content(raw, 'twitter:title')]
    m = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', raw)
    if m:
        candidates.append(html_to_text(m.group(1)).strip())
    m = re.search(r'(?is)<title[^>]*>(.*?)</title>', raw)
    if m:
        candidates.append(html_to_text(m.group(1)).strip())
    for cand in candidates:
        cand = re.sub(r'\s*[|•—–-]\s*(?:DGSE|accueil|home|site officiel).*$', '', cand, flags=re.I).strip()
        if cand and 8 < len(cand) < 160 and not GENERIC_TITLE.match(cand):
            meta['title'] = meta['title'] or cand
            break
    if not meta['title']:
        for line in text.splitlines()[:40]:
            if 12 < len(line) < 140 and not GENERIC_TITLE.match(line):
                meta['title'] = line
                break
    if not meta['company']:
        meta['company'] = meta_content(raw, 'og:site_name') or host
    return text, meta, raw


# ── 2. LLM ────────────────────────────────────────────────────────────────

SYSTEM = """Tu adaptes le CV d'un candidat à une offre d'emploi, dans la langue du CV.

RÈGLES ABSOLUES
- La seule source de faits autorisée est le master JSON fourni. Rien d'autre.
- Interdit d'inventer : entreprise, poste, date, diplôme, technologie, outil, chiffre,
  certification, responsabilité, résultat, ancienneté ou niveau de séniorité.
- Les stages restent présentés comme des stages.
- Tu peux : choisir l'ordre des expériences, des groupes de compétences et des projets ;
  sélectionner et légèrement reformuler les puces (mêmes faits, vocabulaire de l'offre) ;
  écrire le titre sous le nom et le paragraphe PROFIL.
- Les puces reformulées doivent rester très proches des puces du master (vocabulaire du master,
  plus les mots de liaison nécessaires).

FORMAT DE SORTIE : un unique objet JSON, sans texte autour :
{
  "headline": "titre court sous le nom, mots pris dans headline_words",
  "profile": "paragraphe PROFIL, 400-750 caractères, uniquement des faits du master",
  "experiences": [{"id": "<id du master>", "bullets": ["...", "..."]}],
  "skill_groups_order": ["<id>", "..."],
  "projects_order": ["<id>", "..."],
  "include_eligibility": true/false,
  "offer_meta": {"title": "intitulé exact du poste tel qu'écrit dans l'offre",
                 "company": "organisation qui recrute", "location": "lieu du poste",
                 "reference": "référence de l'offre si elle apparaît, sinon \"\""},
  "emphasis": ["mots-clés de l'offre réellement couverts par le profil (max 8)"],
  "gaps": ["écarts honnêtes entre l'offre et le CV (max 4, factuels)"],
  "notes": ["adaptations réalisées (max 4)"]
}
Toutes les expériences du master doivent apparaître, dans l'ordre d'affichage voulu."""


def llm_tailor(offer_text, master, meta, model, api_key, previous_errors=None):
    payload = {
        'url': '',
        'title': meta.get('title'),
        'company': meta.get('company'),
        'location': meta.get('location'),
        'offer_text': offer_text[:12000],
    }
    user = ("MASTER (seule source de faits) :\n" + json.dumps(master, ensure_ascii=False, indent=1) +
            "\n\nOFFRE :\n" + json.dumps(payload, ensure_ascii=False, indent=1))
    if previous_errors:
        user += ("\n\nLa tentative précédente a été REJETÉE par le validateur anti-invention. "
                 "Corrige exactement ces points et renvoie un JSON complet :\n- "
                 + "\n- ".join(previous_errors[:20]))
    body = {
        'model': model,
        'temperature': 0.2,
        'response_format': {'type': 'json_object'},
        'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}],
    }
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(body).encode('utf-8'),
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json',
                 'X-Title': 'Hermes tailored CV'},
        method='POST')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f'ERROR: OpenRouter HTTP {e.code}: {e.read()[:300]}')
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f'ERROR: OpenRouter injoignable: {e}')
    content = data['choices'][0]['message']['content']
    content = re.sub(r'^```(?:json)?|```$', '', content.strip(), flags=re.M).strip()
    try:
        return json.loads(content), data.get('usage', {})
    except json.JSONDecodeError as e:
        raise SystemExit(f'ERROR: réponse LLM non-JSON: {e}')


# ── 3. envois ─────────────────────────────────────────────────────────────

def send_email(subject, body, attachment, env):
    entry = {'subject': subject, 'to': env.get('EMAIL_ADDRESS', ''), 'status': 'pending'}
    addr = env.get('EMAIL_ADDRESS', '')
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = addr
    msg['To'] = addr
    msg['Message-ID'] = entry['message_id'] = f"<cvtailor-{uuid.uuid4().hex}@hermes>"
    msg.set_content(body, charset='utf-8')
    if attachment:
        p = Path(attachment)
        msg.add_attachment(p.read_bytes(), maintype='application', subtype='pdf', filename=p.name)
    try:
        host, port = env.get('EMAIL_SMTP_HOST', ''), int(env.get('EMAIL_SMTP_PORT') or 465)
        if not (addr and env.get('EMAIL_PASSWORD') and host):
            entry.update(status='failed', error='SMTP incomplet : EMAIL_ADDRESS / EMAIL_PASSWORD / '
                                                 'EMAIL_SMTP_HOST / EMAIL_SMTP_PORT manquants')
            return entry
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=45, context=ctx) as s:
                s.login(addr, env['EMAIL_PASSWORD'])
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=45) as s:
                s.starttls(context=ctx)
                s.login(addr, env['EMAIL_PASSWORD'])
                s.send_message(msg)
        entry.update(status='smtp_accepted', sent_at=datetime.now().isoformat(timespec='seconds'))
    except smtplib.SMTPResponseException as e:
        entry.update(status='failed', error=str(e))
    except (smtplib.SMTPException, OSError) as e:
        entry.update(status='uncertain', error=str(e))
    return entry


def verify_email_arrived(env, message_id, timeout=90):
    host = env.get('EMAIL_IMAP_HOST')
    if not host:
        return {'status': 'not_attempted', 'reason': 'EMAIL_IMAP_HOST absent'}
    port = int(env.get('EMAIL_IMAP_PORT') or 993)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ctx = ssl.create_default_context()
            if port == 993:
                M = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
            else:
                M = imaplib.IMAP4(host, port)
                M.starttls(ssl_context=ctx)
            M.login(env.get('EMAIL_ADDRESS', ''), env.get('EMAIL_PASSWORD', ''))
            M.select('INBOX')
            typ, data = M.search(None, 'HEADER', 'Message-ID', f'"{message_id}"')
            M.logout()
            if typ == 'OK' and data and data[0].strip():
                return {'status': 'received', 'checked_at': datetime.now().isoformat(timespec='seconds')}
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(8)
            continue
        time.sleep(8)
    return {'status': 'not_seen', 'reason': 'non trouvé dans INBOX avant expiration'}


def send_telegram(caption, attachment):
    """Notification Telegram via la CLI hermes. Absente = simple information, pas un échec bloquant."""
    if shutil.which('hermes') is None:
        return {'status': 'unavailable',
                'reason': 'CLI « hermes » absente : notification Telegram ignorée'}
    cmd = ['hermes', 'send', '--to', 'telegram', '--json']
    payload = (caption + (f'\nMEDIA:{attachment}' if attachment else ''))
    r = subprocess.run(cmd + [payload], capture_output=True, text=True, timeout=180)
    info = {'status': 'failed', 'returncode': r.returncode}
    try:
        m = re.search(r'\{.*\}', r.stdout, re.S)
        data = json.loads(m.group(0) if m else r.stdout.strip())
        info['result'] = data
        info['status'] = 'sent' if data.get('success') else 'failed'
        info['message_id'] = data.get('message_id')
    except Exception:
        info['stdout'] = r.stdout[-500:]
        info['stderr'] = r.stderr[-500:]
    return info


# ── 4. Jev ────────────────────────────────────────────────────────────────

def run_jev(url, offer_text, meta, profile, run_dir):
    entry = {'status': 'not_attempted'}
    if not JEV.is_file():
        entry['error'] = 'script Jev introuvable'
        return entry, None
    inp = {
        'url': url, 'title': meta.get('title') or '', 'company': meta.get('company') or '',
        'job_text': offer_text[:12000], 'location': meta.get('location') or '',
        'published_at': meta.get('published_at') or None,
        'minimum_global_score': profile['minimum_global_score'],
        'minimum_confidence': profile['minimum_confidence'],
        'criteria': profile['criteria'],
    }
    (run_dir / 'jev-input.json').write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding='utf-8')
    env = dict(os.environ)
    env['OPENROUTER_API_KEY'] = read_env({'OPENROUTER_API_KEY'}).get('OPENROUTER_API_KEY', '')
    r = subprocess.run([sys.executable, str(JEV), str(run_dir / 'jev-input.json')],
                       capture_output=True, text=True, timeout=300, env=env)
    if r.returncode != 0:
        entry.update(status='failed', error=(r.stderr or r.stdout)[-300:])
        return entry, None
    (run_dir / 'jev-output.json').write_text(r.stdout, encoding='utf-8')
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        entry.update(status='failed', error='sortie Jev illisible')
        return entry, None
    entry.update(status='done', global_score=data.get('global_score'),
                 jev_approved=data.get('jev_approved'),
                 blocking_criteria=data.get('blocking_criteria'),
                 required_criteria_passed=data.get('required_criteria_passed'))
    return entry, data


# ── 5. orchestration ──────────────────────────────────────────────────────

def slug(s, n=48):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-')
    return s[:n].strip('-') or 'offre'


def email_body(result, meta, jev, master, tailoring, pdf):
    L = []
    L.append(f"CV adapté — {meta.get('title') or 'offre'}")
    if meta.get('company'):
        L.append(f"Entreprise : {meta['company']}")
    if meta.get('location'):
        L.append(f"Localisation : {meta['location']}")
    L.append(f"Offre : {result['url']}")
    L.append("")
    L.append(f"Fichier : {pdf}")
    L.append("")
    if jev and jev.get('status') == 'done':
        L.append(f"Adéquation Jev : {jev['global_score']}/100 "
                 f"(seuil {result['minimum_global_score']}) — approuvée : "
                 f"{'oui' if jev.get('jev_approved') else 'non'}")
        if jev.get('blocking_criteria'):
            L.append(f"Critères bloquants : {', '.join(jev['blocking_criteria'])}")
        L.append("")
    if tailoring.get('emphasis'):
        L.append("Mots-clés de l'offre couverts : " + ', '.join(tailoring['emphasis']))
        L.append("")
    if tailoring.get('notes'):
        L.append("Adaptations réalisées :")
        L += [f"  - {n}" for n in tailoring['notes']]
        L.append("")
    L.append("Écarts honnêtes (à assumer en entretien) :")
    for g in list(tailoring.get('gaps') or []) + master.get('gap_notes_for_email', []):
        L.append(f"  - {g}")
    L.append("")
    if tailoring.get('include_eligibility') and master.get('eligibility_defense_only'):
        L.append("Éléments d'éligibilité déclarés dans le CV : "
                 + " — ".join(master['eligibility_defense_only']))
        L.append("")
    if result.get('warnings'):
        L.append("Avertissements du validateur : " + ' | '.join(result['warnings']))
    return '\n'.join(L)


def telegram_caption(result, meta, jev, tailoring):
    head = f"CV adapté prêt : {meta.get('title') or 'offre'}"
    if meta.get('company'):
        head += f" — {meta['company']}"
    if jev and jev.get('status') == 'done':
        head += f"\nJev {jev['global_score']}/100 ({'approuvée' if jev.get('jev_approved') else 'non approuvée'})"
    if tailoring.get('emphasis'):
        head += "\nPriorités : " + ', '.join(tailoring['emphasis'][:6])
    if tailoring.get('gaps'):
        head += "\nÉcart principal : " + tailoring['gaps'][0][:180]
    head += f"\nEmail : {result.get('email', {}).get('status')}"
    return head


def main():
    ap = argparse.ArgumentParser(description='CV adapté à une offre -> email + Telegram')
    ap.add_argument('url', help="URL de l'offre")
    ap.add_argument('--offer-text', help="fichier contenant le texte de l'offre (bypass du fetch)")
    ap.add_argument('--title'), ap.add_argument('--company'), ap.add_argument('--location')
    ap.add_argument('--out-dir', default=str(DEFAULT_OUT))
    ap.add_argument('--model')
    ap.add_argument('--no-email', action='store_true')
    ap.add_argument('--no-telegram', action='store_true')
    ap.add_argument('--no-jev', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='produit le PDF, n envoie rien')
    ap.add_argument('--json', action='store_true', help='sortie JSON machine')
    args = ap.parse_args()

    if not MASTER_PATH.is_file():
        raise SystemExit(f'ERROR: master de faits introuvable : {MASTER_PATH} '
                         f'(initialiser l’application ou définir CV_MASTER)')
    if not PROFILE_PATH.is_file():
        raise SystemExit(f'ERROR: profil introuvable : {PROFILE_PATH} (définir CV_PROFILE)')
    master = json.loads(MASTER_PATH.read_text(encoding='utf-8'))
    profile = json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
    model = args.model or DEFAULT_MODEL
    api_key = read_env({'OPENROUTER_API_KEY'}).get('OPENROUTER_API_KEY', '')
    if not api_key:
        raise SystemExit('ERROR: OPENROUTER_API_KEY absente (variable d’environnement, '
                         f'ou fichier {ENV_PATH})')

    # offre
    raw_html = ''
    if args.offer_text:
        text = Path(args.offer_text).read_text(encoding='utf-8')
        meta = {'title': args.title or '', 'company': args.company or '',
                'location': args.location or '', 'published_at': '', 'contract': ''}
    else:
        try:
            text, meta, raw_html = fetch_offer(args.url)
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f'ERROR: lecture de l\'offre impossible: {e} '
                             f'(utiliser --offer-text avec le texte de la page)')
    if len(text) < 800:
        raise SystemExit(f'ERROR PAGE_TOO_THIN: {len(text)} caractères extraits pour {args.url}. '
                         f'Récupérer le texte avec le navigateur puis relancer avec --offer-text.')
    log(f"offre : {meta.get('title') or '(titre non détecté)'} | {meta.get('company') or '?'} | "
        f"{len(text)} caractères")

    stamp = datetime.now().strftime('%Y-%m-%dT%H%M%S')
    run_dir = RUNS / f"{stamp}-{slug(meta.get('title') or 'offre')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # tailoring + validation
    tailoring, usage = llm_tailor(text, master, meta, model, api_key)
    check = validate_tailoring.validate(master, tailoring, text)
    if not check['ok']:
        log(f"validation : {len(check['violations'])} violation(s), nouvelle tentative corrigée")
        tailoring, usage2 = llm_tailor(text, master, meta, model, api_key, check['violations'])
        usage = usage2
        check = validate_tailoring.validate(master, tailoring, text)
    if not check['ok']:
        (run_dir / 'rejected-tailoring.json').write_text(json.dumps(tailoring, ensure_ascii=False, indent=2))
        (run_dir / 'rejections.txt').write_text('\n'.join(check['violations']), encoding='utf-8')
        raise SystemExit('ERROR VALIDATION: CV non produit, contenu non conforme au master :\n- '
                         + '\n- '.join(check['violations'][:15]))
    log(f"validation : OK ({len(check['warnings'])} avertissement(s))")

    om = tailoring.get('offer_meta') or {}
    for key in ('title', 'company', 'location', 'reference'):
        val = (om.get(key) or '').strip()
        if val:
            meta[key] = val
    meta['company'] = meta.get('company') or meta.get('site') or ''
    log(f"offre retenue : {meta.get('title')} | {meta.get('company')} | {meta.get('location')}"
        + (f" | réf. {meta['reference']}" if meta.get('reference') else ''))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = f"_{slug(meta['reference'], 24)}" if meta.get('reference') else ''
    pdf = out_dir / (f"CV_{slug(meta.get('company') or 'entreprise', 24)}_"
                     f"{slug(meta.get('title') or 'poste')}{ref}_{datetime.now():%Y%m%d}.pdf")
    pages, scale = render_cv_pdf.render(
        master, tailoring, pdf, include_eligibility=bool(tailoring.get('include_eligibility')),
        subtitle=f"CV {master['identity']['name'].title()} — {meta.get('title') or 'offre'}")
    log(f"pdf : {pdf} ({pages} page(s), échelle {scale:.2f})")

    # Jev
    jev, _jev_data = ({'status': 'skipped'}, None)
    if not args.no_jev:
        jev, _jev_data = run_jev(args.url, text, meta, profile, run_dir)
    log(f"jev : {jev['status']}" + (f" {jev.get('global_score')}/100" if jev.get('status') == 'done' else ''))

    result = {
        'url': args.url, 'offer': meta, 'pdf': str(pdf), 'pages': pages, 'scale': scale,
        'model': model, 'usage': usage, 'warnings': check['warnings'], 'jev': jev,
        'tailoring': tailoring, 'minimum_global_score': profile['minimum_global_score'],
        'dry_run': args.dry_run,
    }

    if not args.dry_run:
        env = read_env({'EMAIL_ADDRESS', 'EMAIL_PASSWORD', 'EMAIL_SMTP_HOST', 'EMAIL_SMTP_PORT',
                        'EMAIL_IMAP_HOST', 'EMAIL_IMAP_PORT'})
        subject = (f"CV adapté — {meta.get('title') or 'offre'}"
                   + (f" — {meta['company']}" if meta.get('company') else '')
                   + (f" (réf. {meta['reference']})" if meta.get('reference') else ''))
        if args.no_email:
            result['email'] = {'status': 'skipped'}
        else:
            result['email'] = send_email(subject, email_body(result, meta, jev, master, tailoring, pdf),
                                         pdf, env)
            if result['email'].get('status') == 'smtp_accepted':
                result['email']['verification'] = verify_email_arrived(env, result['email']['message_id'])
            log(f"email : {result['email'].get('status')} "
                f"({result['email'].get('verification', {}).get('status', '-')})")
        if args.no_telegram:
            result['telegram'] = {'status': 'skipped'}
        else:
            result['telegram'] = send_telegram(telegram_caption(result, meta, jev, tailoring), pdf)
            log(f"telegram : {result['telegram'].get('status')}")

    (run_dir / 'run.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'pdf': str(pdf), 'run_dir': str(run_dir), 'pages': pages,
                      'email': result.get('email', {}).get('status', 'skipped'),
                      'telegram': result.get('telegram', {}).get('status', 'skipped'),
                      'jev_score': jev.get('global_score'), 'jev_approved': jev.get('jev_approved'),
                      'emphasis': tailoring.get('emphasis'), 'notes': tailoring.get('notes'),
                      'gaps': tailoring.get('gaps'), 'warnings': check['warnings'],
                      'headline': tailoring.get('headline')},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())