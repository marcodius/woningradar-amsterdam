"""Pararius scraper (best-effort).

BELANGRIJK: Pararius verbiedt scrapen in de gebruiksvoorwaarden en blokkeert
bots actief. Deze module staat standaard UIT in config.yaml. Zet hem alleen
aan als je zeker weet dat je gebruik is toegestaan (bijvoorbeeld via een
officiele afspraak of feed). Bij een 403/429 wordt de bron netjes overgeslagen.

Voor JavaScript-zware pagina's is 'requests' vaak niet genoeg; overweeg dan de
Playwright-variant (zie README) via een eigen subklasse.
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..schema import (
    Listing,
    detecteer_buitenruimte,
    parse_energielabel,
    parse_oppervlak,
    parse_prijs,
)
from .base import BaseSource


class ParariusSource(BaseSource):
    naam = "pararius"
    basis_url = "https://www.pararius.nl"

    def _zoek_url(self, pagina: int) -> str:
        max_huur = self.config["criteria"]["huur_max_kaal"]
        return f"{self.basis_url}/huurwoningen/amsterdam/0-{max_huur}/page-{pagina}"

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 2)
        for pagina in range(1, max_paginas + 1):
            resp = self.get(self._zoek_url(pagina))
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
        kaarten = soup.select("section.listing-search-item")
        woningen: List[Listing] = []
        for kaart in kaarten:
            try:
                w = self._parse_kaart(kaart)
                if w:
                    woningen.append(w)
            except Exception:
                continue
        return woningen

    def _parse_kaart(self, kaart) -> Listing | None:
        titel_el = kaart.select_one(".listing-search-item__title a")
        if not titel_el:
            return None
        titel = titel_el.get_text(strip=True)
        url = urljoin(self.basis_url, titel_el.get("href", ""))

        prijs_el = kaart.select_one(".listing-search-item__price")
        prijs = parse_prijs(prijs_el.get_text() if prijs_el else None)

        loc_el = kaart.select_one(".listing-search-item__sub-title")
        loc = loc_el.get_text(" ", strip=True) if loc_el else ""
        postcode = None
        m = re.search(r"\b(\d{4}\s?[A-Z]{2})\b", loc)
        if m:
            postcode = m.group(1)
        buurt = None
        b = re.search(r"\(([^)]+)\)", loc)
        if b:
            buurt = b.group(1)

        kenmerken = kaart.get_text(" ", strip=True)
        buiten, soort = detecteer_buitenruimte(kenmerken)
        slaapkamers = None
        sk = re.search(r"(\d+)\s*(slaapkamer|kamers?)", kenmerken, re.I)
        if sk:
            aantal = int(sk.group(1))
            slaapkamers = aantal - 1 if "slaapkamer" not in sk.group(2).lower() else aantal

        img = kaart.select_one("img")
        afbeelding = None
        if img:
            for attr in ("src", "data-src", "data-lazy"):
                waarde = img.get(attr)
                if waarde and waarde.startswith("http"):
                    afbeelding = waarde
                    break

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=parse_oppervlak(kenmerken),
            buitenruimte=buiten,
            buitenruimte_soort=soort,
            energielabel=parse_energielabel(kenmerken),
            buurt=buurt or "Amsterdam",
            plaats="Amsterdam",
            postcode=postcode,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=url,
        )
