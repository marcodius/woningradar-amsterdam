"""Tests voor de Maxx Huren-bron: parser en pagineringsrobuustheid (zonder netwerk)."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.maxxhuren import MaxxhurenSource

CONFIG = load_config()

# Gebaseerd op de echte kaartstructuur van maxxhuren.nl/woonruimte-huren/.
LIJST_HTML = """
<html><body>
  <a id="object-22842" href="/objects/ads/view/id-22842/" class="object w-inline-block">
    <div class="div-block-75">
      <img src="https://maxxhuren.nl/cdn-cgi/image/width=600/foto.jpg" alt="Celebesstraat 25" class="image-7">
    </div>
    <div class="div-block-76">
      <div class="text-block-34">Celebesstraat 25-a</div>
      <div class="plaatsnaam-object">Groningen</div>
      <div class="type-woonruimte-object">Studio</div>
      <div class="huurprijs-object">&euro;501,28 per maand</div>
      <div class="oppervlak-object">15m&sup2;</div>
      <div class="text-block-35">1 kamers</div>
    </div>
  </a>
  <a id="object-22575" href="/objects/ads/view/id-22575/" class="object w-inline-block">
    <div class="text-block-34">Hofstraat 13-b s1</div>
    <div class="plaatsnaam-object">Groningen</div>
    <div class="type-woonruimte-object">Kamer</div>
    <div class="huurprijs-object">&euro;723,19 per maand</div>
    <div class="oppervlak-object">50m&sup2;</div>
    <div class="text-block-35">3 kamers</div>
  </a>
  <a id="object-18793" href="/objects/ads/view/id-18793/" class="object w-inline-block">
    <div class="text-block-34">Waldeck Pyrmontplein 5--2</div>
    <div class="plaatsnaam-object">Groningen</div>
    <div class="type-woonruimte-object">Berging</div>
    <div class="huurprijs-object">&euro;150,00 per maand</div>
    <div class="oppervlak-object">12m&sup2;</div>
    <div class="text-block-35"> kamers</div>
  </a>
  <a id="object-19019" href="/objects/ads/view/id-19019/" class="object w-inline-block">
    <div class="object-reeds-verhuurd">Reeds verhuurd</div>
    <div class="text-block-34">Hoornsediep 46-B</div>
    <div class="plaatsnaam-object">Groningen</div>
    <div class="type-woonruimte-object">Appartement</div>
    <div class="huurprijs-object">&euro;1.222,74 per maand</div>
    <div class="oppervlak-object">61m&sup2;</div>
    <div class="text-block-35">3 kamers</div>
  </a>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 1) -> MaxxhurenSource:
    return MaxxhurenSource(CONFIG, {"max_paginas": max_paginas})


def test_maxxhuren_parse_kaartvelden():
    """De parser leest prijs, url, plaats, oppervlak en kamers uit een kaart."""
    bron = _bron()
    woningen = bron._parse_lijst(LIJST_HTML)
    # Berging en 'Reeds verhuurd' vallen af: 2 van de 4 blijven over.
    assert len(woningen) == 2

    studio = woningen[0]
    assert studio.prijs == 501
    assert studio.url == "https://maxxhuren.nl/objects/ads/view/id-22842/"
    assert studio.plaats == "Groningen"
    assert studio.titel == "Celebesstraat 25-a"
    assert studio.oppervlak_m2 == 15
    assert studio.slaapkamers == 0          # 1 kamer incl. woonkamer
    assert studio.gedeelde_voorzieningen is False
    assert studio.type == "huur"
    assert studio.bron == "maxxhuren"
    assert studio.afbeelding_url.startswith("https://maxxhuren.nl/cdn-cgi/")

    kamer = woningen[1]
    assert kamer.prijs == 723
    assert kamer.gedeelde_voorzieningen is True   # type Kamer = gedeeld
    assert kamer.slaapkamers == 2


def test_maxxhuren_404_is_einde_paginering():
    """Een 404 tijdens paginering is 'geen volgende pagina', geen bronfout."""
    bron = _bron(max_paginas=3)
    antwoorden = [Mock(text=LIJST_HTML), _http_error(404)]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2


def test_maxxhuren_herhaalde_pagina_stopt_paginering():
    """De site negeert ?page=N en geeft dezelfde inhoud: geen duplicaten oogsten."""
    bron = _bron(max_paginas=3)
    telling = {"n": 0}

    def nep_get(url, **kwargs):
        telling["n"] += 1
        return Mock(text=LIJST_HTML)

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 2      # geen duplicaten
    assert telling["n"] == 2       # gestopt na de eerste herhaling


def test_maxxhuren_andere_fout_blijft_fout():
    """Serverfouten (500) zijn wel echte fouten en moeten omhoog borrelen."""
    bron = _bron()

    def nep_get(url, **kwargs):
        raise _http_error(500)

    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()
