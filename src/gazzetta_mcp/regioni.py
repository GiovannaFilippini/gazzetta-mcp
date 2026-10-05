"""Italian regions and a best-effort guess of the region of a public body.

The GU gives no region field: it is estimated from the name of the issuing body (and, failing
that, from the title) using region names, provinces, main towns and a few well known
hospitals and universities. The result is an estimate, never an official datum.
Matching is on normalised text (lower case, no accents, no apostrophes) and on whole words,
so "Roma" never matches "Romagna" and "Reggio" alone is ambiguous (None).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

REGIONI: tuple[str, ...] = (
    "Abruzzo",
    "Basilicata",
    "Calabria",
    "Campania",
    "Emilia-Romagna",
    "Friuli-Venezia Giulia",
    "Lazio",
    "Liguria",
    "Lombardia",
    "Marche",
    "Molise",
    "Piemonte",
    "Puglia",
    "Sardegna",
    "Sicilia",
    "Toscana",
    "Trentino-Alto Adige",
    "Umbria",
    "Valle d'Aosta",
    "Veneto",
)


def normalize(text: str) -> str:
    """Lower case, no accents, every non-alphanumeric run (apostrophes, quotes) -> one space."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return text.strip()


# Region names and aliases (normalised keys). Used both for user input and for text matching.
_REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "Abruzzo": ("abruzzo", "abruzzi"),
    "Basilicata": ("basilicata", "lucania"),
    "Calabria": ("calabria",),
    "Campania": ("campania",),
    "Emilia-Romagna": ("emilia romagna", "emilia", "romagna"),
    "Friuli-Venezia Giulia": ("friuli venezia giulia", "friuli", "venezia giulia", "fvg"),
    "Lazio": ("lazio",),
    "Liguria": ("liguria",),
    "Lombardia": ("lombardia",),
    "Marche": ("marche",),
    "Molise": ("molise",),
    "Piemonte": ("piemonte",),
    "Puglia": ("puglia", "apulia"),
    "Sardegna": ("sardegna",),
    "Sicilia": ("sicilia", "siciliana"),
    "Toscana": ("toscana",),
    "Trentino-Alto Adige": (
        "trentino alto adige",
        "trentino",
        "alto adige",
        "sudtirol",
        "sued tirol",
        "sud tirol",
        "trentino sudtirol",
    ),
    "Umbria": ("umbria",),
    "Valle d'Aosta": (
        "valle d aosta",
        "valle daosta",
        "vallee d aoste",
        "val d aosta",
    ),
    "Veneto": ("veneto",),
}

