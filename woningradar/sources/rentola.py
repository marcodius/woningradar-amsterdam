"""Rentola scraper.

Rentola is een landelijke huurwoning-aggregator (o.a. doorplaatsingen van
Pararius-kantoren en particuliere verhuurders) met server-gerenderde
Next.js-pagina's. De kaarten staan gewoon in de HTML, dus geen JavaScript nodig.

Lijstpagina: https://rentola.nl/huren/<stad>  (paginering: ?page=N vanaf 2)
Detail-links: /listings/<slug>

Let op: de oude URL-vorm /huurwoningen?location=amsterdam stuurt door naar de
landelijke lijst /huren; de stadsfilter zit in het pad (/huren/amsterdam).
Elke woning staat twee keer in de HTML (mobiele en desktop-kaartvariant),
daarom ontdubbelen we op detail-link.

Per kaart beschikbaar: titel ("2-slaapkamer appartement van 32 m²"), adres
("Quellijnstraat 90-1A, 1072 XX Amsterdam, Netherlands") en prijs
("€929 / maand"). Dat is genoeg om te scoren.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

WONING_TYPES = ["Appartement", "Studio", "Kamer", "Huis", "Woonhuis", "Maisonnette"]
OVERSLAAN_WOORDEN = ["parkeerplaats", "parkeerplek", "garagebox", "garage te huur", "parkeergarage"]

# Adresregel op de kaart: "Straat 12-3A, 1072 XX Amsterdam, Netherlands"
ADRES_RE = re.compile(
    r"^(?P<adres>.+?),\s*(?P<postcode>\d{4}\s?[A-Z]{2})\s+(?P<plaats>.+?)(?:,\s*(?:Netherlands|Nederland|The Netherlands))?$"
)


class RentolaSource(BaseSource):
    naam = "rentola"
    basis_url = "https://rentola.nl"

    def _steden(self) -> List[str]:
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        gezien: set[str] = set()
        max_paginas = self.bron_conf.get("max_paginas", 2)
        pmax = self.prijs_max()
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                # Prijsband (rent_max) concentreert het paginabudget op
                # betaalbare woningen; scoring vangt eventuele uitschieters af.
                params = []
                if pmax:
                    params.append(f"rent_max={pmax}")
                if pagina > 1:
                    params.append(f"page={pagina}")
                url = f"{self.basis_url}/huren/{stad}"
                if params:
                    url += "?" + "&".join(params)
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # Rentola geeft 404 op pagina's voorbij het einde:
                    # dat is het einde van de paginering, geen bronfout.
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                if resp is None:
                    break
                woningen = self._parse_lijst(resp.text, gezien)
                if not woningen:
                    break
                resultaat.extend(woningen)
                if len(resultaat) >= self.max_woningen:
                    break
            if len(resultaat) >= self.max_woningen:
                break
        return resultaat[: self.max_woningen]

    def _parse_lijst(self, html: str, gezien: Optional[set] = None) -> List[Listing]:
        """Parse alle woningkaarten uit een lijstpagina.

        Elke woning staat twee keer op de pagina (mobiel + desktop), dus we
        ontdubbelen op detail-link. `gezien` mag over pagina's heen gedeeld
        worden zodat herhaalde kaarten niet dubbel tellen.
        """
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        if gezien is None:
            gezien = set()
        for link in soup.select('a[href^="/listings/"]'):
            href = link.get("href", "")
            if not href or href in gezien:
                continue
            gezien.add(href)
            try:
                kaart = self._kaart_van(link)
                if kaart is None:
                    continue
                woning = self._parse_kaart(href, kaart)
                if woning:
                    woningen.append(woning)
            except Exception:
                continue
        return woningen

    @staticmethod
    def _kaart_van(link):
        """Kleinste voorouder met prijs EN adres (postcode) = de woningkaart."""
        for ouder in link.parents:
            if ouder.name in ("body", "html", "[document]"):
                break
            tekst = ouder.get_text(" ", strip=True)
            heeft_prijs = "€" in tekst
            heeft_adres = re.search(r"\d{4}\s?[A-Z]{2}", tekst) is not None
            if heeft_prijs and heeft_adres:
                return ouder
        return None

    def _parse_kaart(self, href: str, kaart) -> Optional[Listing]:
        tekst = kaart.get_text(" ", strip=True)

        # Parkeerplaatsen/garages overslaan.
        if any(w in tekst.lower() for w in OVERSLAAN_WOORDEN):
            return None

        # De kaart heeft drie tekstregels (p-elementen): titel, adres, prijs.
        titel = None
        adres_regel = None
        for p in kaart.find_all("p"):
            regel = p.get_text(" ", strip=True)
            if not regel:
                continue
            if "€" in regel:
                continue  # prijsregel; prijs halen we uit de kaarttekst
            if ADRES_RE.match(regel):
                adres_regel = adres_regel or regel
            elif titel is None:
                titel = regel

        # Adres, postcode en plaats.
        adres = postcode = plaats = None
        if adres_regel:
            m = ADRES_RE.match(adres_regel)
            if m:
                adres = m.group("adres").strip()
                postcode = m.group("postcode")
                plaats = m.group("plaats").strip()

        # Prijs: "€929 / maand" of "€1.495 / maand".
        prijs = None
        m_prijs = re.search(r"€\s*[\d.]+", tekst)
        if m_prijs:
            prijs = parse_prijs(m_prijs.group(0))

        # Titel als "2-slaapkamer appartement van 32 m²" of "1 kamer van 18 m²".
        titel_tekst = titel or ""
        m_opp = re.search(r"(\d+)(?:[.,]\d+)?\s*m²", titel_tekst) or re.search(r"(\d+)(?:[.,]\d+)?\s*m²", tekst)
        oppervlak = int(m_opp.group(1)) if m_opp else None

        slaapkamers = None
        m_slaap = re.search(r"(\d+)\s*-\s*slaapkamer", titel_tekst, re.I)
        if m_slaap:
            slaapkamers = int(m_slaap.group(1))

        # Type bepalen; "kamer" alleen als losse woningsoort (niet "slaapkamer").
        titel_l = titel_tekst.lower()
        woning_type = None
        for t in WONING_TYPES:
            if t == "Kamer":
                if re.search(r"(?<!slaap)\bkamer\b", titel_l):
                    woning_type = t
                    break
            elif t.lower() in titel_l:
                woning_type = t
                break

        gedeeld = woning_type == "Kamer"
        if gedeeld and slaapkamers is None:
            slaapkamers = 1  # een kamer is de slaapkamer zelf

        # Zonder prijs en zonder adres is de kaart onbruikbaar.
        if prijs is None and adres is None:
            return None

        # Afbeelding (lazy-loaded via CDN; sla data:-placeholders over).
        afbeelding = None
        img = kaart.find("img")
        if img:
            for attr in ("src", "data-src", "data-original"):
                waarde = img.get(attr)
                if waarde and waarde.startswith("http"):
                    afbeelding = waarde
                    break

        return Listing(
            titel=titel or (woning_type or "Huurwoning"),
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            buurt=plaats,
            plaats=plaats,
            adres=adres,
            postcode=postcode,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
