"""Tests voor prijs-band-URL's en de sociale-huur-labeling."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.schema import Listing
from woningradar.scoring import score_listing
from woningradar.sources.huurwoningencom import HuurwoningenComSource
from woningradar.sources.rentola import RentolaSource

CONFIG = load_config()


# --- prijs_max helper -------------------------------------------------------

def test_prijs_max_valt_terug_op_budgetgrens():
    src = HuurwoningenComSource(CONFIG, {})
    assert src.prijs_max() == CONFIG["criteria"]["huur_max_kaal"]


def test_prijs_max_respecteert_override():
    src = HuurwoningenComSource(CONFIG, {"prijs_max": 1650})
    assert src.prijs_max() == 1650


def test_prijs_max_nul_schakelt_uit():
    src = HuurwoningenComSource(CONFIG, {"prijs_max": 0})
    assert src.prijs_max() is None


# --- prijs-band in de opgevraagde URL's -------------------------------------

def _vang_urls(bron, paginas=3):
    """Vervang get() zodat we de opgevraagde URL's zien en meteen stoppen."""
    urls = []

    def nep_get(url, **kwargs):
        urls.append(url)
        raise _stop()

    bron.get = nep_get
    bron.bron_conf.setdefault("max_paginas", paginas)
    try:
        bron.haal_op()
    except _stop:
        pass
    return urls


class _stop(Exception):
    pass


def test_huurwoningencom_zet_prijsband_in_url():
    bron = HuurwoningenComSource(CONFIG, {"prijs_max": 1650, "max_paginas": 1})
    urls = _vang_urls(bron)
    assert urls, "geen URL opgevraagd"
    assert "price=0-1650" in urls[0]


def test_rentola_zet_rent_max_in_url():
    bron = RentolaSource(CONFIG, {"prijs_max": 1650, "max_paginas": 1, "steden": ["amsterdam"]})
    urls = _vang_urls(bron)
    assert urls, "geen URL opgevraagd"
    assert "rent_max=1650" in urls[0]


def test_prijsband_uit_geeft_schone_url():
    bron = HuurwoningenComSource(CONFIG, {"prijs_max": 0, "max_paginas": 1})
    urls = _vang_urls(bron)
    assert "price=" not in urls[0]


# --- sociale-huur-labeling --------------------------------------------------

def _huur(prijs, oppervlak=60, **extra):
    return Listing(
        titel="Test", type="huur", prijs=prijs, oppervlak_m2=oppervlak,
        slaapkamers=2, plaats="Amsterdam", **extra,
    )


def test_lage_prijs_per_m2_wordt_gelabeld():
    # 905 / 68 = ~13 euro/m2 -> ver onder 18 -> gereguleerd
    l = score_listing(_huur(905, 68), CONFIG)
    assert l.mogelijk_gereguleerd is True
    assert any("gereguleerd" in w.lower() for w in l.waarschuwingen)


def test_normale_vrije_sector_niet_gelabeld():
    # 1500 / 62 = ~24 euro/m2 -> vrije sector
    l = score_listing(_huur(1500, 62), CONFIG)
    assert l.mogelijk_gereguleerd is False
    assert not any("gereguleerd" in w.lower() for w in l.waarschuwingen)


def test_lage_absolute_huur_zonder_oppervlak_gelabeld():
    l = score_listing(_huur(500, None), CONFIG)
    assert l.mogelijk_gereguleerd is True


def test_koop_wordt_nooit_gelabeld_als_sociale_huur():
    l = score_listing(Listing(titel="K", type="koop", prijs=300000, oppervlak_m2=50), CONFIG)
    assert l.mogelijk_gereguleerd is False
