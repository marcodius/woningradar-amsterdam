"""Kamernet scraper.

Kamernet is primair een kamerplatform, maar er staan ook zelfstandige
appartementen en studio's tussen — dat is de waardevolle vangst. Kamers
markeren we met gedeelde_voorzieningen=True zodat de harde filters ze
afwijzen; anti-kraak krijgt tijdelijk_contract=True.

De site is een Next.js-app: alle listingdata zit server-side gerenderd in
het <script id="__NEXT_DATA__">-blok als JSON. Dat is veel robuuster dan
HTML-kaarten parsen, dus we lezen die JSON.

Lijstpagina: https://kamernet.nl/huren/huurwoningen-amsterdam?pageNo=N
Detail-links: /huren/<typeslug>-<stad>/<straatslug>/<typeslug>-<listingId>

Paginering: ?pageNo=N geeft altijd HTTP 200; voorbij de laatste pagina is
de listings-lijst gewoon leeg. Een lege pagina (of een 404) is dus het
einde van de paginering, geen bronfout.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

import requests

from ..schema import Listing
from .base import BaseSource

# listingType uit de Kamernet-JSON -> (url-slug, weergavenaam).
# Geverifieerd tegen de detail-links op de lijstpagina.
LISTING_TYPES = {
    1: ("kamer", "Kamer"),
    2: ("appartement", "Appartement"),
    4: ("studio", "Studio"),
    8: ("anti-kraak", "Anti-kraak"),
}

# Items die we nooit willen (Kamernet heeft ze zelden, maar wees robuust).
OVERSLAAN_WOORDEN = ("parkeer", "garage", "parking")

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class KamernetSource(BaseSource):
    naam = "kamernet"
    basis_url = "https://kamernet.nl"

    def _steden(self) -> List[str]:
        # Stads-slug in de lijst-URL; de Amsterdam-pagina toont ook omgeving.
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        gezien: set[str] = set()
        max_paginas = self.bron_conf.get("max_paginas", 2)
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                url = f"{self.basis_url}/huren/huurwoningen-{stad}"
                if pagina > 1:
                    url += f"?pageNo={pagina}"
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # 404 = geen (volgende) pagina; einde paginering.
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                if resp is None:
                    break
                woningen = self._parse_lijst(resp.text)
                if not woningen:
                    # Voorbij de laatste pagina is de listings-lijst leeg.
                    break
                for woning in woningen:
                    if woning.url in gezien:
                        continue  # top-ads herhalen zich over pagina's heen
                    gezien.add(woning.url)
                    resultaat.append(woning)
                if len(resultaat) >= self.max_woningen:
                    break
        return resultaat[: self.max_woningen]

    def _parse_lijst(self, html: str) -> List[Listing]:
        """Lees de listings uit het __NEXT_DATA__ JSON-blok."""
        m = NEXT_DATA_RE.search(html)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except (ValueError, TypeError):
            return []
        try:
            antwoord = (
                data["props"]["pageProps"]["targetPageProps"]["findListingsResponse"]
            )
        except (KeyError, TypeError):
            return []
        if not isinstance(antwoord, dict):
            return []

        ruwe: List[dict] = []
        for sleutel in ("listings", "topAdListings"):
            deel = antwoord.get(sleutel)
            if isinstance(deel, list):
                ruwe.extend(d for d in deel if isinstance(d, dict))

        woningen: List[Listing] = []
        gezien: set = set()
        for item in ruwe:
            try:
                woning = self._parse_item(item)
            except Exception:
                continue
            if woning is None or woning.url in gezien:
                continue
            gezien.add(woning.url)
            woningen.append(woning)
        return woningen

    def _parse_item(self, item: dict) -> Optional[Listing]:
        listing_id = item.get("listingId")
        type_info = LISTING_TYPES.get(item.get("listingType"))
        if not listing_id or type_info is None:
            return None  # onbekend type: liever overslaan dan gokken
        type_slug, type_naam = type_info

        straat = (item.get("street") or "").strip()
        plaats = (item.get("city") or "").strip() or None

        # Parkeerplaatsen/garages nooit meenemen.
        tekst = f"{straat} {type_naam}".lower()
        if any(w in tekst for w in OVERSLAAN_WOORDEN):
            return None

        # Detail-URL: /huren/<typeslug>-<stad>/<straatslug>/<typeslug>-<id>
        stad_slug = item.get("citySlug") or (plaats or "").lower().replace(" ", "-")
        straat_slug = item.get("streetSlug") or "onbekend"
        url = (
            f"{self.basis_url}/huren/{type_slug}-{stad_slug}/"
            f"{straat_slug}/{type_slug}-{listing_id}"
        )

        prijs = item.get("totalRentalPrice")
        prijs = int(prijs) if isinstance(prijs, (int, float)) and prijs > 0 else None

        oppervlak = item.get("surfaceArea")
        oppervlak = int(oppervlak) if isinstance(oppervlak, (int, float)) and oppervlak > 0 else None

        # Kamers zijn per definitie gedeeld wonen; bij anti-kraak weten we het
        # niet zeker maar is het contract sowieso tijdelijk.
        gedeeld = type_slug == "kamer"
        tijdelijk = type_slug == "anti-kraak" or bool(item.get("availabilityEndDate"))

        afbeelding = (
            item.get("resizedFullPreviewImageUrl")
            or item.get("fullPreviewImageUrl")
            or item.get("thumbnailUrl")
        )
        if afbeelding and not str(afbeelding).startswith("http"):
            afbeelding = None

        titel = f"{type_naam} {straat}".strip() if straat else type_naam

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            tijdelijk_contract=tijdelijk,
            plaats=plaats,
            adres=straat or None,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=url,
        )