# Provinces, regional capitals, main towns, towns found often in GU bodies (normalised).
_PLACES: dict[str, tuple[str, ...]] = {
    "Abruzzo": (
        "l aquila",
        "teramo",
        "pescara",
        "chieti",
        "lanciano",
        "vasto",
        "avezzano",
        "sulmona",
        "giulianova",
        "atri",
        "ortona",
        "montesilvano",
    ),
    "Basilicata": ("potenza", "matera", "policoro", "melfi", "lagonegro", "venosa"),
    "Calabria": (
        "catanzaro",
        "cosenza",
        "crotone",
        "reggio calabria",
        "vibo valentia",
        "lamezia terme",
        "rossano",
        "corigliano",
        "castrovillari",
        "locri",
    ),
    "Campania": (
        "napoli",
        "caserta",
        "avellino",
        "benevento",
        "salerno",
        "pozzuoli",
        "frattamaggiore",
        "giugliano",
        "torre del greco",
        "nola",
        "pomigliano",
        "castellammare di stabia",
        "ariano irpino",
        "sant angelo dei lombardi",
        "eboli",
        "vallo della lucania",
    ),
    "Emilia-Romagna": (
        "bologna",
        "ferrara",
        "forli",
        "cesena",
        "modena",
        "parma",
        "piacenza",
        "ravenna",
        "reggio emilia",
        "reggio nell emilia",
        "rimini",
        "imola",
        "carpi",
        "faenza",
        "riccione",
        "guastalla",
    ),
    "Friuli-Venezia Giulia": (
        "trieste",
        "udine",
        "gorizia",
        "pordenone",
        "aviano",
        "tarcento",
        "monfalcone",
        "cividale del friuli",
        "sacile",
        "maniago",
    ),
    "Lazio": (
        "roma",
        "latina",
        "frosinone",
        "rieti",
        "viterbo",
        "tivoli",
        "civitavecchia",
        "anzio",
        "pomezia",
        "cassino",
        "fiumicino",
        "guidonia",
        "formia",
        "tor vergata",
    ),
    "Liguria": (
        "genova",
        "la spezia",
        "savona",
        "imperia",
        "sanremo",
        "chiavari",
        "sestri levante",
    ),
    "Lombardia": (
        "milano",
        "monza",
        "brianza",
        "varese",
        "como",
        "lecco",
        "sondrio",
        "bergamo",
        "brescia",
        "cremona",
        "mantova",
        "pavia",
        "lodi",
        "crema",
        "seriate",
        "treviglio",
        "garbagnate milanese",
        "rho",
        "legnano",
        "busto arsizio",
        "gallarate",
        "sesto san giovanni",
        "cinisello balsamo",
        "vimercate",
        "desio",
        "lomellina",
        "valcamonica",
        "valtellina",
        "insubria",
        "gavardo",
        "desenzano del garda",
        "bollate",
        "melegnano",
        "abbiategrasso",
        "magenta",
        "cernusco sul naviglio",
        "cantu",
        "saronno",
    ),
    "Marche": (
        "ancona",
        "ascoli piceno",
        "fermo",
        "macerata",
        "pesaro",
        "urbino",
        "camerino",
        "jesi",
        "fabriano",
        "senigallia",
        "civitanova marche",
        "fano",
    ),
    "Molise": ("campobasso", "isernia", "termoli", "larino", "venafro"),
    "Piemonte": (
        "torino",
        "alessandria",
        "asti",
        "biella",
        "cuneo",
        "novara",
        "verbania",
        "vercelli",
        "chivasso",
        "ivrea",
        "ciriè",
        "chieri",
        "moncalieri",
        "rivoli",
        "pinerolo",
        "casale monferrato",
        "verbano cusio ossola",
        "borgomanero",
        "domodossola",
        "novi ligure",
        "tortona",
        "saluzzo",
        "mondovi",
    ),
    "Puglia": (
        "bari",
        "foggia",
        "lecce",
        "taranto",
        "brindisi",
        "barletta",
        "andria",
        "trani",
        "altamura",
        "molfetta",
        "monopoli",
        "san giovanni rotondo",
        "cerignola",
        "manfredonia",
        "gallipoli",
        "casarano",
        "salento",
    ),
    "Sardegna": (
        "cagliari",
        "sassari",
        "nuoro",
        "oristano",
        "olbia",
        "gallura",
        "selargius",
        "carbonia",
        "iglesias",
        "lanusei",
        "tempio pausania",
        "alghero",
        "quartu sant elena",
        "ogliastra",
        "sulcis",
    ),
    "Sicilia": (
        "palermo",
        "catania",
        "messina",
        "siracusa",
        "ragusa",
        "trapani",
        "agrigento",
        "caltanissetta",
        "enna",
        "marsala",
        "gela",
        "acireale",
        "paterno",
        "bagheria",
        "modica",
        "mazara del vallo",
        "sciacca",
        "milazzo",
        "licata",
    ),
    "Toscana": (
        "firenze",
        "arezzo",
        "grosseto",
        "livorno",
        "lucca",
        "massa",
        "carrara",
        "pisa",
        "pistoia",
        "prato",
        "siena",
        "empoli",
        "viareggio",
        "piombino",
        "montecatini terme",
        "pontedera",
        "versilia",
        "valdarno",
        "mugello",
        "lunigiana",
    ),
    "Trentino-Alto Adige": (
        "trento",
        "bolzano",
        "bozen",
        "merano",
        "bressanone",
        "brunico",
        "rovereto",
        "riva del garda",
        "pergine valsugana",
        "cles",
    ),
    "Umbria": (
        "perugia",
        "terni",
        "foligno",
        "spoleto",
        "orvieto",
        "assisi",
        "citta di castello",
        "gubbio",
        "narni",
    ),
    "Valle d'Aosta": ("aosta", "aoste"),
    "Veneto": (
        "venezia",
        "padova",
        "verona",
        "vicenza",
        "treviso",
        "belluno",
        "rovigo",
        "mestre",
        "chioggia",
        "bassano del grappa",
        "mirano",
        "feltre",
        "pieve di soligo",
        "schiavonia",
        "legnago",
        "adria",
        "san donà di piave",
        "portogruaro",
        "ca foscari",
        "marca trevigiana",
        "polesine",
        "altovicentino",
        "castelfranco veneto",
    ),
}

