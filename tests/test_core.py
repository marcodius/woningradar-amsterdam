"""Basistests voor scoring, harde filters en de koopberekening."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from woningradar.config import load_config
from woningradar.mortgage import annuiteit_maandlast, bereken_koop_maandlast
from woningradar.scoring import harde_filters, score_listing
from woningradar.schema import Listing

CONFIG = load_config()


def test_annuiteit_bekende_waarde():
    # 300.000 bij 4,1% over 30 jaar -> ongeveer 1.450 per maand.
    ml = annuiteit_maandlast(300_000, 0.041, 30)
    assert 1400 < ml < 1500


def test_huur_boven_budget_afgewezen():
    w = Listing(titel="Duur", type="huur", prijs=2100, slaapkamers=1,
                plaats="Amsterdam", vrije_sector_bevestigd=True)
    redenen = harde_filters(w, CONFIG)
    assert any("boven grens" in r for r in redenen)


def test_studio_zonder_slaapkamer_afgewezen():
    w = Listing(titel="Studio", type="huur", prijs=1200, slaapkamers=0,
                plaats="Amsterdam")
    redenen = harde_filters(w, CONFIG)
    assert any("slaapkamer" in r for r in redenen)


def test_gedeelde_voorzieningen_afgewezen():
    w = Listing(titel="Kamer", type="huur", prijs=900, slaapkamers=1,
                plaats="Amsterdam", gedeelde_voorzieningen=True)
    redenen = harde_filters(w, CONFIG)
    assert any("Gedeelde" in r for r in redenen)


def test_locatie_buiten_regio_afgewezen():
    w = Listing(titel="Ver weg", type="huur", prijs=1400, slaapkamers=1,
                plaats="Groningen")
    redenen = harde_filters(w, CONFIG)
    assert any("Locatie" in r for r in redenen)


def test_goede_huurwoning_wordt_topmatch():
    w = Listing(titel="Mooi appartement met balkon nabij station", type="huur",
                prijs=1450, slaapkamers=2, oppervlak_m2=75, buitenruimte=True,
                buitenruimte_soort="balkon", energielabel="A", buurt="Amstel",
                plaats="Amsterdam", vrije_sector_bevestigd=True)
    score_listing(w, CONFIG)
    assert w.indeling == "topmatch"
    assert w.score >= 8
    assert w.redenen  # er zijn redenen ingevuld


def test_koop_maandlast_te_hoog_afgewezen():
    w = Listing(titel="Dure koop", type="koop", prijs=450_000, slaapkamers=2,
                plaats="Amsterdam", erfpacht="afgekocht")
    score_listing(w, CONFIG)
    assert w.maandlast_koop > 1500
    assert w.indeling == "afgewezen"


def test_koop_binnen_budget_ok():
    w = Listing(titel="Betaalbare koop", type="koop", prijs=300_000, slaapkamers=2,
                oppervlak_m2=68, energielabel="B", buurt="Watergraafsmeer",
                plaats="Amsterdam", erfpacht="eeuwigdurend afgekocht")
    score_listing(w, CONFIG)
    assert w.maandlast_koop <= 1500
    assert w.indeling in ("topmatch", "lage_match")


def test_erfpachtcanon_verhoogt_maandlast():
    w = Listing(titel="Koop met canon", type="koop", prijs=285_000,
                erfpacht="lopende canon", erfpacht_canon_per_jaar=1800,
                plaats="Amsterdam")
    bereken_koop_maandlast(w, CONFIG)
    zonder = annuiteit_maandlast(285_000, CONFIG["hypotheek"]["rente_jaarlijks"], 30)
    assert w.maandlast_koop > zonder  # canon telt mee


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
