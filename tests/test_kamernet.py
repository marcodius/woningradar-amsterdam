"""Tests voor de Kamernet-bron: JSON-parsing, kamer-vs-appartement en paginering."""
import json
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.kamernet import KamernetSource

CONFIG = load_config()


def _next_data_html(listings, top_ads=None) -> str:
    """Bouw een minimale Next.js-pagina zoals kamernet.nl die rendert."""
    data = {
        "props": {
            "pageProps": {
                "targetPageProps": {
                    "findListingsResponse": {
                        "listings": listings,
                        "topAdListings": top_ads or [],
                        "total": len(listings),
                    }
                }
            }
        }
    }
    return (
        "<html><body><div id=\"__next\">kaarten</div>"
        f"<script id=\"__NEXT_DATA__\" type=\"application/json\">{json.dumps(data)}</script>"
        "</body></html>"
    )


# Velden zoals ze echt in de Kamernet-JSON staan (uit de fixture).
KAMER = {
    "listingId": 2380154,
    "listingType": 1,   # kamer
    "street": "Gerard Schaepstraat",
    "streetSlug": "gerard-schaepstraat",
    "city": "Amsterdam",
    "citySlug": "amsterdam",
    "surfaceArea": 84,
    "totalRentalPrice": 1503,
    "availabilityEndDate": None,
    "resizedFullPreviewImageUrl": "https://resources.kamernet.nl/image/x/resize/422-225",
}

APPARTEMENT = {
    "listingId": 2386059,
    "listingType": 2,   # appartement
    "street": "De Clercqstraat",
    "streetSlug": "de-clercqstraat",
    "city": "Amsterdam",
    "citySlug": "amsterdam",
    "surfaceArea": 68,
    "totalRentalPrice": 2500,
    "availabilityEndDate": None,
    "thumbnailUrl": "https://resources.kamernet.nl/image/y",
}

PAGINA_HTML = _next_data_html([KAMER, APPARTEMENT])


def _bron(max_paginas: int = 3) -> KamernetSource:
    return KamernetSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_kamernet_parse_kamer_en_appartement():
    """Kamer krijgt gedeelde_voorzieningen=True, appartement niet; velden kloppen."""
    woningen = _bron()._parse_lijst(PAGINA_HTML)
    assert len(woningen) == 2
    kamer, app = woningen

    assert kamer.gedeelde_voorzieningen is True
    assert kamer.prijs == 1503
    assert kamer.oppervlak_m2 == 84
    assert kamer.plaats == "Amsterdam"
    assert kamer.url == (
        "https://kamernet.nl/huren/kamer-amsterdam/gerard-schaepstraat/kamer-2380154"
    )
    assert kamer.bron == "kamernet"
    assert kamer.type == "huur"

    assert app.gedeelde_voorzieningen is False
    assert app.prijs == 2500
    assert app.url == (
        "https://kamernet.nl/huren/appartement-amsterdam/de-clercqstraat/appartement-2386059"
    )
    assert app.afbeelding_url == "https://resources.kamernet.nl/image/y"


def test_kamernet_anti_kraak_is_tijdelijk_en_onbekend_type_valt_weg():
    """Anti-kraak (type 8) -> tijdelijk contract; onbekend type wordt overgeslagen."""
    anti_kraak = dict(KAMER, listingId=1, listingType=8, streetSlug="roggeveldweg")
    onbekend = dict(APPARTEMENT, listingId=2, listingType=99)
    woningen = _bron()._parse_lijst(_next_data_html([anti_kraak, onbekend]))
    assert len(woningen) == 1
    assert woningen[0].tijdelijk_contract is True
    assert "anti-kraak" in woningen[0].url


def test_kamernet_lege_pagina_stopt_paginering():
    """Voorbij de laatste pagina geeft Kamernet 200 met lege listings-lijst."""
    bron = _bron(max_paginas=5)
    antwoorden = [Mock(text=PAGINA_HTML), Mock(text=_next_data_html([]))]
    bron.get = lambda url, **kw: antwoorden.pop(0)
    woningen = bron.haal_op()
    assert len(woningen) == 2


def test_kamernet_404_op_vervolgpagina_behoudt_eerdere_resultaten():
    """Een 404 tijdens paginering is einde paginering, geen bronfout."""
    bron = _bron()
    resp = Mock(spec=requests.Response)
    resp.status_code = 404
    antwoorden = [Mock(text=PAGINA_HTML), requests.HTTPError("404", response=resp)]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2


def test_kamernet_top_ads_worden_ontdubbeld():
    """Top-ads die ook in de gewone lijst staan tellen maar één keer."""
    woningen = _bron()._parse_lijst(_next_data_html([KAMER, APPARTEMENT], top_ads=[KAMER]))
    assert len(woningen) == 2
