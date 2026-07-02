"""Tests voor de vb&t-bron: parser op echte kaartstructuur, zonder netwerk."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.vbt import VbtSource

CONFIG = load_config()

# Klein fragment, gebaseerd op de echte kaartstructuur van vbtverhuurmakelaars.nl.
PAGINA_1_HTML = """
<html><body>
  <a href="/woning/rotterdam-hanoistraat-171" class="property svelte-16bhc06">
    <div class="visual">
      <div class="visimage" style="background-image: url(/images/824dfb-w300-s-fwj/hanoistraat-171)"></div>
      <span class="status option">Aangeboden</span>
    </div>
    <div class="items"><div>Rotterdam</div><span class="normal">Hanoistraat 171</span><div class="price">&euro; 1.493,-</div>
      <table>
        <tr><td>Soort object</td><td>Appartement</td></tr>
        <tr><td>Woonoppervlakte</td><td>74 m&#178;</td></tr>
        <tr><td>Kamers</td><td>3 Kamers</td></tr>
        <tr><td>Servicekosten</td><td>&euro; 90,- per maand</td></tr>
        <tr><td>Beschikbaar</td><td>1 augustus 2026</td></tr>
      </table>
    </div>
  </a>
  <a href="/woning/eindhoven-parkeergarage-1" class="property svelte-16bhc06">
    <div class="items"><div>Eindhoven</div><span class="normal">Parkeergarage 1</span><div class="price">&euro; 95,-</div>
      <table>
        <tr><td>Soort object</td><td>Parkeerplaats</td></tr>
      </table>
    </div>
  </a>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> VbtSource:
    return VbtSource(CONFIG, {"max_paginas": max_paginas})


def test_vbt_parseert_kaart_en_slaat_parkeerplaats_over():
    bron = _bron()
    woningen = bron._parse_lijst(PAGINA_1_HTML)
    assert len(woningen) == 1
    w = woningen[0]
    assert w.prijs == 1493
    assert w.plaats == "Rotterdam"
    assert w.adres == "Hanoistraat 171"
    assert w.url == "https://vbtverhuurmakelaars.nl/woning/rotterdam-hanoistraat-171"
    assert w.oppervlak_m2 == 74
    assert w.slaapkamers == 2          # 3 kamers incl. woonkamer
    assert w.servicekosten == 90
    assert w.type == "huur"
    assert w.bron == "vbt"
    assert w.gedeelde_voorzieningen is False
    assert w.afbeelding_url.startswith("https://vbtverhuurmakelaars.nl/images/")


def test_vbt_404_op_vervolgpagina_behoudt_eerdere_resultaten():
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
    assert woningen[0].prijs == 1493


def test_vbt_andere_fout_blijft_fout():
    """Serverfouten (500) zijn wel echte fouten en moeten omhoog borrelen."""
    bron = _bron()

    def nep_get(url, **kwargs):
        raise _http_error(500)

    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()


def test_vbt_respecteert_max_paginas():
    bron = _bron(max_paginas=2)
    opgevraagd = []

    def nep_get(url, **kwargs):
        opgevraagd.append(url)
        return Mock(text=PAGINA_1_HTML)

    bron.get = nep_get
    bron.haal_op()
    assert opgevraagd == [
        "https://vbtverhuurmakelaars.nl/woningen",
        "https://vbtverhuurmakelaars.nl/woningen/2",
    ]
