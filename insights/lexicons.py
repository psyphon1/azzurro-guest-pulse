"""Keyword lexicons for reviews written in French, Spanish, German, Italian and Portuguese.

Same topics and the same rules as the English lists in ``insights.topics``: a keyword in the "liked" box is
praise, in the "disliked" box a complaint, and a negated keyword flips (a negated problem word is good news).
Words are written without accents, because the classifier strips accents before matching ("salete" matches
"saleté"). German "ß" is kept. A lexicon is only used for reviews in its own language, so "sale" (French for
dirty) never fires on English text.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Lexicon:
    keywords: dict[str, tuple[str, ...]]           # topic id -> keywords
    problems: frozenset[str]                       # keywords that name a problem
    negators: frozenset[str]
    fillers: frozenset[str] = frozenset()          # words allowed between a negator and a problem word
    contrast: tuple[str, ...] = ()                 # words that end a clause ("but")
    all_clear: tuple[str, ...] = ()                # phrases meaning "no problems at all"
    rewrites: tuple[tuple[str, str], ...] = ()     # idioms replaced before matching
    loanwords: dict[str, tuple[str, ...]] = field(default_factory=dict)


# English words guests use in every language.
_LOAN = {
    "check_in": ("check-in", "check in", "checkin", "check-out", "checkout"),
    "facilities": ("wifi", "wi-fi", "wlan", "parking"),
    "staff": ("staff",),
}

FR = Lexicon(
    keywords={
        "safety": ("cafard", "cafards", "blatte", "blattes", "punaise de lit", "punaises de lit", "punaises",
                   "moisissure", "moisissures", "moisi", "rat", "rats", "souris", "incendie", "risque electrique",
                   "fils electriques", "fils denudes", "dangereux", "dangereuse", "voleur", "voleurs",
                   "cambriolage", "on m a vole", "insecurite"),
        "cleanliness": ("propre", "propres", "proprete", "sale", "sales", "salete", "crasseux", "crasseuse",
                        "odeur", "odeurs", "puant", "puante", "poussiere", "poussiereux", "cheveux", "poils",
                        "tache", "taches", "hygiene", "insalubre", "degoutant", "degoutante", "menage",
                        "nettoyage", "ordures", "poubelle", "poubelles", "insectes", "moucherons", "cafards",
                        "moisissure"),
        "check_in": ("arrivee", "cle", "cles", "clef", "code d acces", "enregistrement", "depart", "tablette",
                     "borne"),
        "staff": ("personnel", "equipe", "accueil", "receptionniste", "reception", "aimable", "aimables",
                  "sympathique", "sympathiques", "sympa", "serviable", "serviables", "gentil", "gentille",
                  "gentils", "impoli", "impolie", "desagreable", "desagreables", "accueillant", "accueillante",
                  "gerant", "irrespectueux"),
        "noise": ("bruit", "bruits", "bruyant", "bruyante", "bruyants", "calme", "silencieux", "fete",
                  "musique", "insonorisation"),
        "facilities": ("cuisine", "climatisation", "clim", "chauffage", "ascenseur", "serviette", "serviettes",
                       "petit dejeuner", "petit-dejeuner", "laverie", "frigo", "refrigerateur", "micro-ondes",
                       "bouilloire", "eau chaude", "piscine", "casier", "casiers"),
        "location": ("emplacement", "situe", "situee", "bien situe", "localisation", "quartier", "proche",
                     "pres de", "gare", "metro", "bus", "centre", "centre-ville", "plage", "transports",
                     "a pied", "minutes a pied"),
        "room_condition": ("lit", "lits", "matelas", "oreiller", "oreillers", "draps", "linge", "meubles",
                           "moquette", "rideaux", "confortable", "confortables", "inconfortable", "casse",
                           "cassee", "vetuste", "abime", "abimee", "delabre", "delabree", "fuite", "humide",
                           "humidite", "exigu", "exigue"),
        "value": ("prix", "rapport qualite prix", "qualite prix", "cher", "chere", "chers", "trop cher",
                  "abordable", "bon marche", "hors de prix", "arnaque"),
    },
    problems=frozenset({
        "cafard", "cafards", "blatte", "blattes", "punaise de lit", "punaises de lit", "punaises", "moisissure",
        "moisissures", "moisi", "rat", "rats", "souris", "incendie", "risque electrique", "fils electriques",
        "fils denudes", "dangereux", "dangereuse", "voleur", "voleurs", "cambriolage", "on m a vole", "insecurite",
        "sale", "sales", "salete", "crasseux", "crasseuse", "odeur", "odeurs", "puant", "puante", "poussiere",
        "poussiereux", "cheveux", "poils", "tache", "taches", "insalubre", "degoutant", "degoutante", "ordures",
        "insectes", "moucherons", "impoli", "impolie", "desagreable", "desagreables", "irrespectueux", "bruit",
        "bruits", "bruyant", "bruyante", "bruyants", "fete", "musique", "inconfortable", "casse", "cassee",
        "vetuste", "abime", "abimee", "delabre", "delabree", "fuite", "humide", "humidite", "exigu", "exigue",
        "cher", "chere", "chers", "trop cher", "hors de prix", "arnaque",
    }),
    negators=frozenset({"ne", "n", "pas", "aucun", "aucune", "sans", "jamais", "rien", "ni", "non", "guere"}),
    fillers=frozenset({"tres", "vraiment", "du", "tout", "trop", "si", "le", "la", "les", "un", "une", "est",
                       "etait", "sont", "etaient", "etre", "de", "d", "particulierement", "assez", "plus"}),
    contrast=("mais", "cependant", "pourtant", "toutefois", "sauf"),
    all_clear=("aucun probleme", "aucun souci", "rien a signaler", "rien a redire", "rien a dire",
               "pas de probleme", "pas de souci"),
    rewrites=(("a deux pas", "proche"), ("a quelques pas", "proche"), ("a 2 pas", "proche")),
    loanwords=_LOAN,
)

ES = Lexicon(
    keywords={
        "safety": ("cucaracha", "cucarachas", "chinche", "chinches", "moho", "rata", "ratas", "raton", "ratones",
                   "incendio", "cables expuestos", "cables sueltos", "robado", "robada", "robaron",
                   "ladron", "ladrones", "inseguro", "insegura", "peligroso", "peligrosa"),
        "cleanliness": ("limpio", "limpia", "limpios", "limpias", "limpieza", "sucio", "sucia", "sucios", "sucias",
                        "suciedad", "mal olor", "olor", "olores", "apesta", "polvo", "pelos", "manchas", "mancha",
                        "higiene", "asqueroso", "asquerosa", "basura", "insectos", "cucarachas", "moho"),
        "check_in": ("llegada", "llave", "llaves", "codigo", "registro", "salida", "tableta"),
        "staff": ("personal", "recepcion", "recepcionista", "amable", "amables", "simpatico", "simpatica",
                  "atento", "atentos", "atenta", "servicial", "serviciales", "maleducado", "maleducada", "grosero",
                  "grosera", "antipatico", "antipatica", "desagradable", "encargado", "dueno", "anfitrion", "trato"),
        "noise": ("ruido", "ruidos", "ruidoso", "ruidosa", "tranquilo", "tranquila", "silencioso", "fiesta",
                  "musica", "paredes finas"),
        "facilities": ("cocina", "aire acondicionado", "calefaccion", "ascensor", "toallas", "toalla", "desayuno",
                       "aparcamiento", "estacionamiento", "lavanderia", "nevera", "microondas", "agua caliente",
                       "piscina", "taquilla", "taquillas", "casillero", "casilleros"),
        "location": ("ubicacion", "ubicado", "ubicada", "situado", "situada", "localizacion", "barrio", "cerca",
                     "estacion", "metro", "autobus", "centro", "playa", "transporte", "a pie", "andando",
                     "caminando"),
        "room_condition": ("cama", "camas", "colchon", "almohada", "almohadas", "sabanas", "muebles", "cortinas",
                           "comodo", "comoda", "comodas", "incomodo", "incomoda", "roto", "rota", "rotos", "rotas",
                           "viejo", "vieja", "gastado", "desgastado", "deteriorado", "gotera", "humedad", "humedo",
                           "humeda"),
        "value": ("precio", "precios", "barato", "economico", "caro", "caros", "carisimo", "calidad precio",
                  "relacion calidad precio", "vale la pena", "estafa"),
    },
    problems=frozenset({
        "cucaracha", "cucarachas", "chinche", "chinches", "moho", "rata", "ratas", "raton", "ratones", "incendio",
        "cables expuestos", "cables sueltos", "robado", "robada", "robaron", "ladron", "ladrones",
        "inseguro", "insegura", "peligroso", "peligrosa", "sucio", "sucia", "sucios", "sucias", "suciedad",
        "mal olor", "olor", "olores", "apesta", "polvo", "pelos", "manchas", "mancha", "asqueroso", "asquerosa",
        "basura", "insectos", "maleducado", "maleducada", "grosero", "grosera", "antipatico", "antipatica",
        "desagradable", "ruido", "ruidos", "ruidoso", "ruidosa", "fiesta", "musica", "paredes finas", "incomodo",
        "incomoda", "roto", "rota", "rotos", "rotas", "viejo", "vieja", "gastado", "desgastado", "deteriorado",
        "gotera", "humedad", "humedo", "humeda", "caro", "caros", "carisimo", "estafa",
    }),
    negators=frozenset({"no", "sin", "nunca", "nada", "ningun", "ninguna", "ninguno", "ni", "jamas", "tampoco"}),
    fillers=frozenset({"muy", "tan", "demasiado", "el", "la", "los", "las", "un", "una", "era", "es", "estaba",
                       "estaban", "fue", "esta", "estan", "hay", "habia", "nada", "mucho", "mucha", "tanto"}),
    contrast=("pero", "sin embargo", "aunque", "excepto", "salvo"),
    all_clear=("ningun problema", "sin problemas", "nada que reclamar", "nada que objetar", "nada que decir"),
    loanwords=_LOAN,
)

DE = Lexicon(
    keywords={
        "safety": ("kakerlake", "kakerlaken", "schabe", "schaben", "bettwanze", "bettwanzen", "wanzen", "schimmel",
                   "ratte", "ratten", "mause", "brandgefahr", "feuer", "offene kabel", "lose kabel", "diebstahl",
                   "gestohlen", "geklaut", "unsicher", "gefahrlich"),
        "cleanliness": ("sauber", "saubere", "sauberkeit", "schmutzig", "schmutzige", "dreckig", "dreckige",
                        "dreck", "schmutz", "geruch", "gestank", "stinkt", "staub", "staubig", "haare", "flecken",
                        "fleckig", "hygiene", "ekelhaft", "eklig", "mull", "insekten", "kakerlaken", "schimmel"),
        "check_in": ("ankunft", "schlussel", "zugangscode", "anreise", "abreise", "einchecken", "auschecken",
                     "tablet"),
        "staff": ("personal", "mitarbeiter", "rezeption", "freundlich", "freundliches", "freundliche",
                  "unfreundlich", "unfreundliche", "unfreundliches", "hilfsbereit", "hilfsbereites", "nett",
                  "hoflich", "unhoflich", "gastgeber", "service"),
        "noise": ("larm", "laut", "laute", "ruhig", "ruhige", "leise", "hellhorig", "party", "musik"),
        "facilities": ("kuche", "klimaanlage", "heizung", "aufzug", "fahrstuhl", "handtucher", "handtuch",
                       "fruhstuck", "parkplatz", "waschmaschine", "kuhlschrank", "mikrowelle", "warmwasser",
                       "warmes wasser", "pool", "schließfach", "schliessfach", "spind"),
        "location": ("lage", "gelegen", "zentral", "zentrale", "nahe", "bahnhof", "station", "bushaltestelle",
                     "zentrum", "innenstadt", "strand", "zu fuß", "zu fuss", "fußlaufig", "erreichbar"),
        "room_condition": ("bett", "betten", "matratze", "kissen", "bettwasche", "mobel", "vorhange", "gemutlich",
                           "bequem", "bequeme", "unbequem", "unbequeme", "kaputt", "defekt", "abgenutzt",
                           "renovierungsbedurftig", "undicht", "feucht", "eng"),
        "value": ("preis", "preise", "preis-leistung", "preis-leistungs-verhaltnis", "teuer", "gunstig", "billig",
                  "uberteuert", "abzocke"),
    },
    problems=frozenset({
        "kakerlake", "kakerlaken", "schabe", "schaben", "bettwanze", "bettwanzen", "wanzen", "schimmel", "ratte",
        "ratten", "mause", "brandgefahr", "feuer", "offene kabel", "lose kabel", "diebstahl", "gestohlen",
        "geklaut", "unsicher", "gefahrlich", "schmutzig", "schmutzige", "dreckig", "dreckige", "dreck", "schmutz",
        "geruch", "gestank", "stinkt", "staub", "staubig", "haare", "flecken", "fleckig", "ekelhaft", "eklig",
        "mull", "insekten", "unfreundlich", "unfreundliche", "unfreundliches", "unhoflich", "larm", "laut",
        "laute", "hellhorig", "party", "musik", "unbequem", "unbequeme", "kaputt", "defekt", "abgenutzt",
        "renovierungsbedurftig", "undicht", "feucht", "eng", "teuer", "uberteuert", "abzocke",
    }),
    negators=frozenset({"nicht", "kein", "keine", "keinen", "keiner", "keinem", "ohne", "nie", "niemals",
                        "nichts"}),
    fillers=frozenset({"sehr", "so", "zu", "gar", "der", "die", "das", "ein", "eine", "war", "ist", "waren",
                       "sind", "besonders", "wirklich", "ganz", "allzu", "mehr"}),
    contrast=("aber", "jedoch", "sondern", "allerdings", "außer", "ausser", "trotzdem"),
    all_clear=("keine probleme", "kein problem", "nichts auszusetzen", "nichts zu bemangeln", "alles gut"),
    loanwords=_LOAN,
)

IT = Lexicon(
    keywords={
        "safety": ("scarafaggio", "scarafaggi", "blatta", "blatte", "cimice", "cimici", "muffa", "ratto", "ratti",
                   "topo", "topi", "incendio", "fili scoperti", "furto", "rubato", "rubata", "rubati", "ladro",
                   "ladri", "pericoloso", "pericolosa", "insicuro"),
        "cleanliness": ("pulito", "pulita", "puliti", "pulite", "pulizia", "sporco", "sporca", "sporchi",
                        "sporche", "sporcizia", "odore", "puzza", "puzzava", "polvere", "capelli", "peli",
                        "macchie", "igiene", "schifo", "schifoso", "schifosa", "spazzatura", "insetti",
                        "scarafaggi", "muffa"),
        "check_in": ("arrivo", "chiave", "chiavi", "codice", "partenza", "tablet"),
        "staff": ("personale", "reception", "receptionist", "gentile", "gentili", "cordiale", "cordiali",
                  "disponibile", "disponibili", "scortese", "scortesi", "maleducato", "maleducata", "sgarbato",
                  "accoglienza", "proprietario", "servizio"),
        "noise": ("rumore", "rumori", "rumoroso", "rumorosa", "tranquillo", "tranquilla", "silenzioso", "festa",
                  "musica"),
        "facilities": ("cucina", "aria condizionata", "condizionatore", "riscaldamento", "ascensore",
                       "asciugamani", "asciugamano", "colazione", "parcheggio", "lavatrice", "frigorifero", "frigo",
                       "microonde", "acqua calda", "piscina", "armadietto", "armadietti"),
        "location": ("posizione", "posizionato", "situato", "situata", "zona", "quartiere", "vicino", "vicina",
                     "vicinissimo", "stazione", "metro", "autobus", "centro", "spiaggia", "trasporti", "a piedi"),
        "room_condition": ("letto", "letti", "materasso", "cuscino", "cuscini", "lenzuola", "mobili", "tende",
                           "comodo", "comoda", "comodi", "scomodo", "scomoda", "scomodi", "rotto", "rotta",
                           "rotti", "rotte", "vecchio", "vecchia", "usurato", "fatiscente", "umidita", "umido",
                           "stretto"),
        "value": ("prezzo", "prezzi", "rapporto qualita prezzo", "qualita prezzo", "caro", "costoso", "costosa",
                  "economico", "conveniente", "troppo caro", "carissimo"),
    },
    problems=frozenset({
        "scarafaggio", "scarafaggi", "blatta", "blatte", "cimice", "cimici", "muffa", "ratto", "ratti", "topo",
        "topi", "incendio", "fili scoperti", "furto", "rubato", "rubata", "rubati", "ladro", "ladri", "pericoloso",
        "pericolosa", "insicuro", "sporco", "sporca", "sporchi", "sporche", "sporcizia", "odore", "puzza",
        "puzzava", "polvere", "capelli", "peli", "macchie", "schifo", "schifoso", "schifosa", "spazzatura",
        "insetti", "scortese", "scortesi", "maleducato", "maleducata", "sgarbato", "rumore", "rumori", "rumoroso",
        "rumorosa", "festa", "musica", "scomodo", "scomoda", "scomodi", "rotto", "rotta", "rotti", "rotte",
        "vecchio", "vecchia", "usurato", "fatiscente", "umidita", "umido", "stretto", "caro", "costoso", "costosa",
        "troppo caro", "carissimo",
    }),
    negators=frozenset({"non", "senza", "mai", "niente", "nulla", "nessun", "nessuna", "nessuno", "neanche",
                        "nemmeno"}),
    fillers=frozenset({"molto", "troppo", "cosi", "per", "niente", "il", "la", "lo", "i", "le", "un", "una",
                       "era", "e", "erano", "sono", "affatto", "proprio", "particolarmente"}),
    contrast=("ma", "pero", "tuttavia", "eccetto", "tranne"),
    all_clear=("nessun problema", "niente da segnalare", "nulla da segnalare", "niente da dire",
               "nulla da dire"),
    loanwords=_LOAN,
)

PT = Lexicon(
    keywords={
        "safety": ("baratas", "barata no quarto", "percevejo", "percevejos", "mofo", "bolor", "rato", "ratos",
                   "incendio", "fios expostos", "roubo", "roubado", "roubada", "roubaram", "ladrao", "ladroes",
                   "inseguro", "insegura", "perigoso", "perigosa"),
        "cleanliness": ("limpo", "limpa", "limpos", "limpas", "limpeza", "sujo", "suja", "sujos", "sujas",
                        "sujeira", "sujidade", "cheiro", "fedor", "fedia", "poeira", "cabelos", "cabelo",
                        "manchas", "higiene", "nojento", "nojenta", "lixo", "insetos", "baratas", "mofo"),
        "check_in": ("chegada", "chave", "chaves", "codigo", "saida", "tablet"),
        "staff": ("funcionarios", "funcionarias", "funcionario", "equipe", "equipa", "recepcao", "rececao",
                  "recepcionista", "simpatico", "simpaticos", "simpatica", "simpaticas", "atencioso", "atenciosos",
                  "prestativo", "prestativos", "educado", "educados", "mal educado", "antipatico", "antipatica",
                  "grosseiro", "grosseira", "atendimento"),
        "noise": ("barulho", "barulhos", "barulhento", "barulhenta", "ruido", "silencioso", "tranquilo",
                  "tranquila", "festa", "musica"),
        "facilities": ("cozinha", "ar condicionado", "aquecimento", "elevador", "toalhas", "toalha",
                       "cafe da manha", "pequeno almoco", "estacionamento", "lavanderia", "geladeira",
                       "frigorifico", "micro-ondas", "agua quente", "piscina", "cacifo", "cacifos", "armario"),
        "location": ("localizacao", "localizado", "localizada", "bairro", "perto", "proximo", "proxima",
                     "estacao", "metro", "onibus", "autocarro", "centro", "praia", "transporte", "a pe"),
        "room_condition": ("cama", "camas", "colchao", "travesseiro", "travesseiros", "almofada", "lencois",
                           "moveis", "cortinas", "confortavel", "confortaveis", "desconfortavel", "quebrado",
                           "quebrada", "quebrados", "velho", "velha", "gasto", "desgastado", "vazamento",
                           "infiltracao", "umidade", "humidade", "umido", "apertado"),
        "value": ("preco", "precos", "barato", "caro", "caros", "carissimo", "custo beneficio", "custo-beneficio",
                  "vale a pena", "economico"),
    },
    problems=frozenset({
        "baratas", "barata no quarto", "percevejo", "percevejos", "mofo", "bolor", "rato", "ratos", "incendio",
        "fios expostos", "roubo", "roubado", "roubada", "roubaram", "ladrao", "ladroes", "inseguro", "insegura",
        "perigoso", "perigosa", "sujo", "suja", "sujos", "sujas", "sujeira", "sujidade", "cheiro", "fedor",
        "fedia", "poeira", "cabelos", "cabelo", "manchas", "nojento", "nojenta", "lixo", "insetos", "mal educado",
        "antipatico", "antipatica", "grosseiro", "grosseira", "barulho", "barulhos", "barulhento", "barulhenta",
        "ruido", "festa", "musica", "desconfortavel", "quebrado", "quebrada", "quebrados", "velho", "velha",
        "gasto", "desgastado", "vazamento", "infiltracao", "umidade", "humidade", "umido", "apertado", "caro",
        "caros", "carissimo",
    }),
    negators=frozenset({"nao", "sem", "nunca", "nada", "nenhum", "nenhuma", "nem", "jamais"}),
    fillers=frozenset({"muito", "tao", "o", "a", "os", "as", "um", "uma", "era", "e", "estava", "estavam", "foi",
                       "esta", "estao", "havia", "tinha", "nada", "muita", "demasiado"}),
    contrast=("mas", "porem", "contudo", "entretanto", "exceto", "menos"),
    all_clear=("nenhum problema", "sem problemas", "nada a reclamar", "nada a declarar", "nada a apontar"),
    loanwords=_LOAN,
)

LEXICONS: dict[str, Lexicon] = {"fr": FR, "es": ES, "de": DE, "it": IT, "pt": PT}
