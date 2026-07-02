"""Tests voor de Interhouse-bron: REST-filter, detailparser en paginering (zonder netwerk)."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.interhouse import InterhouseSource

CONFIG = load_config()

# Gebaseerd op de echte dt/dd-kenmerkentabel van een interhouse.nl-detailpagina.
DETAIL_HTML = """
<html><head>
  <meta property="og:image" content="https://interhouse.nl/wp-content/uploads/2026/06/985000-123.jpeg">
</head><body>
  <div class="property-tables"><dl>
    <dt>Straatnaam</dt><dd>Keizersgracht</dd>
    <dt>Postcode</dt><dd>1016GC</dd>
    <dt>Stad</dt><dd>Amsterdam</dd>
    <dt>Huurprijs</dt><dd>&euro; 3.250,- per maand <small>Exclusief voorzieningen</small></dd>
    <dt>Waarborgsom</dt><dd>&euro; 6.500,-</dd>
    <dt>Status</dt><dd>Te huur</dd>
    <dt>Interieur</dt><dd>Gestoffeerd</dd>
    <dt>Aanvaardingsdatum</dt><dd>07-07-2026</dd>
    <dt>Type</dt><dd>Appartement</dd>
    <dt>Woonoppervlakte</dt><dd>91 m&sup2;</dd>
    <dt>Aantal kamers</dt><dd>2 kamers</dd>
    <dt>Aantal slaapkamers</dt><dd>1 slaapkamer</dd>
    <dt>Voorzieningen</dt><dd>tuin, kelder</dd>
    <dt>Energieklasse</dt><dd>A</dd>
  </dl></div>
</body></html>
"""

DETAIL_URL = "https://interhouse.nl/vastgoed/huur/amsterdam/appartement/keizersgracht-2/"

# REST-items zoals /wp-json/wp/v2/property ze teruggeeft (ingekort).
ITEM_HUUR_AMS = {
    "link": DETAIL_URL,
    "title": {"rendered": "Keizersgracht 2, Amsterdam"},
    "date": "2026-07-01T06:00:00",
}
ITEM_HUUR_AMS_OOST = {
    "link": "https://interhouse.nl/vastgoed/huur/amsterdam-oost/appartement/venetiehof/",
    "title": {"rendered": "Venetiëhof, Amsterdam"},
    "date": "2026-06-20T06:00:00",
}
ITEM_KOOP = {
    "link": "https://interhouse.nl/vastgoed/koop/haarlem/appartement/lange-herenstraat-135/",
    "title": {"rendered": "Lange Herenstraat 135, Haarlem"},
    "date": "2026-07-02T06:00:00",
}
ITEM_ANDERE_STAD = {
    "link": "https://interhouse.nl/vastgoed/huur/rotterdam/appartement/de-savornin-lohmanlaan-2/",
    "title": {"rendered": "De Savornin Lohmanlaan 2, Rotterdam"},
    "date": "2026-07-01T06:00:00",
}
ITEM_PARKEREN = {
    "link": "https://interhouse.nl/vastgoed/huur/amsterdam/parkeerplaats/bijlmerdreef/",
    "title": {"rendered": "Bijlmerdreef, Amsterdam"},
    "date": "2026-07-01T06:00:00",
}


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 1) -> InterhouseSource:
    return InterhouseSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_interhouse_parse_detailvelden():
    """De parser leest prijs, url, plaats en kenmerken uit de detailpagina."""
    bron = _bron()
    woning = bron._parse_detail(DETAIL_URL, DETAIL_HTML, titel="Keizersgracht 2, Amsterdam")

    assert woning is not None
    assert woning.prijs == 3250
    assert woning.url == DETAIL_URL
    assert woning.plaats == "Amsterdam"
    assert woning.postcode == "1016GC"
    assert woning.adres == "Keizersgracht"
    assert woning.titel == "Keizersgracht 2, Amsterdam"
    assert woning.oppervlak_m2 == 91
    assert woning.slaapkamers == 1
    assert woning.energielabel == "A"
    assert woning.buitenruimte is True
    assert woning.buitenruimte_soort == "tuin"
    assert woning.gedeelde_voorzieningen is False
    assert woning.type == "huur"
    assert woning.bron == "interhouse"
    assert woning.afbeelding_url.startswith("https://interhouse.nl/wp-content/")


def test_interhouse_kamer_is_gedeeld():
    """Type 'Kamer' krijgt gedeelde_voorzieningen=True."""
    bron = _bron()
    html = DETAIL_HTML.replace("<dd>Appartement</dd>", "<dd>Kamer</dd>")
    woning = bron._parse_detail(DETAIL_URL, html)
    assert woning is not None
    assert woning.gedeelde_voorzieningen is True


def test_interhouse_parkeerplaats_wordt_overgeslagen():
    """Parkeerplaatsen/garages zijn geen woonruimte."""
    bron = _bron()
    html = DETAIL_HTML.replace("<dd>Appartement</dd>", "<dd>Parkeerplaats</dd>")
    assert bron._parse_detail(DETAIL_URL, html) is None
    html = DETAIL_HTML.replace("<dd>Appartement</dd>", "<dd>Garagebox</dd>")
    assert bron._parse_detail(DETAIL_URL, html) is None


def test_interhouse_filter_rest_items():
    """Alleen huur in de geconfigureerde steden komt door het REST-filter."""
    bron = _bron()
    assert bron._filter_item(ITEM_HUUR_AMS) is not None
    assert bron._filter_item(ITEM_HUUR_AMS_OOST) is not None   # prefix-match
    assert bron._filter_item(ITEM_KOOP) is None
    assert bron._filter_item(ITEM_ANDERE_STAD) is None
    assert bron._filter_item(ITEM_PARKEREN) is None

    url, titel, datum = bron._filter_item(ITEM_HUUR_AMS)
    assert url == DETAIL_URL
    assert titel == "Keizersgracht 2, Amsterdam"
    assert datum == "2026-07-01"


def test_interhouse_404_is_einde_paginering():
    """Een 404/400 op de volgende REST-pagina is einde paginering, geen fout."""
    bron = _bron(max_paginas=3)
    bron._per_pagina = 1        # zodat er een tweede pagina geprobeerd wordt

    antwoorden = [
        Mock(json=Mock(return_value=[ITEM_HUUR_AMS])),   # REST pagina 1
        Mock(text=DETAIL_HTML),                          # detailpagina
        _http_error(404),                                # REST pagina 2
    ]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 1
    assert woningen[0].prijs == 3250
    assert antwoorden == []     # alle drie de calls zijn gedaan


def test_interhouse_kapotte_detailpagina_blokkeert_oogst_niet():
    """Een 404 op één detailpagina laat de rest van de oogst intact."""
    bron = _bron()
    antwoorden = [
        Mock(json=Mock(return_value=[ITEM_HUUR_AMS, ITEM_HUUR_AMS_OOST])),
        _http_error(404),          # detail 1 kapot
        Mock(text=DETAIL_HTML),    # detail 2 ok
    ]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 1


def test_interhouse_andere_fout_blijft_fout():
    """Serverfouten (500) zijn wel echte fouten en moeten omhoog borrelen."""
    bron = _bron()

    def nep_get(url, **kwargs):
        raise _http_error(500)

    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()
