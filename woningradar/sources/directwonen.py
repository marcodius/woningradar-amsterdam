"""DirectWonen scraper.

DirectWonen is een landelijk verhuurplatform met server-gerenderde
lijstpagina's. De kaarten staan als `a.inner-content` met daarin een
`.new-search-advert`-blok met type, prijs, adres+plaats, kamers en m².

Lijstpagina: https://directwonen.nl/huurwoningen-huren/<stad>
Paginering:  ?pageno=N (pager onderaan; niet-bestaande pagina = einde)

Let op: veel kaartlinks zijn "premium"-links naar /premiumaccountpayment
met de echte detail-URL in de returnUrl-querystring; die pakken we uit,
zodat de listing altijd naar de echte woningpagina wijst.
Detail-URL: /huurwoningen-huren/<stad>/<straat-slug>/<type>-<id>
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

OVERSLAAN_TYPES = ["garage", "garagebox", "parkeerplaats", "parkeren", "berging"]


class DirectwonenSource(BaseSource):
    naam = "directwonen"
    basis_url = "https://directwonen.nl"

    def _steden(self) -> List[str]:
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 2)
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                url = f"{self.basis_url}/huurwoningen-huren/{stad}"
                if pagina > 1:
                    url += f"?pageno={pagina}"
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # 404 op een vervolgpagina = einde van de paginering
                    # voor deze stad, geen bronfout.
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                if resp is None:
                    break
                woningen = self._parse_lijst(resp.text)
                if not woningen:
                    break
                resultaat.extend(woningen)
                if len(resultaat) >= self.max_woningen:
                    break
        return resultaat[: self.max_woningen]

    def _parse_lijst(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        gezien: set[str] = set()
        for link in soup.select("a.inner-content"):
            kaart = link.select_one(".new-search-advert")
            if kaart is None:
                continue  # promo-tegel zonder woningdata
            href = self._echte_url(link.get("href", ""))
            if not href or href in gezien:
                continue
            gezien.add(href)
            try:
                woning = self._parse_kaart(href, kaart)
                if woning:
                    woningen.append(woning)
            except Exception:
                continue
        return woningen

    def _echte_url(self, href: str) -> Optional[str]:
        """Premium-links (/premiumaccountpayment?returnUrl=...) uitpakken."""
        if not href:
            return None
        if "premiumaccountpayment" in href:
            query = parse_qs(urlparse(href).query)
            terug = query.get("returnUrl", [None])[0]
            return terug
        if "hoe-werkt-het" in href:
            return None
        return urljoin(self.basis_url, href)

    def _parse_kaart(self, url: str, kaart) -> Optional[Listing]:
        # Type staat in de kaartkop (Appartement / Kamer / Woning / Studio).
        kop = kaart.select_one(".advert-location-header")
        woning_type = kop.get_text(strip=True) if kop else None
        tekst_l = (woning_type or "").lower()
        if any(t in tekst_l for t in OVERSLAAN_TYPES):
            return None

        # Prijs: "€ 8895" in .advert-location-price.
        prijs = None
        prijs_el = kaart.select_one(".advert-location-price")
        if prijs_el:
            prijs = parse_prijs(prijs_el.get_text(strip=True))

        # Adres + plaats: "O. Nassaulaan, Amsterdam" in h3.location-text.
        adres = plaats = None
        loc = kaart.select_one(".location-text")
        if loc:
            loc_tekst = loc.get_text(" ", strip=True)
            delen = [d.strip() for d in loc_tekst.split(",")]
            if len(delen) >= 2:
                adres, plaats = delen[0], delen[-1]
            elif delen:
                adres = delen[0]

        # Kamers en oppervlak uit de kleine banners.
        kamers = self._banner_getal(kaart, "rooms")
        slaapkamers = max(kamers - 1, 0) if kamers is not None else None
        oppervlak = self._banner_getal(kaart, "surface")

        # Afbeelding uit de thumbnail.
        afbeelding = None
        img = kaart.select_one(".advert-thumbnail img")
        if img:
            src = img.get("src") or img.get("data-src")
            if src and src.startswith("http"):
                afbeelding = src

        titel = f"{woning_type or 'Huurwoning'} {adres}".strip() if adres else (woning_type or "Huurwoning")
        gedeeld = woning_type is not None and "kamer" in woning_type.lower()

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            buurt=plaats,
            plaats=plaats,
            adres=adres,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=url,
        )

    @staticmethod
    def _banner_getal(kaart, soort: str) -> Optional[int]:
        """Getal uit een .small-banner.<soort> (rooms/surface)."""
        el = kaart.select_one(f".small-banner.{soort} .small-banner-top")
        if el is None:
            return None
        m = re.search(r"\d+", el.get_text(strip=True))
        return int(m.group()) if m else None
