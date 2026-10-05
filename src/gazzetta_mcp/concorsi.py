"""Helpers for the 4th special series (competitions): title classification, number of posts,
keyword matching. Pure functions, no network and no cache."""

from __future__ import annotations

import re

from .regioni import normalize

# Kinds returned by classify(). BANDI are the "new calls" shown by default.
TIPO_BANDO = "bando"
TIPO_RIAPERTURA = "riapertura_termini"
TIPO_PROROGA = "proroga"
TIPO_RETTIFICA = "rettifica_annullamento"
TIPO_DIARIO = "diario_prove"
TIPO_ESITO = "esito_graduatoria"
TIPO_COMMISSIONE = "commissione"
TIPO_ALTRO = "altro"
BANDI = frozenset({TIPO_BANDO, TIPO_RIAPERTURA})

_LEAD = r"^(?:(?:avviso|comunicato|comunicazione)\s+(?:di|del|della|relativ[oa]\s+a)\s+)?"

_RULES: tuple[tuple[str, re.Pattern], ...] = (
    # The non-call kinds are recognised from the opening words of the title only: a call
    # may well mention "graduatoria" or "commissione" further on (reserved posts, etc.).
    (
        TIPO_RETTIFICA,
        re.compile(
            _LEAD + r"(?:rettifica|errata corrige|annullamento|revoca|sospensione|ritiro|"
            r"modifica del bando|modifiche al bando|modifica del termine)\b"
        ),
    ),
    (TIPO_RIAPERTURA, re.compile(_LEAD + r"(?:riapertura|nuova apertura)\b")),
    (TIPO_PROROGA, re.compile(_LEAD + r"(?:proroga|differimento|slittamento)\b")),
    (
        TIPO_DIARIO,
        re.compile(
            _LEAD + r"(?:diario|calendario (?:delle|della|dei)|convocazione|sede e (?:data|diario))"
        ),
    ),
    (
        TIPO_ESITO,
        re.compile(
            _LEAD + r"(?:graduatoria|graduatorie|esito|esiti|approvazione (?:atti|degli atti|della "
            r"graduatoria)|elenco (?:degli )?idonei|nomina (?:dei )?vincitor[ei]|scorrimento|"
            r"pubblicazione (?:della )?graduatoria)\b"
        ),
    ),
    (
        TIPO_COMMISSIONE,
        re.compile(
            r"^(?:modifica|composizione|nomina|sostituzione|accettazione|integrazione|"
            r"costituzione|variazione|dimissioni)\b.*\b(?:commissione|commissioni|componente|componenti)\b"
        ),
    ),
    (
        TIPO_BANDO,
        re.compile(
            r"\b(?:concorso|concorsi|selezione|selezioni|procedura|procedure|avviso|bando|"
            r"conferimento|incarico|incarichi|mobilita|stabilizzazione|borsa|borse|ammissione|"
            r"avviamento|assunzione|reclutamento|copertura|chiamata|assegno|assegni|"
            r"dottorato|master|tirocinio|corso)\b"
        ),
    ),
)


def classify(titolo: str) -> str:
    """Kind of a sommario entry, guessed from its title (Italian wording of the GU)."""
    norm = normalize(titolo)
    for tipo, pattern in _RULES:
        if pattern.search(norm):
            return tipo
    return TIPO_ALTRO


# --- number of posts -------------------------------------------------------------------

_UNITS = {
    "un": 1,
    "uno": 1,
    "una": 1,
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10,
    "undici": 11,
    "dodici": 12,
    "tredici": 13,
    "quattordici": 14,
    "quindici": 15,
    "sedici": 16,
    "diciassette": 17,
    "diciotto": 18,
    "diciannove": 19,
}
_TENS = {
    "venti": 20,
    "trenta": 30,
    "quaranta": 40,
    "cinquanta": 50,
    "sessanta": 60,
    "settanta": 70,
    "ottanta": 80,
    "novanta": 90,
}


def _number_words() -> dict[str, int]:
    words = dict(_UNITS)
    words.update(_TENS)
    words["cento"] = 100
    for tens, tv in _TENS.items():
        for unit, uv in _UNITS.items():
            if unit in ("un", "una") or uv > 9:
                continue
            stem = tens[:-1] if unit in ("uno", "otto") else tens  # ventuno, ventotto
            words[stem + unit] = tv + uv
    return words


_NUMBER_WORDS = _number_words()
_ALT = "|".join(sorted(map(re.escape, _NUMBER_WORDS), key=len, reverse=True))
# "a venti posti", "un posto", "n. 5 posti", "5 posti", "di sette posti"
_POSTI = re.compile(rf"\b(\d{{1,4}}|{_ALT})\s+post[oi]\b")
_POSTI_N = re.compile(r"\bposti?\s*(?:n|nr|numero)\s*(\d{1,4})\b")


def estrai_posti(titolo: str) -> int | None:
    """Number of posts declared in a title, when written in a plain way; otherwise None."""
    norm = normalize(titolo)
    m = _POSTI.search(norm)
    if m:
        token = m.group(1)
        return int(token) if token.isdigit() else _NUMBER_WORDS[token]
    m = _POSTI_N.search(norm)
    return int(m.group(1)) if m else None


# --- keyword matching ------------------------------------------------------------------


def _stem(word: str) -> str:
    """Crude Italian stem: drop the final vowel so that singular and plural match."""
    return word[:-1] if len(word) >= 5 and word[-1] in "aeio" else word


def keyword_matcher(parole_chiave: str):
    """Return a predicate on text: every keyword must appear (plural/singular tolerant)."""
    terms = [_stem(w) for w in normalize(parole_chiave).split() if w]

    def match(text: str) -> bool:
        words = normalize(text).split()
        return all(any(w.startswith(t) if len(t) >= 4 else w == t for w in words) for t in terms)

    return match
