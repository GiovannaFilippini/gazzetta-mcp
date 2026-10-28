"""Deadline of a call (bando) from its text and the date of its publication in the GU.

Pure functions, no network and no cache. The rule is in decision 100: the term of the
applications is counted from the publication in the Gazzetta Ufficiale (the day of publication
is not counted); a deadline falling on a Sunday or a national holiday moves to the next working
day. Nothing is invented: when the text gives no usable formula the result says "non rilevata".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from .concorsi import _NUMBER_WORDS
from .regioni import normalize

# How the deadline was found (field "metodo").
METODO_DATA = "data_esplicita"
METODO_GIORNI = "giorni_dalla_pubblicazione"
METODO_NESSUNO = "non_rilevata"

MAX_GIORNI = 120  # longer terms are not credible for the applications: ignore them


@dataclass(frozen=True)
class Scadenza:
    data: date | None
    metodo: str
    dettaglio: str  # one Italian sentence: how the date was obtained
    giorni: int | None = None  # N of the "N days from publication" formula
    data_nominale: date | None = None  # before the shift to a working day
    motivo_spostamento: str = ""
    incerta: bool = False  # the text holds formulas that disagree: check the call


# --- Italian holidays -----------------------------------------------------------------


def pasqua(anno: int) -> date:
    """Easter Sunday (Gregorian calendar, anonymous algorithm)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mese, giorno = divmod(h + ll - 7 * m + 114, 31)
    return date(anno, mese, giorno + 1)


# Fixed national holidays (month, day). Local patron saints are not included.
_FESTE_FISSE = {
    (1, 1): "Capodanno",
    (1, 6): "Epifania",
    (4, 25): "Festa della Liberazione",
    (5, 1): "Festa del Lavoro",
    (6, 2): "Festa della Repubblica",
    (8, 15): "Ferragosto",
    (11, 1): "Ognissanti",
    (12, 8): "Immacolata Concezione",
    (12, 25): "Natale",
    (12, 26): "Santo Stefano",
}


def festivita(anno: int) -> dict[date, str]:
    """National holidays of a year (fixed ones, Easter Monday)."""
    feste = {date(anno, m, g): nome for (m, g), nome in _FESTE_FISSE.items()}
    feste[pasqua(anno) + timedelta(days=1)] = "Lunedi' dell'Angelo"
    return feste


def _giorno_non_utile(d: date, sabato_festivo: bool) -> str:
    """Why ``d`` cannot be the last day (empty if it can)."""
    nome = festivita(d.year).get(d)
    if nome:
        return nome
    if d.weekday() == 6:
        return "domenica"
    if d.weekday() == 5 and sabato_festivo:
        return "sabato"
    return ""


def primo_giorno_utile(d: date, sabato_festivo: bool = False) -> tuple[date, str]:
    """``d`` or the first later day that is not Sunday or a national holiday.

    The Saturday counts as a non-working day only when asked (the text of the call says so).
    Returns the day and a short reason ("" when it did not move).
    """
    motivo = _giorno_non_utile(d, sabato_festivo)
    if not motivo:
        return d, ""
    reasons = [f"{d.isoformat()}: {motivo}"]
    while _giorno_non_utile(d, sabato_festivo):
        d += timedelta(days=1)
        extra = _giorno_non_utile(d, sabato_festivo)
        if extra:
            reasons.append(f"{d.isoformat()}: {extra}")
    return d, "; ".join(reasons)


# --- text patterns ----------------------------------------------------------------------


def _ordinali() -> dict[str, int]:
    out = {"decimo": 10}
    for word, value in _NUMBER_WORDS.items():
        if value <= 10:
            continue
        stem = word if word.endswith(("tre", "sei")) else word[:-1]
        out[stem + "esimo"] = value
    return out


_ORDINALI = _ordinali()
_NUMERI = {w: v for w, v in _NUMBER_WORDS.items() if v >= 5}
_NUM = "|".join(sorted(map(re.escape, {*_NUMERI, *_ORDINALI}), key=len, reverse=True))
# "30 (trenta) giorni": the word in brackets repeats the figure
_TONDE = re.compile(rf"\b(\d{{1,3}}) (?:{_NUM}) (?=giorn)")
# "il trentesimo giorno", "30 giorni", "trenta giorni", "30 giorno" (ordinal written 30°)
_GIORNI = re.compile(rf"\b(\d{{1,3}}|{_NUM}) (?:gg|giorni|giorno)\b")

