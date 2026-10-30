"""Ingestion of the GU into the archive. Fake client over the real fixtures, no network."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from gazzetta_mcp.archivio import ArchiveStore, NumeroDaFare
from gazzetta_mcp.archivio.acquisizione_gu import (
    EsitoRecupero,
    acquisisci_numero,
    aggiorna_recenti,
    attesa_backoff,
    recupera_indietro,
)
from gazzetta_mcp.models import RawPage, Serie
from gazzetta_mcp.parsing import GuParser
from gazzetta_mcp.sources.gu import GuHttpError, GuNotFoundError, UnsupportedSerieError

FIX = Path(__file__).parent.parent / "fixtures" / "real"
DAY = date(2026, 10, 3)
ISSUE = 230  # sample issue of the SG: 17 acts
N_ACTS = 17


def page(content: bytes, url: str = "https://example.test/") -> RawPage:
    return RawPage(url, content, "text/html", datetime.now(timezone.utc))


def stub_issue(data: date, numero: int) -> bytes:
    """What the GU serves for a real issue without acts: the permalink and nothing else."""
    link = f"dataPubblicazioneGazzetta={data.isoformat()}&numeroGazzetta={numero}"
    return f"<html><body>{link}</body></html>".encode()


class FakeClient:
    """SourceClient serving the fixtures. Every act gets the sample scheda and text."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail: dict[str, list[Exception]] = {}  # method name -> errors to raise, in order
        self.empty_text = False
        self.issues: dict[tuple[Serie, date, int], bytes] = {}  # extra issues on offer

    def _maybe_fail(self, name: str) -> None:
        errors = self.fail.get(name)
        if errors:
            raise errors.pop(0)

    async def get_feed(self, serie: Serie) -> RawPage:
        self.calls.append(("feed", serie))
        self._maybe_fail("feed")
        return page((FIX / f"rss_{serie.value}.xml").read_bytes())

    async def get_elenco_30giorni(self, serie: Serie) -> RawPage:
        self.calls.append(("elenco", serie))
        self._maybe_fail("elenco")
        if serie is Serie.SG:
            return page((FIX / "elenco_30giorni_serie_generale.html").read_bytes())
        raise UnsupportedSerieError(f"no index for {serie.value}")

    async def get_sommario(self, data: date, serie: Serie, numero: int) -> RawPage:
        self.calls.append(("sommario", (data, numero)))
        self._maybe_fail("sommario")
        if (data, numero) == (DAY, ISSUE):
            return page((FIX / "sommario_sg_2026-10-03_230.html").read_bytes())
        if (serie, data, numero) in self.issues:
            return page(self.issues[(serie, data, numero)])
        raise GuNotFoundError("no such issue")

    async def get_atto_scheda(self, codice: str, data: date, serie: Serie) -> RawPage:
        self.calls.append(("scheda", codice))
        self._maybe_fail("scheda")
        return page((FIX / "atto_scheda_26A05182_sg.html").read_bytes())

    async def get_atto_testo(
        self, codice: str, data: date, serie: Serie, tipo: str | None
    ) -> RawPage:
        self.calls.append(("testo", codice))
        self._maybe_fail("testo")
        if self.empty_text:
            return page(b"<html></html>")
        return page((FIX / "atto_testo_26A05182_sg.html").read_bytes())

    def url_sommario(self, data: date, serie: Serie, numero: int) -> str:
        return "x"

    def url_atto(self, codice: str, data: date, serie: Serie) -> str:
        return "x"

    def url_pdf(self, data: date, serie: Serie, numero: int) -> str:
        return "x"

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)


@pytest.fixture
def store():
    with ArchiveStore(":memory:") as s:
        yield s


@pytest.fixture
def client():
    return FakeClient()


def voce(numero: int | None = ISSUE, serie: Serie = Serie.SG, giorno: date = DAY):
    return NumeroDaFare(serie, giorno, numero, 0)


def stato(store: ArchiveStore, serie: Serie = Serie.SG, giorno: date = DAY):
    row = store.read(
        "SELECT * FROM numeri WHERE serie = ? AND data = ?", (serie.value, str(giorno))
    )
    return row[0]


# --- acquisisci_numero ---------------------------------------------------------------


