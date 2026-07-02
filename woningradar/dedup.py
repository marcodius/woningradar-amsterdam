"""Ontdubbeling van woningen die op meerdere bronnen voorkomen."""
from __future__ import annotations

from typing import List

from .schema import Listing, _dedup_sleutel


def dedup(listings: List[Listing]) -> List[Listing]:
    """
    Houd per unieke woning één advertentie over. Bij dubbelen wint de
    advertentie met de meeste ingevulde velden (meest complete bron).
    De url's van de andere bronnen worden bewaard in .waarschuwingen niet,
    maar het aantal bronnen wordt genoteerd op het object (attribuut bronnen_extra).
    """
    per_sleutel: dict[str, Listing] = {}
    for l in listings:
        sleutel = _dedup_sleutel(l)
        bestaand = per_sleutel.get(sleutel)
        if bestaand is None:
            per_sleutel[sleutel] = l
        else:
            # Kies de meest complete; noteer extra bron.
            winnaar = _meest_compleet(bestaand, l)
            verliezer = l if winnaar is bestaand else bestaand
            extra = getattr(winnaar, "ook_op", []) or []
            if verliezer.bron and verliezer.bron != winnaar.bron:
                extra = list({*extra, verliezer.bron})
            setattr(winnaar, "ook_op", extra)
            per_sleutel[sleutel] = winnaar
    return list(per_sleutel.values())


def _ingevuld(l: Listing) -> int:
    velden = (
        l.prijs, l.servicekosten, l.slaapkamers, l.oppervlak_m2,
        l.energielabel, l.buurt, l.adres, l.postcode, l.erfpacht,
        l.datum_geplaatst,
    )
    return sum(1 for v in velden if v not in (None, "", False))


def _meest_compleet(a: Listing, b: Listing) -> Listing:
    return a if _ingevuld(a) >= _ingevuld(b) else b
