"""Huurwoningen.nl scraper (best-effort, met BeautifulSoup).

Let op: opmaak van woningsites verandert regelmatig. Deze selectors kunnen
verouderen en vragen dan onderhoud. Bij een blokkade of parsefout wordt de
bron netjes overgeslagen zodat de radar blijft werken.
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
    parse_int,
    parse_oppervlak,
    parse_prijs,
)
from .base import BaseSource


class HuurwoningenSource(BaseSource):
    naam = "huurwoningen"
    basis_url = "https://www.huurwoningen.nl"

    # Zoekpad voor huurwoningen in Amsterdam tot de budgetgrens.
    def _zoek_url(self, pagina: int) -> str:
        max_huur = self.config["criteria"]["huur_max_kaal"]
        return (
            f"{self.basis_url}/in/amsterdam/"
            f"?price=0-{max_huur}&page={pagina}"
        )

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
        kaarten = soup.select("section.listing-search-item, li.search-list__item")
        woningen: List[Listing] = []
        for kaart in kaarten:
            try:
                woning = self._parse_kaart(kaart)
                if woning:
                    woningen.append(woning)
            except Exception:
                # Sla een kapotte kaart over, laat de rest doorgaan.
                continue
        return woningen

    def _parse_kaart(self, kaart) -> Listing | None:
        link = kaart.select_one("a[href]")
        if not link:
            return None
        url = urljoin(self.basis_url, link.get("href", ""))

        titel_el = kaart.select_one(
            ".listing-search-item__title, .search-list-item__title, h2, h3"
        )
        titel = titel_el.get_text(strip=True) if titel_el else "Huurwoning"

        prijs_el = kaart.select_one(
            ".listing-search-item__price, .search-list-item__price, [class*=price]"
        )
        prijs = parse_prijs(prijs_el.get_text() if prijs_el else None)

        sub_el = kaart.select_one(
            ".listing-search-item__sub-title, .search-list-item__sub-title, [class*=location]"
        )
        subtekst = sub_el.get_text(" ", strip=True) if sub_el else ""
        buurt, postcode = self._parse_locatie(subtekst)

        # Kenmerken (oppervlak, kamers) staan vaak in een lijstje.
        kenmerk_tekst = kaart.get_text(" ", strip=True)
        oppervlak = self._zoek_oppervlak(kenmerk_tekst)
        slaapkamers = self._zoek_slaapkamers(kenmerk_tekst)
        buiten, soort = detecteer_buitenruimte(kenmerk_tekst)
        afbeelding = self._zoek_afbeelding(kaart)

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            buitenruimte=buiten,
            buitenruimte_soort=soort,
            energielabel=parse_energielabel(kenmerk_tekst),
            buurt=buurt or "Amsterdam",
            plaats="Amsterdam",
            postcode=postcode,
            vrije_sector_bevestigd=None,   # onbekend vanaf de lijstpagina
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=url,
        )

    @staticmethod
    def _zoek_afbeelding(kaart) -> str | None:
        img = kaart.select_one("img")
        if not img:
            return None
        # Lazy-loaded afbeeldingen staan vaak in data-src / srcset.
        for attr in ("src", "data-src", "data-lazy", "data-original"):
            waarde = img.get(attr)
            if waarde and waarde.startswith("http"):
                return waarde
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            eerste = srcset.split(",")[0].strip().split(" ")[0]
            if eerste.startswith("http"):
                return eerste
        return None

    @staticmethod
    def _parse_locatie(tekst: str):
        # Voorbeeld: "1091 AB Amsterdam (Oosterparkbuurt)"
        postcode = None
        m = re.search(r"\b(\d{4}\s?[A-Z]{2})\b", tekst)
        if m:
            postcode = m.group(1)
        buurt = None
        b = re.search(r"\(([^)]+)\)", tekst)
        if b:
            buurt = b.group(1)
        return buurt, postcode

    @staticmethod
    def _zoek_oppervlak(tekst: str):
        m = re.search(r"(\d+)\s*m", tekst)
        return parse_oppervlak(m.group(0)) if m else None

    @staticmethod
    def _zoek_slaapkamers(tekst: str):
        m = re.search(r"(\d+)\s*(slaapkamer|kamers?)", tekst, re.I)
        if not m:
            return None
        aantal = parse_int(m.group(1))
        # "3 kamers" betekent doorgaans woonkamer + 2 slaapkamers.
        if "slaapkamer" not in m.group(2).lower() and aantal:
            return max(aantal - 1, 0)
        return aantal