# Healthcare / university / research entities that identify a region without naming it.
# Ambiguous acronyms (ASL, AUSL, ASP, ATS, AST, ARNAS, AOU, "Policlinico") are deliberately
# absent: they exist in several regions and only the town after them tells which one.
_ENTITIES: dict[str, tuple[str, ...]] = {
    "Lombardia": (
        "asst",
        "azienda socio sanitaria territoriale",
        "policlinico san matteo",
        "policlinico di milano",
        "niguarda",
        "san raffaele",
        "bocconi",
        "bicocca",
        "politecnico di milano",
        "istituto neurologico besta",
        "humanitas",
        "ospedale maggiore policlinico",
    ),
    "Toscana": (
        "estar",
        "careggi",
        "meyer",
        "normale superiore",
        "scuola superiore sant anna",
        "ausl toscana",
        "azienda usl toscana",
        "toscana centro",
        "toscana nord ovest",
        "toscana sud est",
    ),
    "Piemonte": (
        "molinette",
        "citta della salute e della scienza",
        "mauriziano",
        "politecnico di torino",
        "azienda zero piemonte",
    ),
    "Sardegna": (
        "azienda regionale della salute",
        "ares sardegna",
        "areus",
        "brotzu",
        "ats sardegna",
    ),
    "Lazio": (
        "policlinico umberto i",
        "policlinico gemelli",
        "gemelli",
        "sapienza",
        "luiss",
        "bambino gesu",
        "san camillo forlanini",
        "spallanzani",
        "tuscia",
        "roma tre",
        "foro italico",
        "tor vergata",
    ),
    "Campania": (
        "cardarelli",
        "monaldi",
        "federico ii",
        "pascale",
        "vanvitelli",
        "policlinico federico ii",
        "asl napoli",
        "ospedali dei colli",
        "azienda ospedaliera dei colli",
    ),
    "Emilia-Romagna": (
        "sant orsola",
        "rizzoli",
        "policlinico di modena",
        "asl romagna",
        "ausl romagna",
    ),
    "Liguria": ("gaslini", "ospedale policlinico san martino"),
    "Friuli-Venezia Giulia": (
        "asufc",
        "burlo garofolo",
        "sissa",
        "azienda sanitaria universitaria friuli",
        "centro di riferimento oncologico di aviano",
    ),
    "Sicilia": (
        "arnas civico",
        "arnas garibaldi",
        "villa sofia",
        "cannizzaro",
        "policlinico paolo giaccone",
        "policlinico gaetano martino",
        "regione siciliana",
    ),
    "Puglia": ("policlinico di bari", "politecnico di bari", "casa sollievo della sofferenza"),
    "Veneto": ("azienda zero veneto", "iuav", "ulss", "aulss"),
    "Calabria": (
        "magna graecia",
        "mediterranea di reggio calabria",
        "grande ospedale metropolitano",
    ),
    "Marche": ("politecnica delle marche", "ospedali riuniti di ancona", "inrca"),
    "Trentino-Alto Adige": (
        "azienda provinciale per i servizi sanitari",
        "apss",
        "azienda sanitaria dell alto adige",
        "sabes",
        "libera universita di bolzano",
    ),
    "Valle d'Aosta": ("azienda usl della valle d aosta", "usl valle d aosta"),
}