_NOMI_MESI = (
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre"
)
_MESI = {m: i for i, m in enumerate(_NOMI_MESI.split(), 1)}
_MESE = "|".join(_MESI)
_GIORNO_SETTIMANA = r"(?:(?:lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica) )?"
_DATA = re.compile(rf"\b{_GIORNO_SETTIMANA}(?:il )?(?:giorno )?(\d{{1,2}}) ({_MESE}) (20\d\d)\b")
_DATA_NUM = re.compile(
    r"\b(\d{1,2}) (\d{1,2}) (20\d\d)\b"
)  # 12/10/2026, 12.10.2026 once normalised
_PAROLE_TERMINE = re.compile(
    r"\b(?:scadenza|scade|scadra|scadono|termine|termini|entro|improrogabilmente|non oltre|"
    r"fino al|sino al)\b"
)
_PAROLE_DOMANDA = re.compile(r"domand|candidatur|partecipazion|istanz|presentazion|scad|termin")
_ATTO = re.compile(
    r"\b(?:decreto|deliberazione|delibera|determina|bollettino|pubblicat[oa]|gazzetta)\b"
)
# normalised text has no full stops: look at the words close to each other
_SABATO_FESTIVO = re.compile(
    r"sabato(?: \w+){0,6} (?:festiv|lavorativ)|(?:festiv|lavorativ)\w*(?: \w+){0,6} sabato"
)


# A term counted from the publication on the website of the body (or its notice board) is not
# the formula of the GU: the date of the GU would be wrong by days or weeks.
_FONTE_LOCALE = re.compile(
    r"\b(?:sito|albo|pretori\w*|internet|web|portale|istituzional\w*|online|on line)\b"
)
# appeal terms ("ricorso al TAR entro 60 giorni dalla pubblicazione") are not application terms
_RICORSO = re.compile(r"\b(?:ricors\w*|impugn\w*|giurisdizional\w*|tar|tribunale amministrativo)\b")
_PUBBLICAZIONE = re.compile(r"pubblicazion\w*")
# characters between "pubblicazione" and "Gazzetta" before the link between the two is lost
_DISTANZA_GAZZETTA = 90