async def test_acquisisci_numero_archives_every_act(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    nuovi = await acquisisci_numero(client, GuParser(), store, voce())
    assert nuovi == N_ACTS
    assert store.count_atti() == N_ACTS
    assert stato(store)["stato"] == "fatto"
    atto = store.get_atto("26A05182")
    assert atto is not None and atto.testo and atto.numero_gu == ISSUE
    # one request for the summary, then scheda + text per act (the client adds the menu)
    assert client.count("sommario") == 1
    assert client.count("scheda") == client.count("testo") == N_ACTS


async def test_acquisisci_numero_never_downloads_an_archived_act_again(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    await acquisisci_numero(client, GuParser(), store, voce())
    client.calls.clear()
    assert await acquisisci_numero(client, GuParser(), store, voce()) == 0
    assert [n for n, _ in client.calls] == ["sommario"]
    assert stato(store)["stato"] == "fatto"


async def test_acquisisci_numero_resumes_after_an_interruption(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    # the 5th text request fails
    original = client.get_atto_testo
    state = {"n": 0}

    async def flaky(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 5:
            raise GuHttpError("Unexpected HTTP status 503 for x")
        return await original(*args, **kwargs)

    client.get_atto_testo = flaky
    with pytest.raises(GuHttpError):
        await acquisisci_numero(client, GuParser(), store, voce())
    assert store.count_atti() == 4  # saved so far, kept
    row = stato(store)
    # a network problem says nothing about the issue: back in the queue, attempt not counted
    assert (row["stato"], row["tentativi"]) == ("da_fare", 0)
    assert "503" in row["ultimo_errore"]

    client.calls.clear()
    client.get_atto_testo = original
    assert await acquisisci_numero(client, GuParser(), store, voce()) == N_ACTS - 4
    assert client.count("scheda") == N_ACTS - 4
    assert stato(store)["stato"] == "fatto"


async def test_acquisisci_numero_marks_an_issue_without_acts_as_vuoto(client, store):
    client.issues[(Serie.SG, date(2026, 10, 4), 231)] = stub_issue(date(2026, 10, 4), 231)
    store.aggiungi_numeri([(Serie.SG, date(2026, 10, 4), 231)])
    v = voce(231, giorno=date(2026, 10, 4))
    assert await acquisisci_numero(client, GuParser(), store, v) == 0
    assert stato(store, giorno=date(2026, 10, 4))["stato"] == "vuoto"


async def test_acquisisci_numero_wrong_number_is_an_error_not_a_hole(client, store):
    # the GU answers 200 for any number; a page without the permalink is a stub
    client.issues[(Serie.SG, DAY, 999)] = b"<html><body>nothing here</body></html>"
    store.aggiungi_numeri([(Serie.SG, DAY, 999)])
    assert await acquisisci_numero(client, GuParser(), store, voce(999)) == 0
    row = stato(store)
    assert (row["stato"], row["tentativi"]) == ("errore", 1)
    assert "stub" in row["ultimo_errore"]
    assert store.count_atti() == 0


async def test_acquisisci_numero_404_on_the_summary_is_an_error(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, 5)])
    assert await acquisisci_numero(client, GuParser(), store, voce(5)) == 0
    row = stato(store)
    assert row["stato"] == "errore" and "GuNotFoundError" in row["ultimo_errore"]


async def test_acquisisci_numero_empty_text_is_not_archived(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    client.empty_text = True
    assert await acquisisci_numero(client, GuParser(), store, voce()) == 0
    assert store.count_atti() == 0  # an empty copy would hide the real one for good
    row = stato(store)
    assert row["stato"] == "errore" and f"{N_ACTS} acts not archived" in row["ultimo_errore"]

    client.empty_text = False  # the next run gets them
    assert await acquisisci_numero(client, GuParser(), store, voce()) == N_ACTS
    assert stato(store)["stato"] == "fatto"


async def test_acquisisci_numero_one_bad_act_does_not_stop_the_others(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, ISSUE)])
    client.fail["scheda"] = [GuNotFoundError("gone")]
    assert await acquisisci_numero(client, GuParser(), store, voce()) == N_ACTS - 1
    row = stato(store)
    assert row["stato"] == "errore" and "1 acts not archived" in row["ultimo_errore"]


async def test_acquisisci_numero_without_number_resolves_it_from_the_feed(client, store):
    store.aggiungi_numeri([(Serie.SG, DAY, None)])
    assert await acquisisci_numero(client, GuParser(), store, voce(None)) == N_ACTS
    assert stato(store)["numero"] == ISSUE  # filled in for next time
    assert client.count("feed") == 1


async def test_acquisisci_numero_unresolvable_number_is_an_error(client, store):
    giorno = date(2026, 9, 1)  # nothing on offer: guesses all fail
    store.aggiungi_numeri([(Serie.SG, giorno, None)])
    assert await acquisisci_numero(client, GuParser(), store, voce(None, giorno=giorno)) == 0
    row = stato(store, giorno=giorno)
    assert row["stato"] == "errore" and "NumeroNotFoundError" in row["ultimo_errore"]


async def test_series_without_act_support_keep_only_the_summary(client, store):
    giorno = DAY
    html = (FIX / "sommario_sg_2026-10-03_230.html").read_bytes()
    client.issues[(Serie.S5, giorno, ISSUE)] = html
    store.aggiungi_numeri([(Serie.S5, giorno, ISSUE)])
    nuovi = await acquisisci_numero(client, GuParser(), store, voce(serie=Serie.S5))
    assert nuovi == N_ACTS
    assert client.count("scheda") == client.count("testo") == 0
    atto = store.get_atto("26A05182")
    assert atto is not None
    assert atto.serie is Serie.S5 and atto.testo == "" and atto.titolo and atto.emettitore


# --- aggiorna_recenti ------------------------------------------------------------------


async def test_aggiorna_recenti_queues_the_last_30_days_once(client, store):
    first = await aggiorna_recenti(client, GuParser(), store, Serie.SG)
    assert first == 24
    assert await aggiorna_recenti(client, GuParser(), store, Serie.SG) == 0
    todo = store.prossimi_numeri(Serie.SG, 100)
    assert (todo[0].data, todo[0].numero) == (DAY, ISSUE)  # newest first


async def test_aggiorna_recenti_does_not_requeue_done_issues(client, store):
    await aggiorna_recenti(client, GuParser(), store, Serie.SG)
    store.segna_numero(Serie.SG, DAY, "fatto")
    assert await aggiorna_recenti(client, GuParser(), store, Serie.SG) == 0
    assert all(v.data != DAY for v in store.prossimi_numeri(Serie.SG, 100))


async def test_aggiorna_recenti_falls_back_to_the_feed(client, store):
    assert await aggiorna_recenti(client, GuParser(), store, Serie.S5) == 1
    (v,) = store.prossimi_numeri(Serie.S5, 10)
    assert (v.data, v.numero) == (date(2026, 10, 2), 112)


async def test_aggiorna_recenti_raises_network_errors(client, store):
    client.fail["elenco"] = [GuHttpError("Unexpected HTTP status 429")]
    with pytest.raises(GuHttpError):
        await aggiorna_recenti(client, GuParser(), store, Serie.SG)
    assert store.conteggio_numeri() == {}


# --- recupera_indietro ------------------------------------------------------------------


def queue_empty_issues(client: FakeClient, store: ArchiveStore, days: list[int]) -> None:
    for d in days:
        giorno, numero = date(2026, 9, d), 100 + d
        client.issues[(Serie.SG, giorno, numero)] = stub_issue(giorno, numero)
        store.aggiungi_numeri([(Serie.SG, giorno, numero)])


async def test_recupera_indietro_goes_newest_first_up_to_max_numeri(client, store):
    queue_empty_issues(client, store, [1, 2, 3, 4])
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    esito = await recupera_indietro(client, GuParser(), store, Serie.SG, max_numeri=3, sleep=sleep)
    assert esito == EsitoRecupero(3, 0, False, None, 0.0)
    assert [c[1][0].day for c in client.calls if c[0] == "sommario"] == [4, 3, 2]
    assert store.conteggio_numeri(Serie.SG) == {"vuoto": 3, "da_fare": 1}
    assert waits == []


async def test_recupera_indietro_backs_off_exponentially_then_stops(client, store):
    queue_empty_issues(client, store, [1, 2, 3])
    client.fail["sommario"] = [GuHttpError("Unexpected HTTP status 429")] * 10
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    esito = await recupera_indietro(
        client, GuParser(), store, Serie.SG, max_numeri=3, sleep=sleep, backoff_base=10
    )
    assert waits == [10, 20, 40]
    assert esito.fermato
    assert esito.numeri_elaborati == 0 and esito.attesa_totale == 70
    assert "429" in (esito.motivo or "")
    assert client.count("sommario") == 4  # 1 try + 3 retries, only the newest issue is touched
    assert store.conteggio_numeri(Serie.SG) == {"da_fare": 3}  # nothing lost, nothing burned
    assert store.get_stato("gu.SG.ultimo_stop") is not None


async def test_recupera_indietro_recovers_after_a_transient_error(client, store):
    queue_empty_issues(client, store, [1, 2])
    client.fail["sommario"] = [GuHttpError("Unexpected HTTP status 503")]
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    esito = await recupera_indietro(client, GuParser(), store, Serie.SG, max_numeri=5, sleep=sleep)
    assert (esito.numeri_elaborati, esito.fermato) == (2, False)
    assert len(waits) == 1
    assert store.conteggio_numeri(Serie.SG) == {"vuoto": 2}


async def test_recupera_indietro_is_resumable(client, store):
    queue_empty_issues(client, store, [1, 2, 3])
    client.fail["sommario"] = [GuHttpError("boom")] * 4

    async def sleep(s: float) -> None:
        return None

    stopped = await recupera_indietro(
        client, GuParser(), store, Serie.SG, max_numeri=3, sleep=sleep
    )
    assert stopped.fermato
    again = await recupera_indietro(client, GuParser(), store, Serie.SG, max_numeri=3, sleep=sleep)
    assert (again.numeri_elaborati, again.fermato) == (3, False)
    assert store.conteggio_numeri(Serie.SG) == {"vuoto": 3}


async def test_recupera_indietro_keeps_going_past_a_bad_issue(client, store):
    queue_empty_issues(client, store, [1])
    store.aggiungi_numeri([(Serie.SG, date(2026, 9, 2), 7)])  # 404: not on offer

    async def sleep(s: float) -> None:
        return None

    esito = await recupera_indietro(client, GuParser(), store, Serie.SG, max_numeri=5, sleep=sleep)
    assert (esito.numeri_elaborati, esito.fermato) == (2, False)
    assert store.conteggio_numeri(Serie.SG) == {"vuoto": 1, "errore": 1}


# --- back-off ----------------------------------------------------------------------------


def test_attesa_backoff_doubles_and_is_capped():
    assert [attesa_backoff(n, 30, 200) for n in range(5)] == [30, 60, 120, 200, 200]
    assert attesa_backoff(-1, 30, 200) == 30
