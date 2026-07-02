"""Koopberekening: bruto maandlast via een annuiteitenhypotheek."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .schema import Listing


def annuiteit_maandlast(hoofdsom: float, jaarrente: float, jaren: int) -> float:
    """Bruto maandlast van een annuiteitenhypotheek."""
    if hoofdsom <= 0:
        return 0.0
    n = jaren * 12
    r = jaarrente / 12
    if r == 0:
        return hoofdsom / n
    return hoofdsom * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def bereken_koop_maandlast(listing: Listing, config: Dict[str, Any]) -> Optional[int]:
    """
    Vul listing.maandlast_koop met de bruto maandlast (hypotheek + erfpachtcanon).
    Geeft None terug als er geen prijs bekend is.
    """
    if listing.type != "koop" or not listing.prijs:
        return None

    hyp = config["hypotheek"]
    maandlast = annuiteit_maandlast(
        hoofdsom=listing.prijs,
        jaarrente=hyp["rente_jaarlijks"],
        jaren=hyp["looptijd_jaren"],
    )
    # Erfpachtcanon (per jaar) omrekenen naar per maand en optellen.
    if listing.erfpacht_canon_per_jaar:
        maandlast += listing.erfpacht_canon_per_jaar / 12

    listing.maandlast_koop = int(round(maandlast))
    listing.maandlast_aanname = hyp.get("aanname_tekst")
    return listing.maandlast_koop