def _numero(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _ORDINALI.get(token) or _NUMERI.get(token)


def _data_valida(g: int, m: int, a: int) -> date | None:
    try:
        return date(a, m, g)
    except ValueError:
        return None


def _origine_termine(testo: str, inizio: int) -> str | None:
    """Where the "publication" of a formula of days happens: "gazzetta", "locale" or None.

    Looks at the first "pubblicazione" from the figure on (else at the closest one before it)
    and at the words up to the first "Gazzetta" after it: if the website or the notice board of
    the body comes in between, the term is counted from that publication ("locale"), not from
    the GU.
    """
    pub = _PUBBLICAZIONE.search(testo, max(0, inizio - 60), inizio + 170)
    if not pub:
        prima = list(_PUBBLICAZIONE.finditer(testo, max(0, inizio - 170), inizio))
        if not prima:
            return None
        pub = prima[-1]
    dopo = testo[pub.end() : pub.end() + _DISTANZA_GAZZETTA]
    gazzetta = dopo.find("gazzetta")
    if gazzetta != -1:
        return "locale" if _FONTE_LOCALE.search(dopo[:gazzetta]) else "gazzetta"
    if _FONTE_LOCALE.search(dopo[:40]):
        return "locale"
    # "pubblicato nella Gazzetta ..., a quindici giorni dalla pubblicazione": the GU comes first
    prima_pub = testo[max(0, pub.start() - _DISTANZA_GAZZETTA) : pub.start()]
    ultima = prima_pub.rfind("gazzetta")
    if ultima != -1 and not _FONTE_LOCALE.search(prima_pub[ultima:]):
        return "gazzetta"
    return None


def _formule_giorni(norm: str, origine: str = "gazzetta") -> list[tuple[int, bool, str]]:
    """Every "N days from the publication in the GU" in the text: (N, "presente", excerpt).

    With ``origine="locale"`` it returns the formulas counted from the website of the body
    instead (used only to say why no date is given).
    """
    testo = _TONDE.sub(r"\1 ", norm)
    trovate = []
    for m in _GIORNI.finditer(testo):
        n = _numero(m.group(1))
        if n is None or not 5 <= n <= MAX_GIORNI:
            continue
        finestra = testo[max(0, m.start() - 170) : m.end() + 170]
        if _origine_termine(testo, m.start()) != origine:
            continue
        if _RICORSO.search(testo[max(0, m.start() - 120) : m.end()]):
            continue
        if not _PAROLE_DOMANDA.search(testo[max(0, m.start() - 450) : m.end() + 170]):
            continue
        # a term of "N working days" or counted from something else is not this formula
        dopo = testo[m.end() : m.end() + 25]
        if re.match(r"\s*(?:lavorativi|feriali)", dopo):
            continue
        presente = bool(re.search(r"presente (?:avviso|bando|estratto|comunicato)", finestra))
        trovate.append((n, presente, finestra.strip()))
    return trovate


def _formule_data(norm: str, pubblicazione: date) -> list[date]:
    """Explicit deadlines: after a word of "term/deadline", or the end of "da ... a ..."."""
    trovate: list[date] = []
    candidate: list[tuple[int, date]] = []
    for m in _DATA.finditer(norm):
        d = _data_valida(int(m.group(1)), _MESI[m.group(2)], int(m.group(3)))
        if d:
            candidate.append((m.start(), d))
    for m in _DATA_NUM.finditer(norm):
        d = _data_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            candidate.append((m.start(), d))
    candidate.sort()
    for pos, d in candidate:
        prima = norm[max(0, pos - 200) : pos]
        parole = list(_PAROLE_TERMINE.finditer(prima))
        if not parole or not _PAROLE_DOMANDA.search(prima):
            continue
        # between the word of "deadline" and the date there must not be an act: "con decreto
        # n. 12 del 3 ottobre 2026" is the date of the act, not the deadline
        if _ATTO.search(prima[parole[-1].end() :]):
            continue
        # the bando of a reopening may quote the old deadline: it is before the publication
        if d < pubblicazione:
            continue
        trovate.append(d)
    return trovate


def _intervallo_domande(norm: str, pubblicazione: date) -> list[date]:
    """End of "termini di presentazione delle domande: da <data> a <data>"."""
    fine = []
    pattern = re.compile(
        rf"\bdal?\b {_GIORNO_SETTIMANA}(\d{{1,2}}) ({_MESE}) (20\d\d) al? {_GIORNO_SETTIMANA}"
        rf"(\d{{1,2}}) ({_MESE}) (20\d\d)\b"
    )
    for m in pattern.finditer(norm):
        prima = norm[max(0, m.start() - 110) : m.start()]
        if not _PAROLE_DOMANDA.search(prima) or not _PAROLE_TERMINE.search(prima):
            continue
        d = _data_valida(int(m.group(4)), _MESI[m.group(5)], int(m.group(6)))
        if d and d >= pubblicazione:
            fine.append(d)
    return fine


def ricava_scadenza(testo: str, pubblicazione: date) -> Scadenza:
    """Deadline of the applications for the call ``testo`` published in the GU on ``pubblicazione``.

    Order: the formula "N days from the publication in the Gazzetta Ufficiale" (the usual one),
    then an explicit date. When nothing is found the date is None: it is never guessed.
    """
    norm = normalize(testo or "")
    if not norm:
        return Scadenza(None, METODO_NESSUNO, "Testo del bando vuoto.")

    formule = _formule_giorni(norm)
    if formule:
        # the formula about "il presente avviso" first, then the first one in the text
        formule.sort(key=lambda f: not f[1])
        giorni = formule[0][0]
        incerta = len({f[0] for f in formule}) > 1
        nominale = pubblicazione + timedelta(days=giorni)
        data, motivo = primo_giorno_utile(nominale, bool(_SABATO_FESTIVO.search(norm)))
        dettaglio = (
            f"{giorni} giorni dalla pubblicazione in Gazzetta Ufficiale del "
            f"{pubblicazione.isoformat()} (il giorno della pubblicazione non si conta)"
        )
        if motivo:
            dettaglio += f"; il {nominale.isoformat()} non e' un giorno utile ({motivo}), slitta"
        if incerta:
            dettaglio += "; nel testo compaiono termini diversi: controlla il bando"
        return Scadenza(data, METODO_GIORNI, dettaglio + ".", giorni, nominale, motivo, incerta)

    esplicite = _intervallo_domande(norm, pubblicazione) or _formule_data(norm, pubblicazione)
    if esplicite:
        data = esplicite[0]
        incerta = len(set(esplicite)) > 1
        dettaglio = f"Data scritta nel testo del bando: {data.isoformat()}"
        if incerta:
            dettaglio += "; nel testo compaiono altre date possibili: controlla il bando"
        return Scadenza(data, METODO_DATA, dettaglio + ".", incerta=incerta)

    if _formule_giorni(norm, "locale"):
        return Scadenza(
            None,
            METODO_NESSUNO,
            "Il termine sembra contare dalla pubblicazione sul sito dell'ente e non dalla "
            "Gazzetta: la scadenza non e' calcolabile da qui, controlla il bando.",
        )
    return Scadenza(
        None,
        METODO_NESSUNO,
        "Nel testo pubblicato in Gazzetta non c'e' una scadenza ricavabile (di solito rimanda al "
        "bando completo sul sito dell'ente).",
    )
