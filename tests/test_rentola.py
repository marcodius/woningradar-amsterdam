"""Tests voor de Rentola-bron: kaartparser en pagineringsrobuustheid."""
import os
import sys
from unittest.mock import Mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.rentola import RentolaSource

CONFIG = load_config()

# Fragment gebaseerd op de echte kaartstructuur van rentola.nl/huren/amsterdam:
# elke woning staat twee keer op de pagina (mobiele + desktop-kaart), plus hier
# een parkeerplaats-kaart die overgeslagen moet worden.
PAGINA_1_HTML = """
<html><body>
  <div class="relative flex overflow-hidden rounded-xl border border-grey-300 bg-white xl:hidden">
    <a class="relative w-40 shrink-0" href="/listings/apartment-at-quellijnstraat-90-1a-1072xx-amsterdam-p42abc6">
      <picture><img alt="appartement" src="https://img2.rentola.com/foto.jpg"/></picture>
    </a>
    <div class="relative min-w-0 flex-1 p-2">
      <a class="absolute inset-0 z-1" href="/listings/apartment-at-quellijnstraat-90-1a-1072xx-amsterdam-p42abc6"></a>
      <p class="text-base font-medium text-blue-300 line-clamp-2">2-slaapkamer appartement van 32 m&#178;</p>
      <p class="truncate text-sm text-grey-400">Quellijnstraat 90-1A, 1072 XX Amsterdam, Netherlands</p>
      <p class="text-base font-bold text-blue-300">&euro;929 / maand</p>
    </div>
  </div>
  <div class="relative h-full flex-col overflow-hidden rounded-xl border border-grey-300 hidden xl:flex">
    <a class="relative block size-full" href="/listings/apartment-at-quellijnstraat-90-1a-1072xx-amsterdam-p42abc6"></a>
    <p class="text-base font-medium text-blue-300">2-slaapkamer appartement van 32 m&#178;</p>
    <p class="truncate text-sm text-grey-400">Quellijnstraat 90-1A, 1072 XX Amsterdam, Netherlands</p>
    <p class="text-base font-bold text-blue-300">&euro;929 / maand</p>
  </div>
  <div class="relative flex overflow-hidden rounded-xl border border-grey-300 bg-white xl:hidden">
    <a class="absolute inset-0 z-1" href="/listings/gemeubileerde-kamer-amsterdam-p5cfb87"></a>
    <p class="text-base font-medium text-blue-300 line-clamp-2">1 kamer van 24 m&#178;</p>
    <p class="truncate text-sm text-grey-400">Van Leijenberghlaan 125, 1082 GD Amsterdam, Netherlands</p>
    <p class="text-base font-bold text-blue-300">&euro;880 / maand</p>
  </div>
  <div class="relative flex overflow-hidden rounded-xl border border-grey-300 bg-white xl:hidden">
    <a class="absolute inset-0 z-1" href="/listings/parkeerplaats-centrum-p999999"></a>
    <p class="text-base font-medium text-blue-300 line-clamp-2">Parkeerplaats in centrum</p>
    <p class="truncate text-sm text-grey-400">Damrak 1, 1012 LG Amsterdam, Netherlands</p>
    <p class="text-base font-bold text-blue-300">&euro;250 / maand</p>
  </div>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> RentolaSource:
    return RentolaSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_rentola_parseert_kaartvelden():
    """Prijs, url, plaats, adres, oppervlak en slaapkamers uit de kaart."""
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)

    # 2 woningen: appartement + kamer; dubbele kaartvariant ontdubbeld,
    # parkeerplaats overgeslagen.
    assert len(woningen) == 2

    app = woningen[0]
    assert app.prijs == 929
    assert app.url == "https://rentola.nl/listings/apartment-at-quellijnstraat-90-1a-1072xx-amsterdam-p42abc6"
    assert app.plaats == "Amsterdam"
    assert app.postcode == "1072 XX"
    assert app.adres == "Quellijnstraat 90-1A"
    assert app.oppervlak_m2 == 32
    assert app.slaapkamers == 2
    assert app.gedeelde_voorzieningen is False
    assert app.afbeelding_url == "https://img2.rentola.com/foto.jpg"
    assert app.type == "huur"
    assert app.bron == "rentola"


def test_rentola_kamer_is_gedeeld():
    """Een losse kamer krijgt gedeelde_voorzieningen=True."""
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    kamer = woningen[1]
    assert kamer.prijs == 880
    assert kamer.gedeelde_voorzieningen is True
    assert kamer.slaapkamers == 1


def test_rentola_404_op_vervolgpagina_behoudt_eerdere_resultaten():
    """Een 404 op pagina 2 betekent 'einde paginering', geen bronfout."""
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
    assert woningen[0].prijs == 929
