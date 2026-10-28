"""Ready-made MCP prompts (menu commands in the client). Each one is only an instruction text."""

from __future__ import annotations

from fastmcp import FastMCP

# Common closing rules, appended to every prompt (see decision 130).
_REGOLE = (
    "Regole valide sempre: parti dalle parole dell'utente e NON chiedergli mai codici, date o "
    "serie (ricavali tu e converti le date dette a parole in AAAA-MM-GG). Fai poche chiamate "
    "mirate, senza cicli. Dichiara che i risultati possono essere parziali: il server vede le "
    "pubblicazioni recenti e cio' che ha gia' consultato, non l'intero archivio. Cita sempre il "
    "link ufficiale ('fonte') di ogni atto. Ricorda all'utente l'avvertenza: Fonte: Gazzetta "
    "Ufficiale della Repubblica Italiana (gazzettaufficiale.it). Testo non ufficiale e non "
    "autentico: fa fede solo il testo pubblicato nella Gazzetta Ufficiale. Non dare consigli "
    "legali: se serve interpretare una norma per un caso concreto, invita a rivolgersi a un "
    "professionista (avvocato, commercialista, patronato)."
)


def register_prompts(mcp: FastMCP) -> None:
    """Register the ready-made prompts on ``mcp``."""

    @mcp.prompt
    def riassumi_atto(atto: str) -> str:
        """Riassume un atto della Gazzetta Ufficiale in pochi punti, per chi non e' giurista."""
        return (
            f"Voglio capire questo atto della Gazzetta Ufficiale: {atto}\n\n"
            "Se l'utente ha dato un codice (es. 26A05182) usalo con leggi_atto. Se l'ha descritto "
            "a parole (es. 'la legge sul bonus X') cercalo con cerca usando le parole del titolo, "
            "poi leggi il risultato piu' adatto con leggi_atto. Se e' una legge o un decreto con "
            "estremi noti puoi anche dare il link con rimando_normattiva. Se il testo e' lungo "
            "e leggi_atto lo restituisce a pezzi, leggine solo quanto basta per un riassunto; per "
            "il testo aggiornato (vigente) usa testo_vigente.\n\n"
            "Scrivi il riassunto in 3-5 punti, in italiano semplice, senza gergo giuridico "
            "(spiega le parole difficili in poche parole): di cosa si tratta, a chi riguarda, cosa "
            "cambia in pratica, da quando vale, eventuali scadenze. Non inventare nulla che non "
            "sia nel testo.\n\n" + _REGOLE
        )

    @mcp.prompt
    def confronta_decreti(primo_atto: str, secondo_atto: str) -> str:
        """Confronta due atti (decreti, leggi) e dice cosa cambia e cosa resta uguale."""
        return (
            "Confronta questi due atti della Gazzetta Ufficiale:\n"
            f"1. {primo_atto}\n2. {secondo_atto}\n\n"
            "Trova ciascun atto partendo dalle parole dell'utente: con cerca (parole del titolo) "
            "oppure con il codice se l'utente lo ha dato, poi leggilo con leggi_atto (una sola "
            "lettura per atto). Se uno dei due non si trova, dillo e suggerisci parole diverse "
            "invece di tirare a indovinare.\n\n"
            "Rispondi in italiano semplice con due elenchi brevi: 'Cosa cambia' e 'Cosa resta "
            "uguale', poi una riga su quale dei due e' piu' recente. Confronta solo cio' che hai "
            "letto davvero; se i testi sono lunghi e hai visto solo una parte, dillo.\n\n" + _REGOLE
        )

    @mcp.prompt
    def concorsi_per_me(profilo: str, regione: str = "") -> str:
        """Elenca i concorsi pubblici aperti adatti a un profilo, con le scadenze."""
        dove = f"in {regione}" if regione else "in tutta Italia"
        return (
            f"Cerco concorsi pubblici {dove} adatti a questo profilo: {profilo}\n\n"
            "Usa cerca_concorsi con le parole del profilo (titolo di studio, mestiere, ente) e, "
            "se l'utente ha indicato un luogo, con la regione. Per la scadenza dei bandi usa "
            "scadenze_concorsi con entro_giorni=30, perche' il valore predefinito (7) mostra solo "
            "quelli in scadenza entro una settimana: cerca_concorsi da sola non la da'. Non "
            "chiedere altro prima di cercare. Per i dettagli "
            "di un bando promettente usa leggi_atto, ma solo per i pochi piu' adatti.\n\n"
            "Elenca i bandi aperti in modo ordinato: ente, posti e requisiti principali, scadenza "
            "(prima quelli che scadono prima), link ufficiale. Escludi i bandi gia' scaduti. "
            "Il server vede soprattutto i bandi degli ultimi 30 giorni: dillo, e suggerisci di "
            "controllare anche il sito dell'ente.\n\n" + _REGOLE
        )

    @mcp.prompt
    def cosa_e_uscito(periodo: str = "oggi") -> str:
        """Riassume le novita' pubblicate in Gazzetta Ufficiale in un periodo detto a parole."""
        return (
            f"Dimmi cosa e' uscito in Gazzetta Ufficiale: {periodo}\n\n"
            "Traduci il periodo in giorni tu stesso. Per periodi recenti (oggi, questa settimana, "
            "ultimi giorni) usa ultime_pubblicazioni; per un giorno preciso passato usa sommario "
            "con la data in AAAA-MM-GG. Fai una sola chiamata principale e, se serve, una seconda "
            "per un'altra serie.\n\n"
            "Scrivi una sintesi in italiano semplice: raggruppa le novita' per tema (leggi, "
            "decreti, concorsi, altro), evidenzia le 3-5 cose piu' importanti per i cittadini e "
            "per ciascuna dai il link ufficiale. Non leggere ogni atto: apri con leggi_atto solo "
            "quelli necessari per capire di cosa parlano.\n\n" + _REGOLE
        )

    @mcp.prompt
    def aggiornamenti_su(argomento: str) -> str:
        """Dice cosa c'e' di nuovo su un argomento dall'ultima volta che l'utente ha chiesto."""
        return (
            f"Cosa c'e' di nuovo in Gazzetta Ufficiale su questo argomento: {argomento}\n\n"
            "Usa novita_argomento con l'argomento cosi' come l'ha detto l'utente: mostra solo cio' "
            "che e' nuovo dall'ultima volta. Se lo strumento dice che e' la prima volta, spiegalo. "
            "Se non trova nulla, prova con cerca usando parole vicine, una sola volta. Per capire "
            "una novita' usa leggi_atto solo se serve.\n\n"
            "Rispondi in italiano semplice: prima le novita' (titolo in parole facili, data, link "
            "ufficiale), poi una riga che dica se non c'e' nulla di nuovo.\n\n" + _REGOLE
        )
