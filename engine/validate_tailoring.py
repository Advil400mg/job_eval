"""Validation du CV adapté : rien ne doit être inventé par rapport à CV_MASTER.json.

Utilisé après l'appel LLM. Toute violation bloque la production du PDF.
"""
import re
import unicodedata

STOPWORDS = set("""
a afin ai ainsi alors apres après au aucun aucune aujourd auquel aux avant avec avoir avons ayant
bien ca ça car ce ceci cela celle celles celui cependant certain certaine ces cet cette ceux chaque
chez ci comme comment dans de dedans dehors deja déjà depuis des desormais dès lors dessous dessus
deux doit doivent donc dont du duquel durant elle elles en encore enfin entre est et etaient étaient
etais étais etait était etant étant ete été etes êtes etre être eu eux fait faire fais faisons fait
font grace grâce hors ici il ils j je jusqu jusque l la laquelle le lequel les lesquels leur leurs
lui ma mais malgre malgré me meme même mes mien mienne moi mon ne ni non nos notre nous nouveau
on ont ou où oui par parce parmi pas pendant peut peuvent plus plusieurs pour pourquoi premier
pres près puis puisque qu quand que quel quelle quelles quels quelque quelques qui quoi sa sans se
selon ses si sien sienne soi soit son sont sous souvent suis sur ta tandis tant te tel telle
tellement telles tels tes toi ton tous tout toute toutes tres très trop tu un une va vers voici
voila voilà vos votre vous y etc plus moins fort forts forte fortes bon bonne nouveau nouvelle
nouvelles au dela delà aussi autre autres fois annee années annee encore
""".split())


def norm(tok):
    tok = unicodedata.normalize('NFKD', tok.lower())
    tok = ''.join(c for c in tok if not unicodedata.combining(c))
    tok = re.sub(r"[^a-z0-9/+.-]", '', tok).strip('.-')
    if len(tok) > 4 and tok.endswith('s'):
        tok = tok[:-1]
    return tok


def tokens(text):
    return [norm(t) for t in re.findall(r"[\wÀ-ÿ/+.-]+", text, flags=re.UNICODE)]


def master_corpus(master):
    """Tout le vocabulaire légitime, normalisé."""
    parts = []

    def walk(x):
        if isinstance(x, str):
            parts.append(x)
        elif isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ('rules',):
                    walk(v)
    walk(master)
    return set(t for t in tokens(' '.join(parts)) if t)


# jetons techniques : contiennent un chiffre, une majuscule interne, une barre ou un point
TECH_RE = re.compile(r"[A-Za-z]*\d|[/+]|\.[a-z]{2,}|[A-Z]{2,}")


def tech_tokens(text):
    return {norm(t) for t in re.findall(r"[\wÀ-ÿ/+.-]+", text) if TECH_RE.search(t)}


CLAIM_RE = [
    (re.compile(r"\b\d+\s*(?:ans?|ann[eé]es?|years?)\b", re.I), "revendication d'années d'expérience"),
    (re.compile(r"\b(?:senior|expert|expertise avérée|confirm[ée]|lead)\b", re.I), "positionnement sénior"),
    (re.compile(r"\b(?:CISSP|OSCP|CEH|CISM|ISO 27001 lead)\b", re.I), "certification non détenue"),
]


def validate(master, tailoring, offer_text=''):
    v, w = [], []
    corpus = master_corpus(master)

    headline = (tailoring.get('headline') or '').strip()
    if not headline:
        v.append("headline manquant")
    elif len(headline) > 95:
        v.append(f"headline trop long ({len(headline)} caractères)")
    else:
        allowed = set(norm(x) for x in master.get('headline_words', []))
        for t in tokens(headline):
            if t and t not in allowed and t not in corpus:
                v.append(f"headline : mot non autorisé « {t} »")

    profile = (tailoring.get('profile') or '').strip()
    if not profile:
        v.append("profil manquant")
    else:
        if not (150 <= len(profile) <= 900):
            v.append(f"profil hors bornes ({len(profile)} caractères, attendu 150-900)")
        plain_unknown, risky_unknown = [], []
        for raw in re.findall(r"[\wÀ-ÿ/+.-]+", profile):
            t = norm(raw)
            if not t or t in corpus or t in STOPWORDS:
                continue
            if raw[0].isupper() or TECH_RE.search(raw) or any(c.isdigit() for c in raw):
                risky_unknown.append(raw)
            else:
                plain_unknown.append(raw)
        for raw in risky_unknown:
            v.append(f"profil : terme risqué absent du master « {raw} »")
        if len(plain_unknown) > 4:
            v.append("profil : trop de mots hors vocabulaire master : " + ', '.join(sorted(set(plain_unknown))[:12]))
        elif plain_unknown:
            w.append("profil : mots hors vocabulaire master (tolérés) : " + ', '.join(sorted(set(plain_unknown))))

    exp_by_id = {e['id']: e for e in master['experiences']}
    seen = set()
    for item in tailoring.get('experiences', []):
        eid = item.get('id')
        if eid not in exp_by_id:
            v.append(f"expérience inconnue : {eid}")
            continue
        if eid in seen:
            v.append(f"expérience dupliquée : {eid}")
        seen.add(eid)
        master_bullets = exp_by_id[eid]['bullets']
        if not item.get('bullets'):
            w.append(f"{eid} : aucune puce retenue")
        for b in item.get('bullets', []):
            if not isinstance(b, str) or not b.strip():
                v.append(f"{eid} : puce vide")
                continue
            if len(b) > 240:
                v.append(f"{eid} : puce trop longue ({len(b)})")
            bt = set(tokens(b))
            bt = {t for t in bt if t and t not in STOPWORDS}
            best = 0.0
            for mb in master_bullets:
                mt = {t for t in tokens(mb) if t and t not in STOPWORDS}
                if not mt:
                    continue
                sim = len(bt & mt) / max(1, len(bt | mt))
                best = max(best, sim)
            if best < 0.45:
                v.append(f"{eid} : puce trop éloignée du master (similarité {best:.2f}) : « {b[:70]}… »")
            for t in tech_tokens(b):
                if t and t not in corpus:
                    v.append(f"{eid} : terme technique absent du master « {t} »")

    # Ordre : le rendu suit l'ordre du master (antéchronologique). Un ordre différent
    # proposé par le LLM est ignoré, mais signalé pour rendre la dérive visible.
    master_order = [e['id'] for e in master['experiences']]
    proposed_order = [i.get('id') for i in tailoring.get('experiences', []) if i.get('id') in exp_by_id]
    chrono_order = [eid for eid in master_order if eid in set(proposed_order)]
    if proposed_order and proposed_order != chrono_order:
        w.append("ordre des expériences proposé non antéchronologique, ignoré au rendu : "
                 + ', '.join(proposed_order))

    for gid in tailoring.get('skill_groups_order', []) or []:
        if gid not in {g['id'] for g in master['skill_groups']}:
            v.append(f"groupe de compétences inconnu : {gid}")
    for pid in tailoring.get('projects_order', []) or []:
        if pid not in {p['id'] for p in master['projects']}:
            v.append(f"projet inconnu : {pid}")

    haystack = ' '.join([headline, profile] + [b for it in tailoring.get('experiences', [])
                                               for b in it.get('bullets', [])])
    for rx, label in CLAIM_RE:
        for m in rx.finditer(haystack):
            if norm(m.group(0)) not in corpus:
                v.append(f"{label} : « {m.group(0)} »")

    return {"ok": not v, "violations": v, "warnings": w}