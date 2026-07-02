"""Tests voor de Huurstunt-bron: kaart-parsing en paginering (zonder netwerk)."""
import os
import sys
from unittest.mock import Mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.huurstunt import HuurstuntSource

CONFIG = load_config()

# Verkleinde kopie van de echte kaartstructuur op /huren/amsterdam/.
PAGINA_1_HTML = """
<html><body>
  <div class="relative">
    <article class="z-20 relative bg-white">
      <span>Te huur</span>
      <div class="flex flex-col gap-6">
        <header class="flex flex-col gap-1">
          <h3 class="font-semibold text-lg text-gray-900 truncate">Wolbrantskerkweg</h3>
          <ul class="flex flex-row gap-1 text-sm text-gray-500 text-start">
            <li><span>90 m2</span></li>
            <li><span>3 kamers</span></li>
            <li><span class="truncate">Amsterdam</span></li>
          </ul>
        </header>
        <footer class="flex flex-row items-center justify-between">
          <p class="text-sm font-semibold">&euro; 2.785 <span class="text-gray-500">/maand</span></p>
          <a href="https://www.huurstunt.nl/appartement/huren/in/amsterdam/wolbrantskerkweg/f6yau"
             aria-label="Ga naar wolbrantskerkweg Amsterdam">Meer zien</a>
        </footer>
      </div>
    </article>
  </div>
  <div class="relative">
    <article class="z-20 relative bg-white">
      <span>Te huur</span>
      <h3>Sarphatistraat</h3>
      <ul><li><span>14 m2</span></li><li><span>1 kamers</span></li><li><span>Amsterdam</span></li></ul>
      <p>&euro; 950 <span>/maand</span></p>
      <a href="https://www.huurstunt.nl/kamer/huren/in/amsterdam/sarphatistraat/f9abc">Meer zien</a>
    </article>
  </div>
  <div class="relative">
    <article class="z-20 relative bg-white">
      <span>Te huur</span>
      <h3>Garageplein</h3>
      <ul><li><span>12 m2</span></li></ul>
      <p>&euro; 250 <span>/maand</span></p>
      <a href="https://www.huurstunt.nl/parkeerplaats/huren/in/amsterdam/garageplein/f9xyz">Meer zien</a>
    </article>
  </div>
  <div class="relative">
    <article class="z-20 relative bg-white">
      <span>Verhuurd</span>
      <h3>Keizersgracht</h3>
      <ul><li><span>70 m2</span></li><li><span>2 kamers</span></li><li><span>Amsterdam</span></li></ul>
      <p>&euro; 3.750 <span>/maand</span></p>
      <a href="https://www.huurstunt.nl/appartement/huren/in/amsterdam/keizersgracht/f7h5H">Meer zien</a>
    </article>
  </div>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> HuurstuntSource:
    return HuurstuntSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_huurstunt_parseert_kaartvelden():
    """Prijs, url, plaats, oppervlak en kamers komen correct uit de kaart."""
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    # Parkeerplaats en verhuurde woning vallen af.
    assert len(woningen) == 2

    appartement = woningen[0]
    assert appartement.titel == "Wolbrantskerkweg"
    assert appartement.prijs == 2785
    assert appartement.plaats == "Amsterdam"
    assert appartement.oppervlak_m2 == 90
    assert appartement.slaapkamers == 2   # 3 kamers = incl. woonkamer
    assert appartement.url == "https://www.huurstunt.nl/appartement/huren/in/amsterdam/wolbrantskerkweg/f6yau"
    assert appartement.bron == "huurstunt"
    assert appartement.type == "huur"
    assert appartement.gedeelde_voorzieningen is False


def test_huurstunt_kamer_krijgt_gedeelde_voorzieningen():
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    kamer = next(w for w in woningen if "kamer" in w.url)
    assert kamer.gedeelde_voorzieningen is True
    assert kamer.prijs == 950


def test_huurstunt_404_op_vervolgpagina_behoudt_eerdere_resultaten():
    """Een 404 op /p2 betekent 'geen volgende pagina', geen bronfout."""
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
