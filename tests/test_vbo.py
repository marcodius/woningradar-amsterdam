"""Tests voor de VBO-koopbron: parser en paginering-robuustheid (zonder netwerk)."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.vbo import VboSource

CONFIG = load_config()

# Klein fragment, gebaseerd op de echte kaartstructuur van
# aanbod.vastgoednederland.nl (a.propertyLink > figure.property).
PAGINA_1_HTML = """
<html><body>
<div id="propertiesWrapper" class="properties grid"><div class="row">
  <div class="col-12 col-sm-6 col-lg-4">
    <a href="https://aanbod.vastgoednederland.nl/koopwoningen/amsterdam/woning-648531-blasiusstraat-98d" class="propertyLink">
      <figure class="property">
        <img src="https://d1zsattj8yq64o.cloudfront.net/media/21576933/424x318_crop.jpg" alt="Blasiusstraat 98D">
        <div class="label">Nieuw</div>
        <figcaption>
          <span class="street">Blasiusstraat 98D</span><br>
          <span class="city">Amsterdam</span><br>
          <span class="price">&euro; 550.000,- k.k.</span>
          <div class="bottom">
            <ul>
              <li><span class="icon icon-meter"></span> 55 m&#178;</li>
              <li><span class="icon icon-bed"></span> 1</li>
            </ul>
            <span class="energielabel energy-A">A</span>
          </div>
          <div class="broker">Klok Real Estate B.V.</div>
        </figcaption>
      </figure>
    </a>
  </div>
  <div class="col-12 col-sm-6 col-lg-4">
    <a href="https://aanbod.vastgoednederland.nl/koopwoningen/amsterdam/parkeergelegenheid-123-teststraat" class="propertyLink">
      <figure class="property">
        <figcaption>
          <span class="street">Parkeerplaats Teststraat</span><br>
          <span class="city">Amsterdam</span><br>
          <span class="price">&euro; 75.000,- k.k.</span>
        </figcaption>
      </figure>
    </a>
  </div>
</div></div>
</body></html>
"""

LEGE_PAGINA_HTML = """
<html><body>
<div id="propertiesWrapper" class="properties grid"><div class="row"></div></div>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> VboSource:
    return VboSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_vbo_parse_kaart_velden():
    """De parser haalt prijs, adres, oppervlak en label uit een echte kaart."""
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    assert len(woningen) == 1   # parkeerplaats overgeslagen
    w = woningen[0]
    assert w.type == "koop"
    assert w.prijs == 550000
    assert w.titel == "Blasiusstraat 98D"
    assert w.plaats == "Amsterdam"
    assert w.oppervlak_m2 == 55
    assert w.slaapkamers == 1
    assert w.energielabel == "A"
    assert w.bron == "vbo"
    assert w.url == (
        "https://aanbod.vastgoednederland.nl/koopwoningen/amsterdam/"
        "woning-648531-blasiusstraat-98d"
    )
    assert w.afbeelding_url.startswith("https://")


def test_vbo_lege_vervolgpagina_stopt_paginering():
    """Voorbij het einde geeft de site 200 met nul kaarten: netjes stoppen."""
    bron = _bron()
    antwoorden = [Mock(text=PAGINA_1_HTML), Mock(text=LEGE_PAGINA_HTML)]

    def nep_get(url, **kwargs):
        return antwoorden.pop(0)

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 1
    assert woningen[0].prijs == 550000


def test_vbo_404_op_vervolgpagina_behoudt_eerdere_resultaten():
    """Een 404 op pagina 2 betekent 'geen volgende pagina', geen bronfout."""
    bron = _bron()
    antwoorden = [Mock(text=PAGINA_1_HTML), _http_error(404)]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 1


def test_vbo_andere_fout_blijft_fout():
    """Serverfouten (500) zijn wel echte fouten en moeten omhoog borrelen."""
    bron = _bron()

    def nep_get(url, **kwargs):
        raise _http_error(500)

    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()
