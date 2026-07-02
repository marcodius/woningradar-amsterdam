"""Huurwoningen.com scraper.

LET OP: dit is bewust het .com-domein. Huurwoningen.NL zit achter Cloudflare
en blokkeert datacenter-IP's; het .com-domein serveert dezelfde (Pararius-
achtige) server-gerenderde lijstpagina's zonder blokkade.

Lijstpagina: https://www.huurwoningen.com/in/amsterdam/ (paginering: ?page=N)
Detail-links: /huren/<stad>/<id>/<slug>/

Elke woningkaart is een <section class="listing-search-item"> met daarin:
- titel (bv. "Appartement Krijn Taconiskade") met type + straat
- sub-title: "1087 HW Amsterdam (IJburg-Zuid)" -> postcode, plaats, buurt
- prijs: __price-main, of bij prijstransparantie __price-bare (kale huur)
- features: oppervlak (m²) en aantal kamers
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

# Types waarbij we gedeelde voorzieningen aannemen (kamers).
GEDEELDE_TYPES = ("kamer",)
# Niet-woningen: overslaan.
OVERSLAAN_TYPES = ("parkeerplaats", "garage", "garagebox", "berging", "opslag")


class HuurwoningenComSource(BaseSource):
    naam = "huurwoningencom"
    basis_url = "https://www.huurwoningen.com"

    def _steden(self) -> List[str]:
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        gezien: set = set()
        max_paginas = self.bron_conf.get("max_paginas", 2)
        pmax = self.prijs_max()
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                # Prijsband in de URL (geverifieerd werkend) concentreert het
                # paginabudget op betaalbare woningen i.p.v. dure appartementen.
                params = []
                if pmax:
                    params.append(f"price=0-{pmax}")
                if pagina > 1:
                    params.append(f"page={pagina}")
                url = f"{self.basis_url}/in/{stad}/"
                if params:
                    url += "?" + "&".join(params)
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # 404 op een vervolgpagina = einde paginering, geen fout.
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                if resp is None:
                    break
                woningen = self._parse_lijst(resp.text)
                # Voorbij de laatste pagina redirect de site (307) naar pagina 1;
                # requests volgt dat stilletjes. Alleen nieuwe URL's tellen dus
                # mee, en een pagina zonder nieuwe woningen = einde paginering.
                nieuw = [w for w in woningen if w.url not in gezien]
                if not nieuw:
                    break
                gezien.update(w.url for w in nieuw)
                resultaat.extend(nieuw)
                if len(resultaat) >= self.max_woningen:
                    break
        return resultaat[: self.max_woningen]

    def _parse_lijst(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        gezien: set = set()
        for kaart in soup.select("section.listing-search-item"):
            try:
                woning = self._parse_kaart(kaart)
            except Exception:
                continue
            if woning is None or woning.url in gezien:
                continue
            gezien.add(woning.url)
            woningen.append(woning)
        return woningen

    def _parse_kaart(self, kaart) -> Optional[Listing]:
        titel_link = kaart.select_one("a.listing-search-item__link--title")
        if titel_link is None:
            return None
        titel = titel_link.get_text(strip=True)
        href = titel_link.get("href", "")
        if not titel or not href:
            return None

        # Parkeerplaatsen/garages e.d. zijn geen woningen.
        titel_l = titel.lower()
        if any(t in titel_l for t in OVERSLAAN_TYPES):
            return None

        # Sub-title: "1087 HW Amsterdam (IJburg-Zuid)" of "Amsterdam (Centrum)".
        postcode = None
        plaats = None
        buurt = None
        sub = kaart.select_one(".listing-search-item__sub-title")
        if sub:
            sub_tekst = sub.get_text(" ", strip=True)
            m = re.match(
                r"(?:(\d{4}\s?[A-Z]{2})\s+)?([^(]+?)(?:\s*\(([^)]+)\))?\s*$",
                sub_tekst,
            )
            if m:
                postcode = m.group(1)
                plaats = m.group(2).strip() or None
                buurt = m.group(3)

        # Prijs: bij prijstransparantie staat de kale huur in __price-bare,
        # anders in __price-main. Nooit de "Totale huurprijs" pakken.
        prijs = None
        prijs_el = kaart.select_one(
            ".listing-search-item__price-bare"
        ) or kaart.select_one(".listing-search-item__price-main")
        if prijs_el:
            m_prijs = re.search(r"€\s*[\d.,]+", prijs_el.get_text(" ", strip=True))
            if m_prijs:
                prijs = parse_prijs(m_prijs.group(0))

        # Kenmerken: oppervlak en kamers.
        oppervlak = None
        slaapkamers = None
        opp_el = kaart.select_one(".illustrated-features__item--surface-area")
        if opp_el:
            m_opp = re.search(r"(\d+)\s*m", opp_el.get_text(strip=True))
            if m_opp:
                oppervlak = int(m_opp.group(1))
        kamers_el = kaart.select_one(".illustrated-features__item--number-of-rooms")
        if kamers_el:
            m_kamers = re.search(r"(\d+)\s*kamer", kamers_el.get_text(strip=True), re.I)
            if m_kamers:
                kamers = int(m_kamers.group(1))
                slaapkamers = max(kamers - 1, 0)   # kamers = incl. woonkamer

        # Afbeelding uit de kaart (eerste echte http-src).
        afbeelding = None
        img = kaart.select_one("img.picture__image") or kaart.find("img")
        if img:
            for attr in ("data-src", "src"):
                waarde = img.get(attr)
                if waarde and waarde.startswith("http"):
                    afbeelding = waarde
                    break

        gedeeld = any(t in titel_l for t in GEDEELDE_TYPES)

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            buurt=buurt or plaats,
            plaats=plaats,
            postcode=postcode,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
