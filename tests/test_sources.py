"""Tests voor bron-robuustheid: pagination-fouten en de lege-oogst-wachter."""
import os
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.sources.nederwoon import NederwoonSource

CONFIG = load_config()

PAGINA_1_HTML = """
<html><body>
  <div class="kaart">
    <a href="/huurwoning/amsterdam/12345/appartement-teststraat">Teststraat 1</a>
    <p>Appartement 1012AB Amsterdam 60 m2 Woonoppervlakte 3 kamers &euro; 1.500,00 Kale huur</p>
  </div>
</body></html>
"""


def _http_error(status: int) -> requests.HTTPError:
    resp = Mock(spec=requests.Response)
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


def _bron(max_paginas: int = 3) -> NederwoonSource:
    return NederwoonSource(CONFIG, {"max_paginas": max_paginas, "steden": ["amsterdam"]})


def test_nederwoon_404_op_vervolgpagina_behoudt_eerdere_resultaten():
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
    assert woningen[0].prijs == 1500


def test_nederwoon_404_op_eerste_pagina_gaat_door_naar_volgende_stad():
    """Een stad zonder pagina mag de andere steden niet blokkeren."""
    bron = NederwoonSource(CONFIG, {"max_paginas": 1, "steden": ["nergenshuizen", "amsterdam"]})
    antwoorden = [_http_error(404), Mock(text=PAGINA_1_HTML)]

    def nep_get(url, **kwargs):
        antwoord = antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord

    bron.get = nep_get
    woningen = bron.haal_op()
    assert len(woningen) == 1


def test_nederwoon_andere_fout_blijft_fout():
    """Serverfouten (500) zijn wel echte fouten en moeten omhoog borrelen."""
    bron = _bron()
    def nep_get(url, **kwargs):
        raise _http_error(500)
    bron.get = nep_get
    with pytest.raises(requests.HTTPError):
        bron.haal_op()


def test_lege_oogst_faalt_de_run():
    """0 woningen mag nooit stilletjes een lege site publiceren."""
    from woningradar.run import controleer_opbrengst
    with pytest.raises(SystemExit):
        controleer_opbrengst(0, {"nederwoon": "fout: 404"})


def test_niet_lege_oogst_faalt_niet():
    from woningradar.run import controleer_opbrengst
    controleer_opbrengst(3, {"nederwoon": "ok (3)"})
