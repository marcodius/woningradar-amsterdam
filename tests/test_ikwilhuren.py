"""Tests voor de ikwilhuren.nu-bron: kaart-parser en pagineringsrobuustheid."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.ikwilhuren import IkwilhurenSource

CONFIG = load_config()

# Gebaseerd op de echte kaartstructuur van ikwilhuren.nu (div.card-woning).
KAART_HTML = """
<html><body><div class="row">
  <div class="card card-woning shadow-sm">
    <div class="card-img-top">
      <picture><img src='//a.static.nbo.nl/media/cd/cd705e/768x510/thumb.jpg' alt="Schipholweg 232"/></picture>
    </div>
    <div class="card-body d-flex flex-column">
      <span class="card-title h5"><a class="stretched-link"
        href="/object/amsterdam-1012ab-232-schipholweg-92cd0f820bde/">
        Appartement Schipholweg 232</a></span>
      <span>1012AB Amsterdam</span>
      <div class="pt-4 dotted-spans mt-auto">
        <span class="fw-bold">&euro; 1.166,- /mnd</span>
        <span>46 m<sup>2</sup></span>
        <span>1  slaapkamer </span>
      </div>
    </div>
  </div>
  <div class="card card-woning shadow-sm">
    <div class="card-body">
      <span class="card-title h5"><a class="stretched-link"
        href="/object/amsterdam-1013cd-9-parkeerhof-aabbccddee/">
        Parkeerplaats Parkeerhof 9</a></span>
      <span>1013CD Amsterdam</span>
      <div><span class="fw-bold">&euro; 150,- /mnd</span></div>
    </div>
  </div>
  <div class="card card-woning shadow-sm">
    <div class="card-body">
      <span class="card-title h5"><a class="stretched-link"
        href="/object/leiden-2316xd-45-stationsweg-ffeeddccbb/">
        Kamer Stationsweg 45</a></span>
      <span>2316XD Leiden</span>
      <div>
        <span class="fw-bold">&euro; 750,- /mnd</span>
        <span>18 m<sup>2</sup></span>
      </div>
    </div>
  </div>
</div></body></html>
"""


def _bron(**conf) -> IkwilhurenSource:
    return IkwilhurenSource(CONFIG, conf)


def test_parser_leest_kaartvelden():
    """De parser haalt prijs, oppervlak, slaapkamers, plaats en url uit een kaart."""
    bron = _bron()
    woningen = bron._parse_lijst(KAART_HTML)
    # Parkeerplaats wordt overgeslagen; woning + kamer blijven over.
    assert len(woningen) == 2

    w = woningen[0]
    assert w.titel == "Appartement Schipholweg 232"
    assert w.prijs == 1166
    assert w.oppervlak_m2 == 46
    assert w.slaapkamers == 1
    assert w.plaats == "Amsterdam"
    assert w.postcode == "1012AB"
    assert w.adres == "Schipholweg 232"
    assert w.url == "https://ikwilhuren.nu/object/amsterdam-1012ab-232-schipholweg-92cd0f820bde/"
    assert w.type == "huur"
    assert w.bron == "ikwilhuren"
    assert w.gedeelde_voorzieningen is False
    assert w.afbeelding_url == "https://a.static.nbo.nl/media/cd/cd705e/768x510/thumb.jpg"


def test_kamer_krijgt_gedeelde_voorzieningen():
    bron = _bron()
    woningen = bron._parse_lijst(KAART_HTML)
    kamer = woningen[1]
    assert kamer.titel == "Kamer Stationsweg 45"
    assert kamer.gedeelde_voorzieningen is True
    assert kamer.plaats == "Leiden"


def test_haal_op_filtert_op_plaats():
    """De landelijke lijst wordt gefilterd op de geconfigureerde plaatsen."""
    bron = _bron(max_paginas=1, plaatsen=["amsterdam"])
    bron.get = lambda url, **kw: Mock(text=KAART_HTML)
    woningen = bron.haal_op()
    assert len(woningen) == 1
    assert woningen[0].plaats == "Amsterdam"


def test_404_op_vervolgpagina_behoudt_eerdere_resultaten():
    """Een 404 tijdens paginering is 'einde lijst', geen bronfout."""
    bron = _bron(max_paginas=3, plaatsen=[])
    resp404 = Mock(spec=requests.Response)
    resp404.status_code = 404
    antwoorden = [Mock(text=KAART_HTML), requests.HTTPError("404", response=resp404)]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2


def test_andere_http_fout_blijft_fout():
    bron = _bron(max_paginas=2, plaatsen=[])
    resp500 = Mock(spec=requests.Response)
    resp500.status_code = 500

    def nep_get(url, **kwargs):
        raise requests.HTTPError("500", response=resp500)

    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()


def test_herhaalde_pagina_stopt_paginering():
    """Voorbij de laatste pagina serveert de site dezelfde kaarten opnieuw."""
    bron = _bron(max_paginas=5, plaatsen=[])
    bron.get = lambda url, **kw: Mock(text=KAART_HTML)
    woningen = bron.haal_op()
    # Pagina 2 bevat alleen al geziene urls -> stoppen, geen duplicaten.
    assert len(woningen) == 2
