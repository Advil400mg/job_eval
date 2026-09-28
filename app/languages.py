"""Conservative ISO 639-1 language requirements and declared CEFR levels.

Only explicit requirements are detected; an unrecognised language is left for
Jev and human review instead of being assumed compatible.
"""

from __future__ import annotations

import gettext
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pycountry

_MANDATORY = re.compile(
    r"\b(?:required|mandatory|must|essential|fluent|proficient|"
    r"obligatoire|exig[ée]e?|indispensable|couran(?:t|te)|"
    r"erforderlich|vorausgesetzt|flie(?:ss|ß)end|beherrschen|"
    r"necessario|obligatorio|imprescindible)\b", re.I)
_OPTIONAL = re.compile(r"\b(?:optional|not required|not mandatory|facultatif|"
                       r"pas obligatoire|non exig[ée]|nicht erforderlich|opcional)\b", re.I)
_LEVEL = re.compile(r"\b(?:[ABC][12]|fluent|couran(?:t|te)|bilingual|bilingue|"
                    r"native|advanced|avanc[ée]|professional|professionnel|"
                    r"flie(?:ss|ß)end|muttersprachlich)\b", re.I)
_CEFR = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


@lru_cache(maxsize=1)
def _aliases() -> tuple[dict[str, str | None], re.Pattern]:
    langs = [lang for lang in pycountry.languages if hasattr(lang, "alpha_2")]
    aliases: dict[str, str | None] = {}
    def remember(name: str, code: str) -> None:
        folded = _fold(name.strip())
        if len(folded) < 4 or not folded[0].isalpha():
            return
        if folded in aliases and aliases[folded] != code:
            aliases[folded] = None
        else:
            aliases[folded] = code
    for lang in langs:
        remember(lang.name, lang.alpha_2)
        if hasattr(lang, "common_name"):
            remember(lang.common_name, lang.alpha_2)
    for locale in Path(pycountry.LOCALES_DIR).iterdir():
        if not locale.is_dir():
            continue
        try:
            translated = gettext.translation("iso639-3", pycountry.LOCALES_DIR,
                                             languages=[locale.name])
        except FileNotFoundError:
            continue
        for lang in langs:
            remember(translated.gettext(lang.name), lang.alpha_2)
    names = sorted(aliases, key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b", re.I)
    return aliases, pattern


def _mentions(sentence: str) -> list[tuple[str, int, int]]:
    mapping, pattern = _aliases()
    folded = _fold(sentence)
    return [(code, match.start(), match.end()) for match in pattern.finditer(folded)
            if (code := mapping.get(match.group(0))) is not None]


def required_languages(text: str) -> list[tuple[str, str, int | None]]:
    """(ISO code, verbatim sentence, CEFR requirement when explicit)."""
    required = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        excerpt = sentence.strip()
        if not excerpt or not _MANDATORY.search(excerpt) or _OPTIONAL.search(excerpt):
            continue
        mentions = _mentions(excerpt)
        for index, (code, start, end) in enumerate(mentions):
            stop = mentions[index + 1][1] if index + 1 < len(mentions) else len(excerpt)
            segment = _fold(excerpt)[end:min(stop, end + 35)]
            level = next((int(_CEFR[m.group(0).upper()]) for m in
                          re.finditer(r"\b[ABC][12]\b", segment, re.I)), None)
            if all(existing[0] != code for existing in required):
                required.append((code, excerpt, level))
    return required


def candidate_levels(line: str) -> dict[str, int | bool]:
    """Map only levels immediately attached to their own language name."""
    result: dict[str, int | bool] = {}
    for phrase in re.split(r"[,;\n]+", line):
        mentions = _mentions(phrase)
        folded = _fold(phrase)
        for index, (code, start, end) in enumerate(mentions):
            stop = mentions[index + 1][1] if index + 1 < len(mentions) else len(phrase)
            before = folded[max(0, start - 15):start]
            after = folded[end:min(end + 28, stop)]
            matched = _LEVEL.search(after) or re.search(
                r"\b(?:[ABC][12]|fluent|native)\s+(?:en\s+|in\s+)?$", before, re.I)
            if matched:
                level = _CEFR.get(matched.group(0).upper(), True)
                result[code] = level
    return result
