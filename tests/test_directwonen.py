"""Tests voor de DirectWonen-parser: kaartstructuur, premium-links en 404-einde."""
import os
import sys
from unittest.mock import Mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.directwonen import DirectwonenSource

CONFIG = load_config()

# Gebaseerd op de echte kaartstructuur van directwonen.nl (juli 2026):
# a.inner-content > .new-search-advert met kop, prijs, locatie en banners.
PAGINA_HTML = """
<html><body>
<div class="tiles-container">
  <div class="tile">
    <a href="/premiumaccountpayment?ip=4&amp;returnUrl=https%3A%2F%2Fdirectwonen.nl%2Fhuurwoningen-huren%2Famsterdam%2Foranje-nassaulaan%2Fappartement-517354&amp;entityId=517354" class="inner-content">
      <div class="new-search-advert">
        <div class="advert-header">
          <div class="advert-location">
            <div class="advert-location-title">
              <span class="advert-location-header h2">Appartement</span>
            </div>
            <div class="advert-location-price">&euro; 8895</div>
          </div>
          <div class="advert-location">
            <h3 class="location-text">O. Nassaulaan, Amsterdam</h3>
            <div class="kale-huur">(Excl.)</div>
          </div>
        </div>
        <div class="advertise-content">
          <div class="advert-thumbnail ">
            <img alt="foto" src="https://resources.directwonen.nl/image/abc123" />
          </div>
          <div class="small-banner rooms">
            <p class="small-banner-top">3</p>
            <p class="small-banner-bottom">kmr</p>
          </div>
          <div class="small-banner surface">
            <p class="small-banner-top">162</p>
            <p class="small-banner-bottom">m<sup>2</sup></p>
          </div>
        </div>
      </div>
    </a>
  </div>
  <div class="tile">
    <a href="https://directwonen.nl/huurwoningen-huren/amsterdam/hofgeest/kamer-517327" class="inner-content">
      <div class="new-search-advert">
        <div class="advert-header">
          <div class="advert-location">
            <span class="advert-location-header h2">Kamer</span>
            <div class="advert-location-price">&euro; 950</div>
          </div>
          <div class="advert-location">
            <h3 class="location-text">Hofgeest, Amsterdam</h3>
          </div>
        </div>
        <div class="advertise-content">
          <div class="small-banner rooms">
            <p class="small-banner-top">1</p>
            <p class="small-banner-bottom">kmr</p>
          </div>
        </div>
      </div>
    </a>
  </div>
  <div class="tile">
    <a href="https://directwonen.nl/hoe-werkt-het" class="inner-content">
      <div class="promo">Hoe werkt het?</div>
    </a>
  </div>
</div>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> DirectwonenSource:
    return DirectwonenSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_directwonen_parseert_kaartvelden():
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_HTML)
    assert len(woningen) == 2  # promo-tegel wordt overgeslagen

    appartement = woningen[0]
    assert appartement.prijs == 8895
    assert appartement.plaats == "Amsterdam"
    assert appartement.adres == "O. Nassaulaan"
    assert appartement.oppervlak_m2 == 162
    assert appartement.slaapkamers == 2  # 3 kamers incl. woonkamer
    assert appartement.gedeelde_voorzieningen is False
    # Premium-link wordt uitgepakt naar de echte detail-URL.
    assert appartement.url == "https://directwonen.nl/huurwoningen-huren/amsterdam/oranje-nassaulaan/appartement-517354"
    assert appartement.afbeelding_url == "https://resources.directwonen.nl/image/abc123"
    assert appartement.bron == "directwonen"
    assert appartement.type == "huur"

    kamer = woningen[1]
    assert kamer.prijs == 950
    assert kamer.gedeelde_voorzieningen is True


def test_directwonen_404_op_vervolgpagina_behoudt_eerdere_resultaten():
    """Een 404 op pagina 2 betekent 'geen volgende pagina', geen bronfout."""
    bron = _bron()
    antwoorden = [Mock(text=PAGINA_HTML), _http_error(404)]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2


def test_directwonen_respecteert_max_woningen():
    bron = _bron(max_paginas=5)
    bron.max_woningen = 1

    def nep_get(url, **kwargs):
        return Mock(text=PAGINA_HTML)

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 1
