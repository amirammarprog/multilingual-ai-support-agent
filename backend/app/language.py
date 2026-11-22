"""Language detection for Arabic (incl. Tunisian Arabic, in Arabic script or Latin "Arabizi"),
French and English.

Script decides Arabic vs Latin. For Latin text a Tunisian Arabizi lexicon is checked first, then the
lingua detector separates French from English. Very short or ambiguous messages ("ok", "merci 👍")
keep the language of the conversation.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

LanguageCode = Literal["en", "fr", "ar"]
SUPPORTED: tuple[LanguageCode, ...] = ("en", "fr", "ar")

_ARABIC_CHAR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_CHAR = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
_WORD = re.compile(r"[\w']+", re.UNICODE)

# Words that are typical of Tunisian Arabic (Derja) rather than Modern Standard Arabic.
TUNISIAN_ARABIC_MARKERS = {
    "شنوة",
    "شنوا",
    "شنية",
    "شني",
    "برشا",
    "برشة",
    "توا",
    "تو",
    "باهي",
    "بهي",
    "فما",
    "فمة",
    "فماش",
    "نحب",
    "نحبو",
    "علاش",
    "قداش",
    "قداه",
    "كيفاش",
    "وقتاش",
    "وقتاه",
    "وين",
    "مازال",
    "ماهوش",
    "موش",
    "مش",
    "بش",
    "باش",
    "نجم",
    "نجموا",
    "يعيشك",
    "عيشك",
    "ياسر",
    "حاجة",
    "متاعي",
    "متاع",
    "متاعك",
    "كوموند",
    "الكوموند",
    "ليفريزون",
    "نخلص",
    "خلصت",
    "وصلني",
    "ماوصلنيش",
    "بالحق",
    "زادة",
    "زاده",
}

# Tunisian Arabic written in Latin letters, often with digits 3, 7, 9, 5 for Arabic sounds.
ARABIZI_MARKERS = {
    "chnowa",
    "chnoua",
    "chnouwa",
    "chniya",
    "chnia",
    "chbik",
    "famma",
    "fama",
    "famech",
    "famma'",
    "nheb",
    "n7eb",
    "n7ebb",
    "nhebb",
    "barcha",
    "barsha",
    "yesser",
    "yasser",
    "3lech",
    "3lach",
    "alech",
    "kifech",
    "kifach",
    "wa9tech",
    "wa9teh",
    "waktech",
    "9adech",
    "9addech",
    "kadech",
    "9adeh",
    "mta3",
    "mte3",
    "mta3i",
    "mte3i",
    "mta3ek",
    "ya3tik",
    "y3aychek",
    "3aychek",
    "sa7a",
    "saha",
    "behi",
    "bahi",
    "tawa",
    "taw",
    "3andi",
    "3andek",
    "3andkom",
    "win",
    "wiin",
    "mazel",
    "mazelt",
    "mouch",
    "mich",
    "bech",
    "besh",
    "najjem",
    "najem",
    "nejjem",
    "nestanna",
    "wsel",
    "wsoltni",
    "jetni",
    "jani",
    "5alast",
    "khallast",
    "5ales",
    "mrigel",
    "brabi",
    "3ayechek",
    "salem",
    "aslema",
    "ahla",
    "chkoun",
    "lyoum",
    "ghodwa",
    "commanda",
    "el",
    "fil",
}
# Markers that are also common French/English words count only with other evidence.
_WEAK_ARABIZI = {"win", "el", "fil", "taw", "saha", "bahi", "salem", "fama"}
_DIGIT_IN_WORD = re.compile(r"\b[a-z]*[a-z][3579][a-z]+\b|\b[3579][a-z]{2,}\b")

_FR_HINTS = {
    "le",
    "la",
    "les",
    "des",
    "est",
    "et",
    "je",
    "vous",
    "mon",
    "ma",
    "mes",
    "pour",
    "avec",
    "une",
    "un",
    "bonjour",
    "merci",
    "commande",
    "livraison",
    "remboursement",
    "retour",
    "combien",
    "quand",
    "où",
    "pourquoi",
    "comment",
    "est-ce",
    "qu'est-ce",
    "j'ai",
    "c'est",
    "garantie",
    "prix",
    "disponible",
    "salut",
}
_EN_HINTS = {
    "the",
    "is",
    "and",
    "my",
    "you",
    "your",
    "for",
    "with",
    "what",
    "when",
    "where",
    "how",
    "why",
    "order",
    "delivery",
    "refund",
    "return",
    "price",
    "available",
    "hello",
    "hi",
    "thanks",
    "thank",
    "please",
    "can",
    "do",
    "does",
    "i'm",
    "it's",
    "warranty",
    "shipping",
    "stock",
}


@dataclass(frozen=True)
class DetectedLanguage:
    code: LanguageCode
    dialect: str | None  # "tn" for Tunisian Arabic
    script: Literal["arabic", "latin", "none"]
    confidence: float

    @property
    def tag(self) -> str:
        return f"{self.code}-{self.dialect}" if self.dialect else self.code


@lru_cache(maxsize=1)
def _detector():  # pragma: no cover - trivial factory
    from lingua import Language, LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.FRENCH).build()


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # Arabic-Indic digits to ASCII so "٣" and "3" behave the same.
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def detect_language(text: str, prior: str | None = None) -> DetectedLanguage:
    """Detect the language of a user message. ``prior`` is the conversation language, if any."""
    text = _normalize(text or "")
    arabic = len(_ARABIC_CHAR.findall(text))
    latin = len(_LATIN_CHAR.findall(text))
    prior_code: LanguageCode | None = prior.split("-")[0] if prior and prior.split("-")[0] in SUPPORTED else None  # type: ignore[assignment]

    if arabic == 0 and latin == 0:
        code: LanguageCode = prior_code or "en"
        return DetectedLanguage(code, "tn" if prior and prior.endswith("-tn") else None, "none", 0.2)

    if arabic >= latin:
        words = set(_WORD.findall(text))
        tunisian = len(words & TUNISIAN_ARABIC_MARKERS)
        return DetectedLanguage("ar", "tn" if tunisian else None, "arabic", min(1.0, 0.6 + arabic / 40))

    lowered = text.lower()
    words = _WORD.findall(lowered)
    word_set = set(words)
    strong = len((word_set & ARABIZI_MARKERS) - _WEAK_ARABIZI)
    weak = len(word_set & _WEAK_ARABIZI)
    digit_words = len(_DIGIT_IN_WORD.findall(lowered))
    arabizi_score = strong + digit_words + 0.5 * weak
    fr_hits = len(word_set & _FR_HINTS)
    en_hits = len(word_set & _EN_HINTS)

    if arabizi_score >= 2 or (arabizi_score >= 1 and arabizi_score >= 0.5 * max(fr_hits, en_hits)):
        return DetectedLanguage("ar", "tn", "latin", min(1.0, 0.5 + 0.15 * arabizi_score))

    if len(words) <= 2 and prior_code and fr_hits == en_hits:
        return DetectedLanguage(prior_code, None, "latin", 0.4)

    confidences = {c.language.name: c.value for c in _detector().compute_language_confidence_values(text)}
    fr, en = confidences.get("FRENCH", 0.0), confidences.get("ENGLISH", 0.0)
    # Accented letters are a strong French signal that lingua sometimes underweights on short text.
    if re.search(r"[éèêàùçôîœ]", lowered):
        fr += 0.2
    fr += 0.05 * fr_hits
    en += 0.05 * en_hits
    if abs(fr - en) < 0.1 and prior_code in ("fr", "en"):
        return DetectedLanguage(prior_code, None, "latin", 0.5)
    return DetectedLanguage("fr" if fr > en else "en", None, "latin", round(max(fr, en) / (fr + en or 1), 3))


def ts_config_for(code: str) -> str:
    """PostgreSQL text search configuration for a language code."""
    return {"en": "english", "fr": "french", "ar": "arabic"}.get(code.split("-")[0], "simple")


LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "ar": "Modern Standard Arabic",
    "ar-tn": "Tunisian Arabic (Derja) written in Arabic script, simple and friendly",
}