_ASL_TO = re.compile(r"\b(?:asl\s+)?to\s?[1-5]\b")
_PREPOSITION = r"(?:di|a|ad|presso|da|del|della|dello|dei|degli|delle|nel|nella|in)"


def _compile(
    keys: dict[str, tuple[str, ...]], *, need_preposition: bool
) -> list[tuple[re.Pattern, str]]:
    out: list[tuple[re.Pattern, str]] = []
    for regione, words in keys.items():
        for word in words:
            key = re.escape(normalize(word)).replace(r"\ ", r"\s+")
            prefix = rf"\b{_PREPOSITION}\s+" if need_preposition else r"\b"
            out.append((re.compile(rf"{prefix}{key}\b"), regione))
    return out


_NAME_PATTERNS = _compile(_REGION_ALIASES, need_preposition=False)
_ENTITY_PATTERNS = _compile(_ENTITIES, need_preposition=False)
_PLACE_PATTERNS = _compile(_PLACES, need_preposition=False)
_PLACE_PATTERNS_STRICT = _compile(_PLACES, need_preposition=True)


def _matches(text: str, patterns: list[tuple[re.Pattern, str]]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for pattern, regione in patterns:
        for m in pattern.finditer(text):
            found.append((m.end(), regione))
    return found


def _pick(found: list[tuple[int, str]]) -> str | None:
    """Most frequent region; on a tie the one mentioned last (the town usually comes last)."""
    if not found:
        return None
    counts = Counter(r for _, r in found)
    best = max(counts.values())
    candidates = {r for r, n in counts.items() if n == best}
    return max((pos, r) for pos, r in found if r in candidates)[1]


def regione_da_testo(text: str, *, strict: bool = False) -> str | None:
    """Region of a body name or title, or None if it cannot be told.

    ``strict`` is for free prose (titles): a town only counts when introduced by a
    preposition ("di Lecce"), so that "letteratura latina" is not read as the town of Latina.
    Region names and explicit entities always count.
    """
    norm = normalize(text)
    if not norm:
        return None
    if _ASL_TO.search(norm):
        return "Piemonte"
    found = _matches(norm, _NAME_PATTERNS) + _matches(norm, _ENTITY_PATTERNS)
    if found:
        return _pick(found)
    return _pick(_matches(norm, _PLACE_PATTERNS_STRICT if strict else _PLACE_PATTERNS))


def regione_ente(ente: str, titolo: str = "") -> str | None:
    """Estimate the region of an act: the issuing body first, then the title."""
    return regione_da_testo(ente) or regione_da_testo(titolo, strict=True)


def normalizza_regione(user_input: str | None) -> str | None:
    """Canonical region name for tolerant user input ('lombardia', 'Emilia Romagna', 'friuli').

    Returns None for empty input; raises ValueError (Italian message) if not recognised.
    """
    if user_input is None or not user_input.strip():
        return None
    norm = normalize(user_input)
    norm = re.sub(r"^(?:regione|regione autonoma|provincia autonoma di|provincia di)\s+", "", norm)
    norm = re.sub(r"^(?:della|di|del|dell)\s+", "", norm)
    for regione, aliases in _REGION_ALIASES.items():
        if norm == normalize(regione) or norm in aliases:
            return regione
    for regione, towns in _PLACES.items():  # "Bolzano", "Aosta" are provinces/regions too
        if regione in ("Trentino-Alto Adige", "Valle d'Aosta") and norm in towns:
            return regione
    elenco = ", ".join(REGIONI)
    raise ValueError(f"Regione '{user_input.strip()}' non riconosciuta. Regioni ammesse: {elenco}.")
