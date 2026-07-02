"""Demobron: leest een lokale JSON-fixture. Handig om de hele keten te testen
zonder echte sites te benaderen."""
from __future__ import annotations

import json
import os
from typing import List

from ..schema import (
    Listing,
    detecteer_buitenruimte,
    parse_energielabel,
    parse_int,
    parse_oppervlak,
    parse_prijs,
)
from .base import BaseSource

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "demo_listings.json",
)


class DemoSource(BaseSource):
    naam = "demo"

    def haal_op(self) -> List[Listing]:
        with open(FIXTURE, "r", encoding="utf-8") as fh:
            ruw = json.load(fh)
        return [self._normaliseer(r) for r in ruw]

    def _normaliseer(self, r: dict) -> Listing:
        omschrijving = r.get("omschrijving", "")
        buiten, soort = detecteer_buitenruimte(
            " ".join([r.get("titel", ""), omschrijving, r.get("buitenruimte_soort", "")])
        )
        return Listing(
            titel=r.get("titel", ""),
            type=r.get("type", "huur"),
            prijs=parse_prijs(r.get("prijs")),
            servicekosten=parse_int(r.get("servicekosten")),
            slaapkamers=parse_int(r.get("slaapkamers")),
            oppervlak_m2=parse_oppervlak(r.get("oppervlak_m2")),
            buitenruimte=buiten,
            buitenruimte_soort=r.get("buitenruimte_soort") or soort,
            parkeren="parkeer" in omschrijving.lower(),
            energielabel=parse_energielabel(r.get("energielabel")),
            buurt=r.get("buurt"),
            plaats=r.get("plaats"),
            adres=r.get("adres"),
            postcode=r.get("postcode"),
            erfpacht=r.get("erfpacht"),
            erfpacht_canon_per_jaar=parse_int(r.get("erfpacht_canon_per_jaar")),
            inkomenseis=parse_int(r.get("inkomenseis")),
            tijdelijk_contract=bool(r.get("tijdelijk_contract", False)),
            gedeelde_voorzieningen=bool(r.get("gedeelde_voorzieningen", False)),
            vrije_sector_bevestigd=r.get("vrije_sector"),
            afbeelding_url=r.get("afbeelding_url"),
            bron=self.naam,
            url=r.get("url", ""),
            datum_geplaatst=r.get("datum_geplaatst"),
        )
