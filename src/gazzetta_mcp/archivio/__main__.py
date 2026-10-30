"""Command line of the archive jobs: ``python -m gazzetta_mcp.archivio <command>``.

Commands: ``aggiorna`` (daily: new issues of the GU and updates of Normattiva), ``recupera``
(backward recovery, resumable), ``controlla`` (parser check), ``stato`` (what is in the archive).
Every command is safe to repeat: acts already archived are never downloaded again.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import date

from ..config import Settings
from ..models import Serie
from ..parsing import GuParser
from ..sources.gu import GuClient, GuError
from .acquisizione_gu import aggiorna_recenti, recupera_indietro
from .acquisizione_normattiva import NormattivaOpenData, aggiorna_normattiva, recupera_normattiva
from .controllo_parser import Campione, controlla_parser
from .store import ArchiveStore

SERIE_GIORNALIERE = (Serie.SG, Serie.S4)  # series with a 30 days list: see acquisizione_gu


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m gazzetta_mcp.archivio", description=__doc__)
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("aggiorna", help="daily update (GU and Normattiva)")
    r = sub.add_parser("recupera", help="backward recovery, a limited batch per run")
    r.add_argument("--max-numeri", type=int, default=20, help="GU issues per series (default 20)")
    r.add_argument("--max-atti", type=int, default=200, help="Normattiva acts (default 200)")
    r.add_argument(
        "--serie", default="SG", choices=[s.value for s in Serie], help="GU series (default SG)"
    )
    sub.add_parser("controlla", help="check that the parser still reads the GU pages")
    sub.add_parser("stato", help="show what the archive holds")
    return p


async def _gu(
    store: ArchiveStore, settings: Settings, serie_lista: Sequence[Serie], max_numeri: int
) -> dict[str, object]:
    """Update and recover the GU. A problem on the site stops every GU series (it is one site)
    but not Normattiva, which is another source."""
    out: dict[str, object] = {}
    client, parser = GuClient(settings), GuParser()
    try:
        for serie in serie_lista:
            try:
                if serie in SERIE_GIORNALIERE:
                    out[f"gu.{serie.value}.numeri_in_coda"] = await aggiorna_recenti(
                        client, parser, store, serie
                    )
                esito = await recupera_indietro(client, parser, store, serie, max_numeri=max_numeri)
            except GuError as exc:
                return _fermo(store, out, f"gu.{serie.value}", str(exc))
            out[f"gu.{serie.value}.atti_nuovi"] = esito.atti_nuovi
            if esito.fermato:
                return _fermo(store, out, f"gu.{serie.value}", esito.motivo or "")
    finally:
        await client.aclose()
    return out


def _fermo(store: ArchiveStore, out: dict[str, object], chi: str, motivo: str) -> dict[str, object]:
    store.set_stato(f"{chi}.fermato", motivo)
    out[f"{chi}.fermato"] = motivo
    return out


async def _normattiva(store: ArchiveStore, settings: Settings, **kwargs: int) -> dict[str, object]:
    out: dict[str, object] = {}
    normattiva = NormattivaOpenData(settings)
    try:
        if kwargs:
            out["normattiva.atti_nuovi"] = await recupera_normattiva(normattiva, store, **kwargs)
        else:
            out["normattiva.atti_nuovi"] = await aggiorna_normattiva(normattiva, store)
    except GuError as exc:
        return _fermo(store, out, "normattiva", str(exc))
    finally:
        await normattiva.aclose()
    return out


async def _aggiorna(store: ArchiveStore, settings: Settings) -> dict[str, object]:
    out = await _gu(store, settings, SERIE_GIORNALIERE, 10)
    out.update(await _normattiva(store, settings))
    return out


async def _recupera(
    store: ArchiveStore, settings: Settings, serie: Serie, max_numeri: int, max_atti: int
) -> dict[str, object]:
    out = await _gu(store, settings, [serie], max_numeri)
    out.update(await _normattiva(store, settings, max_atti=max_atti))
    return out


async def _controlla(store: ArchiveStore, settings: Settings) -> bool:
    """Sample the newest archived issue of each series that has one. Also fails when most of
    the recent issues were stored as empty: that is what a changed HTML looks like."""
    campioni: list[Campione] = []
    sospetto = False
    for serie in Serie:
        recenti = store.read(
            "SELECT stato FROM numeri WHERE serie = ? AND stato IN ('fatto', 'vuoto')"
            " ORDER BY data DESC LIMIT 30",
            (serie.value,),
        )
        if len(recenti) >= 10 and sum(r["stato"] == "vuoto" for r in recenti) > len(recenti) / 2:
            print(f"Allarme: la serie {serie.value} ha troppi numeri vuoti tra gli ultimi.")
            sospetto = True
    for serie in Serie:
        rows = store.read(
            "SELECT data, numero FROM numeri WHERE serie = ? AND stato = 'fatto'"
            " AND numero IS NOT NULL ORDER BY data DESC LIMIT 1",
            (serie.value,),
        )
        if rows:
            campioni.append(Campione(serie, date.fromisoformat(rows[0]["data"]), rows[0]["numero"]))
    if not campioni:
        print("Niente da controllare: nessun numero della Gazzetta e' ancora stato archiviato.")
        return True
    client = GuClient(settings)
    try:
        rapporto = await controlla_parser(client, GuParser(), store, campioni=campioni)
    finally:
        await client.aclose()
    print(rapporto.testo)
    return rapporto.ok and not sospetto


def _stato(store: ArchiveStore) -> dict[str, object]:
    return {
        "atti": store.count_atti(),
        "numeri": store.conteggio_numeri(),
        "ultimo_errore_normattiva": store.get_stato("normattiva.ultimo_errore") or "",
        "cursore_normattiva": store.get_stato("normattiva.cursore") or "",
        "controllo_parser": store.get_stato("controllo_parser") or "",
        "note_dei_lavori": {  # stops and cursors of the jobs, e.g. gu.SG.ultimo_stop
            r["chiave"]: r["valore"]
            for r in store.read(
                "SELECT chiave, valore FROM stato WHERE chiave LIKE 'gu.%' ORDER BY chiave"
            )
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.from_env()
    if args.comando in ("stato", "controlla") and not settings.archivio_path.exists():
        print(f"Nessun archivio in {settings.archivio_path}: niente da mostrare o controllare.")
        return 0 if args.comando == "stato" else 1
    with ArchiveStore(settings.archivio_path) as store:
        if args.comando == "stato":
            print(json.dumps(_stato(store), ensure_ascii=False, indent=2))
            return 0
        if args.comando == "controlla":
            return 0 if asyncio.run(_controlla(store, settings)) else 1
        if args.comando == "aggiorna":
            risultato = asyncio.run(_aggiorna(store, settings))
        else:
            risultato = asyncio.run(
                _recupera(store, settings, Serie(args.serie), args.max_numeri, args.max_atti)
            )
        print(json.dumps(risultato, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
