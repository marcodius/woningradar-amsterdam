"""vb&t Verhuurmakelaars scraper.

vb&t is een landelijke verhuurmakelaar met veel nieuwbouwprojecten. De
lijstpagina's zijn server-gerenderd (Svelte SSR) en werken dus zonder JS.

Lijstpagina: https://vbtverhuurmakelaars.nl/woningen (pagina 1)
Paginering:  https://vbtverhuurmakelaars.nl/woningen/<n> (pad-gebaseerd);
             een niet-bestaande pagina geeft 404 = einde paginering.
Detail-links: /woning/<plaats>-<straat-slug>

Let op: het plaats-filter (?city=...) werkt alleen client-side in de
browser; de server negeert het. We halen daarom landelijk op en laten de
scoring op plaats filteren.

Per kaart (<a class="property">) staat: plaats, straat, kale huur en een
kenmerkentabel met soort object, woonoppervlak, kamers en servicekosten.
Postcode staat niet op de kaart; die laten we leeg.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

# Soorten object die geen woning zijn en overgeslagen worden.
OVERSLAAN_TYPES = ["parkeerplaats", "garage", "garagebox", "berging"]


class VbtSource(BaseSource):
    naam = "vbt"
    basis_url = "https://vbtverhuurmakelaars.nl"

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 3)
        for pagina in range(1, max_paginas + 1):
            url = f"{self.basis_url}/woningen"
            if pagina > 1:
                url += f"/{pagina}"
            try:
                resp = self.get(url)
            except requests.HTTPError as exc:
                # Een pagina voorbij het einde geeft 404: netjes stoppen.
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
        for kaart in soup.select('a.property[href^="/woning/"]'):
            href = kaart.get("href", "")
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

    @staticmethod
    def _tabel_waarde(kaart, label: str) -> Optional[str]:
        """Waarde uit de kenmerkentabel: <tr><td>label</td><td>waarde</td></tr>."""
        for rij in kaart.select("table tr"):
            cellen = rij.find_all("td")
            if len(cellen) >= 2 and label.lower() in cellen[0].get_text(strip=True).lower():
                return cellen[1].get_text(" ", strip=True)
        return None

    def _parse_kaart(self, href: str, kaart) -> Optional[Listing]:
        # Soort object; parkeerplaatsen/garages overslaan.
        soort = self._tabel_waarde(kaart, "Soort object") or ""
        if any(t in soort.lower() for t in OVERSLAAN_TYPES):
            return None

        items = kaart.select_one("div.items")
        if items is None:
            return None

        # Plaats: eerste directe <div> in .items (bv. "Rotterdam" of "'s-Gravenhage").
        plaats = None
        plaats_div = items.find("div", recursive=False)
        if plaats_div:
            plaats = plaats_div.get_text(strip=True) or None

        # Adres/titel: <span class="normal">Hanoistraat 171</span>.
        adres = None
        adres_span = items.select_one("span.normal")
        if adres_span:
            adres = adres_span.get_text(" ", strip=True) or None
        titel = adres or soort or "Huurwoning"

        # Kale huur: <div class="price">€ 1.493,-</div>.
        prijs = None
        prijs_div = items.select_one("div.price")
        if prijs_div:
            prijs = parse_prijs(prijs_div.get_text(" ", strip=True))

        # Servicekosten: "€ 90,- per maand".
        servicekosten = parse_prijs(self._tabel_waarde(kaart, "Servicekosten"))

        # Woonoppervlak: "74 m²".
        oppervlak = None
        opp_tekst = self._tabel_waarde(kaart, "Woonoppervlakte")
        if opp_tekst:
            m = re.search(r"(\d+)", opp_tekst)
            if m:
                oppervlak = int(m.group(1))

        # Kamers: "3 Kamers"; kamers = incl. woonkamer.
        slaapkamers = None
        gedeeld = False
        kamers_tekst = self._tabel_waarde(kaart, "Kamers")
        if kamers_tekst:
            m = re.search(r"(\d+)", kamers_tekst)
            if m:
                slaapkamers = max(int(m.group(1)) - 1, 0)
        if "kamer" in soort.lower():
            # Losse kamers delen voorzieningen.
            gedeeld = True

        # Afbeelding: background-image op .visimage (relatieve URL).
        afbeelding = None
        visimage = kaart.select_one(".visimage")
        if visimage:
            m = re.search(r"url\(([^)]+)\)", visimage.get("style", ""))
            if m:
                afbeelding = urljoin(self.basis_url, m.group(1).strip("'\""))

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            servicekosten=servicekosten,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            plaats=plaats,
            adres=adres,
            postcode=None,          # staat niet op de lijstkaart
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
