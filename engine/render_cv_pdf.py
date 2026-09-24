"""Rendu PDF d'un CV adapté à partir de CV_MASTER.json + sortie de tailoring.

Aucun contenu n'est inventé ici : le renderer n'affiche que ce que le master
contient, réordonné/sélectionné par la sortie de tailoring.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
                                Table, TableStyle, KeepTogether, ListFlowable, ListItem)
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _find_fontdir():
    """Polices Liberation : dossier embarqué, puis emplacements système usuels."""
    candidates = []
    if os.environ.get('CV_FONTDIR'):
        candidates.append(Path(os.environ['CV_FONTDIR']))
    candidates += [
        HERE / 'fonts',
        Path('/usr/share/fonts/truetype/liberation'),
        Path('/usr/share/fonts/liberation'),
        Path('/usr/local/share/fonts/truetype/liberation'),
        Path('/Library/Fonts'),
        Path('/System/Library/Fonts/Supplemental'),
    ]
    for candidate in candidates:
        if (candidate / 'LiberationSans-Regular.ttf').is_file():
            return candidate
    raise SystemExit(
        "ERROR: polices Liberation Sans introuvables. Installer le paquet "
        "fonts-liberation, ou pointer CV_FONTDIR vers un dossier contenant "
        "LiberationSans-Regular.ttf / -Bold / -Italic."
    )


FONTDIR = str(_find_fontdir()) + os.sep
pdfmetrics.registerFont(TTFont('LSans', FONTDIR + 'LiberationSans-Regular.ttf'))
pdfmetrics.registerFont(TTFont('LSans-Bold', FONTDIR + 'LiberationSans-Bold.ttf'))
pdfmetrics.registerFont(TTFont('LSans-Italic', FONTDIR + 'LiberationSans-Italic.ttf'))
pdfmetrics.registerFontFamily('LSans', normal='LSans', bold='LSans-Bold', italic='LSans-Italic')

ACCENT = colors.HexColor('#8C4A22')
GREY = colors.HexColor('#B9B9B9')


def _styles(k):
    """k = facteur d'échelle pour tenir sur une page."""
    s = {}
    s['name'] = ParagraphStyle('name', fontName='LSans-Bold', fontSize=21 * k[0], leading=24 * k[0], alignment=1)
    s['sub'] = ParagraphStyle('sub', fontName='LSans', fontSize=11.5 * k[0], leading=14 * k[0], alignment=1,
                              textColor=colors.HexColor('#444444'), spaceBefore=2)
    s['contact'] = ParagraphStyle('contact', fontName='LSans', fontSize=8.9 * k[1], leading=11.5 * k[1],
                                  alignment=1, textColor=colors.HexColor('#333333'), spaceBefore=3)
    s['h'] = ParagraphStyle('h', fontName='LSans-Bold', fontSize=10.6 * k[1], leading=13 * k[1],
                            textColor=ACCENT, spaceBefore=4.5 * k[1], spaceAfter=1)
    s['body'] = ParagraphStyle('body', fontName='LSans', fontSize=8.8 * k[1], leading=10.9 * k[1],
                               alignment=4, spaceAfter=3 * k[1])
    s['bullet'] = ParagraphStyle('bullet', fontName='LSans', fontSize=8.8 * k[1], leading=10.9 * k[1],
                                 alignment=0, spaceAfter=1.0 * k[1])
    s['jobtitle'] = ParagraphStyle('jobtitle', fontName='LSans-Bold', fontSize=9.6 * k[1], leading=12 * k[1],
                                   spaceAfter=2)
    s['date'] = ParagraphStyle('date', fontName='LSans-Bold', fontSize=8.7 * k[1], leading=11 * k[1],
                               textColor=colors.HexColor('#333333'))
    s['place'] = ParagraphStyle('place', fontName='LSans', fontSize=8.7 * k[1], leading=11 * k[1],
                                textColor=colors.HexColor('#333333'))
    s['skill'] = ParagraphStyle('skill', fontName='LSans', fontSize=8.8 * k[1], leading=10.9 * k[1],
                                alignment=4, spaceAfter=1.2 * k[1])
    return s


