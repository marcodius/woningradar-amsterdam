"""Huurstunt scraper.

Huurstunt is een landelijk huurplatform met server-gerenderde lijstpagina's.

Lijstpagina:  https://www.huurstunt.nl/huren/<stad>/  (pagina 2+ = /huren/<stad>/p<N>)
Detail-links: /<type>/huren/in/<stad>/<straat>/<id>
              (type = appartement / kamer / studio / huurwoning / ...)

Elke woningkaart is een <article> met daarin: status ("Te huur"/"Verhuurd"),
straat (h3), oppervlak ("90 m2"), kamers ("3 kamers"), plaats en de prijs
("€ 2.785 /maand"). Postcode staat niet op de kaart; die blijft leeg.
De lijst bevat ook skeleton-<article>'s (laad-placeholders) zonder detail-link;
die vallen vanzelf af omdat we vanaf de detail-links werken.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

# Types (eerste URL-segment) die geen woonruimte zijn: overslaan.
OVERSLAAN_TYPES = ("parkeerplaats", "parkeren", "garage", "garagebox", "berging")


class HuurstuntSource(BaseSource):
    naam = "huurstunt"
    basis_url = "https://www.huurstunt.nl"

    def _steden(self) -> List[str]:
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 2)
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                url = f"{self.basis_url}/huren/{stad}/"
                if pagina > 1:
                    url = f"{self.basis_url}/huren/{stad}/p{pagina}"
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # Een niet-bestaande vervolgpagina geeft 404: dat is het
                    # einde van de paginering voor deze stad, geen bronfout.
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
            if len(resultaat) >= self.max_woningen:
                break
        return resultaat[: self.max_woningen]

    def _parse_lijst(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        gezien: set[str] = set()
        # Detail-links hebben altijd de vorm /<type>/huren/in/<stad>/<straat>/<id>.
        for link in soup.select('a[href*="/huren/in/"]'):
            href = link.get("href", "")
            if not href or href in gezien:
                continue
            gezien.add(href)
            try:
                kaart = link.find_parent("article")
                if kaart is None:
                    continue
                woning = self._parse_kaart(href, kaart)
                if woning:
                    woningen.append(woning)
            except Exception:
                continue
        return woningen

    def _parse_kaart(self, href: str, kaart) -> Optional[Listing]:
        # URL-delen: /<type>/huren/in/<stad>/<straat>/<id>
        delen = [d for d in urlparse(href).path.split("/") if d]
        if len(delen) < 4 or "huren" not in delen:
            return None

        woning_type = delen[0].lower()
        # Parkeerplaatsen, garages e.d. zijn geen woonruimte.
        if any(t in woning_type for t in OVERSLAAN_TYPES):
            return None

        tekst = kaart.get_text(" ", strip=True)

        # Reeds verhuurde woningen hebben geen zin om te melden.
        if "verhuurd" in tekst.lower():
            return None

        # Plaats: uit de URL (na "in/"); de kaart toont dezelfde plaatsnaam.
        plaats = None
        try:
            idx = delen.index("in")
            plaats = delen[idx + 1].replace("-", " ").title()
        except (ValueError, IndexError):
            pass

        # Titel: straatnaam uit de h3, anders uit de slug.
        kop = kaart.find("h3")
        titel = kop.get_text(strip=True) if kop else None
        if not titel:
            slug = delen[-2] if len(delen) >= 2 else ""
            titel = slug.replace("-", " ").title() or woning_type.title()

        # Oppervlak ("90 m2"), kamers ("3 kamers") en prijs ("€ 2.785 /maand").
        m_opp = re.search(r"(\d+)\s*m2?\b", tekst)
        oppervlak = int(m_opp.group(1)) if m_opp else None

        m_kamers = re.search(r"(\d+)\s*kamer", tekst, re.I)
        slaapkamers = None
        if m_kamers:
            kamers = int(m_kamers.group(1))
            slaapkamers = max(kamers - 1, 0)   # kamers = incl. woonkamer

        prijs = None
        m_prijs = re.search(r"€\s*([\d.]+)", tekst)
        if m_prijs:
            prijs = parse_prijs(m_prijs.group(0))

        # Afbeelding (skeletons hebben geen echte foto-URL).
        afbeelding = None
        img = kaart.find("img")
        if img:
            for attr in ("src", "data-src", "data-lazy", "data-original"):
                waarde = img.get(attr)
                if waarde and waarde.startswith("http"):
                    afbeelding = waarde
                    break

        gedeeld = woning_type == "kamer"

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            buurt=plaats,
            plaats=plaats,
            postcode=None,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
