"""Tests voor de huurwoningen.com-bron: parser en paginering, zonder netwerk."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.huurwoningencom import HuurwoningenComSource

CONFIG = load_config()

# Klein fragment, gebaseerd op de echte kaartstructuur van huurwoningen.com.
PAGINA_1_HTML = """
<html><body>
  <section class="listing-search-item listing-search-item--list listing-search-item--for-rent">
    <div class="listing-search-item__content">
      <h3 class="listing-search-item__title">
        <a class="listing-search-item__link listing-search-item__link--title"
           href="/huren/amsterdam/b480736a/krijn-taconiskade/">
          Appartement Krijn Taconiskade
        </a>
      </h3>
      <div class="listing-search-item__sub-title">
        1087 HW Amsterdam (IJburg-Zuid)
      </div>
      <div class="listing-search-item__price">
        <span class="listing-search-item__price-main">&euro;&nbsp;1.173 per maand</span>
      </div>
      <div class="listing-search-item__features">
        <ul class="illustrated-features illustrated-features--compact">
          <li class="illustrated-features__item illustrated-features__item--surface-area">45 m&sup2;</li>
          <li class="illustrated-features__item illustrated-features__item--number-of-rooms">3 kamers</li>
        </ul>
      </div>
    </div>
  </section>
  <section class="listing-search-item listing-search-item--list listing-search-item--for-rent">
    <div class="listing-search-item__content">
      <h3 class="listing-search-item__title">
        <a class="listing-search-item__link listing-search-item__link--title"
           href="/huren/amsterdam/1a2b3c4d/kamer-teststraat/">
          Kamer Teststraat
        </a>
      </h3>
      <div class="listing-search-item__sub-title">1012 AB Amsterdam (Centrum)</div>
      <div class="listing-search-item__price">
        <div class="listing-search-item__price-bare">
          <span class="listing-search-item__price-bare-label">Kale huurprijs</span>
          <span>&euro;&nbsp;850 per maand</span>
        </div>
        <div class="listing-search-item__price-transparency-badge">
          <span class="price-transparency-badge__total-price-value">&euro;&nbsp;1.050 per maand</span>
        </div>
      </div>
      <div class="listing-search-item__features">
        <ul class="illustrated-features">
          <li class="illustrated-features__item illustrated-features__item--surface-area">18 m&sup2;</li>
          <li class="illustrated-features__item illustrated-features__item--number-of-rooms">1 kamer</li>
        </ul>
      </div>
    </div>
  </section>
  <section class="listing-search-item listing-search-item--list listing-search-item--for-rent">
    <div class="listing-search-item__content">
      <h3 class="listing-search-item__title">
        <a class="listing-search-item__link listing-search-item__link--title"
           href="/huren/amsterdam/9z8y7x6w/parkeerplaats-garagelaan/">
          Parkeerplaats Garagelaan
        </a>
      </h3>
      <div class="listing-search-item__sub-title">1013 CD Amsterdam (Havens-West)</div>
      <div class="listing-search-item__price">
        <span class="listing-search-item__price-main">&euro;&nbsp;150 per maand</span>
      </div>
    </div>
  </section>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> HuurwoningenComSource:
    return HuurwoningenComSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_parser_leest_velden_uit_kaart():
    """Prijs, url, plaats, postcode, oppervlak en kamers uit de kaartstructuur."""
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    # Parkeerplaats overgeslagen: 2 van de 3 kaarten blijven over.
    assert len(woningen) == 2

    app = woningen[0]
    assert app.titel == "Appartement Krijn Taconiskade"
    assert app.prijs == 1173
    assert app.url == "https://www.huurwoningen.com/huren/amsterdam/b480736a/krijn-taconiskade/"
    assert app.plaats == "Amsterdam"
    assert app.postcode == "1087 HW"
    assert app.buurt == "IJburg-Zuid"
    assert app.oppervlak_m2 == 45
    assert app.slaapkamers == 2       # 3 kamers incl. woonkamer
    assert app.gedeelde_voorzieningen is False
    assert app.bron == "huurwoningencom"
    assert app.type == "huur"


def test_kamer_krijgt_gedeelde_voorzieningen_en_kale_huur():
    """Bij prijstransparantie pakken we de kale huur, niet de totale huurprijs."""
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    kamer = woningen[1]
    assert kamer.gedeelde_voorzieningen is True
    assert kamer.prijs == 850         # kale huur, niet 1050


def test_404_op_vervolgpagina_behoudt_eerdere_resultaten():
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
    assert len(woningen) == 2


def test_andere_fout_blijft_fout():
    """Serverfouten (500) zijn wel echte fouten en moeten omhoog borrelen."""
    bron = _bron()

    def nep_get(url, **kwargs):
        raise _http_error(500)

    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()


def test_redirect_naar_pagina_1_stopt_paginering():
    """Voorbij de laatste pagina redirect de site naar pagina 1; dubbele
    URL's mogen dan niet nogmaals meetellen en de paginering stopt."""
    bron = _bron(max_paginas=5)

    def nep_get(url, **kwargs):
        return Mock(text=PAGINA_1_HTML)   # elke pagina 'redirect' naar dezelfde inhoud

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2
    assert len({w.url for w in woningen}) == 2


def test_max_woningen_wordt_gerespecteerd():
    bron = _bron(max_paginas=5)
    bron.max_woningen = 2

    def nep_get(url, **kwargs):
        return Mock(text=PAGINA_1_HTML)

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2