def _esc(t):
    return (str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'))


def build_story(master, tailoring, k, include_eligibility):
    S = _styles(k)
    idn = master['identity']
    story = [Paragraph(_esc(idn['name']), S['name']),
             Paragraph(_esc(tailoring.get('headline') or idn['headline_default']), S['sub']),
             Paragraph(' &nbsp;|&nbsp; '.join(_esc(x) for x in
                                              [idn['email'], idn['phone'], idn['linkedin'], idn['mobility']]),
                       S['contact']),
             Spacer(1, 6),
             HRFlowable(width='100%', thickness=0.9, color=ACCENT, spaceBefore=1, spaceAfter=1)]

    def section(title):
        story.append(Paragraph(_esc(title), S['h']))
        story.append(HRFlowable(width='100%', thickness=0.5, color=GREY, spaceBefore=0, spaceAfter=4))

    def job(entry):
        right = [Paragraph(_esc(entry['title']), S['jobtitle'])]
        if entry.get('bullets'):
            right.append(ListFlowable([ListItem(Paragraph(_esc(b), S['bullet']), leftIndent=10)
                                       for b in entry['bullets']],
                                      bulletType='bullet', bulletFontName='LSans', bulletFontSize=7.5,
                                      bulletOffsetY=-0.5, leftIndent=11, start='•',
                                      spaceBefore=0, spaceAfter=0))
        if entry.get('dates'):
            left = [Paragraph(_esc(entry['dates']), S['date']), Paragraph(_esc(entry['place']), S['place'])]
        else:
            left = [Paragraph(_esc(entry['place']), S['place'])]
        t = Table([[left, right]], colWidths=[3.5 * cm, 14.1 * cm])
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 0),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 0),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5)]))
        story.append(KeepTogether(t))

    if tailoring.get('profile'):
        section('PROFIL')
        story.append(Paragraph(_esc(tailoring['profile']), S['body']))

    exp_by_id = {e['id']: e for e in master['experiences']}
    # L'ordre du master fait foi : antéchronologique (le plus récent d'abord).
    # Le LLM ne choisit que la sélection des expériences, jamais leur ordre.
    selected = {x['id'] for x in tailoring.get('experiences', []) if x['id'] in exp_by_id}
    order = [e['id'] for e in master['experiences'] if e['id'] in selected] or list(exp_by_id)
    bullets_by_id = {x['id']: x.get('bullets', []) for x in tailoring.get('experiences', [])}
    if order:
        section('EXPÉRIENCES')
        for eid in order:
            e = dict(exp_by_id[eid])
            e['bullets'] = bullets_by_id.get(eid, e['bullets'])
            job(e)

    section('FORMATION')
    for e in master['education']:
        job(e)

    groups = {g['id']: g for g in master['skill_groups']}
    gorder = [g for g in tailoring.get('skill_groups_order', []) if g in groups] or list(groups)
    if gorder:
        section('COMPÉTENCES')
        for gid in gorder:
            g = groups[gid]
            story.append(Paragraph(f"<b>{_esc(g['label'])} :</b> {_esc(g['text'])}", S['skill']))

    proj = {p['id']: p for p in master['projects']}
    porder = [p for p in tailoring.get('projects_order', []) if p in proj] or list(proj)
    if porder:
        section('PROJETS')
        for pid in porder:
            p = proj[pid]
            story.append(Paragraph(f"<b>{_esc(p['title'])} :</b> {_esc(p['text'])}", S['skill']))

    section('LANGUES')
    langs = _esc(idn['languages_line'])
    if include_eligibility and master.get('eligibility_defense_only'):
        langs += ' &nbsp;—&nbsp; ' + _esc(' — '.join(master['eligibility_defense_only']))
    story.append(Paragraph(langs, S['skill']))
    return story


def render(master, tailoring, path, include_eligibility=False, subtitle=None):
    """Écrit le PDF ; réduit les corps de texte si nécessaire pour tenir sur une page."""
    scale = 0.0
    for step in range(6):
        k = (1.0, 1.0 - 0.04 * step)
        doc = SimpleDocTemplate(str(path), pagesize=A4,
                                rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                                topMargin=1.0 * cm, bottomMargin=1.0 * cm,
                                title=subtitle or f"CV {master['identity']['name'].title()}",
                                author=master['identity']['name'].title())
        story = build_story(master, tailoring, k, include_eligibility)
        doc.build(story)
        import pymupdf
        d = pymupdf.open(str(path))
        pages = d.page_count
        d.close()
        if pages <= 1:
            return pages, k[1]
    return pages, k[1]
