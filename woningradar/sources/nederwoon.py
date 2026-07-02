"""NederWoon scraper.

NederWoon is een landelijke verhuurmakelaar met server-gerenderde
listing-pagina's. In tegenstelling tot Funda/Pararius blokkeert NederWoon
datacenter-IP's (GitHub Actions) niet, dus dit werkt gewoon in CI.

Lijstpagina: https://www.nederwoon.nl/huurwoningen/<stad>
Detail-links: /huurwoning/<stad>/<id>/<slug>

De lijstpagina bevat per woning al: straat, postcode+plaats, type, woonoppervlak,
aantal kamers, oplevering en kale huur. Dat is genoeg om te scoren; detail-
verrijking (energielabel, buitenruimte) kan later.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

WONING_TYPES = ["Appartement", "Studio", "Kamer", "Woonhuis", "Maisonnette"]
OVERSLAAN_TYPES = ["Garagebox", "Parkeerplaats"]


class NederwoonSource(BaseSource):
    naam = "nederwoon"
    basis_url = "https://www.nederwoon.nl"

    def _steden(self) -> List[str]:
        # Steden/plaatsen om te doorzoeken; Amsterdam-pagina toont ook omgeving.
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 2)
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                url = f"{self.basis_url}/huurwoningen/{stad}"
                if pagina > 1:
                    url += f"?page={pagina}"
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # NederWoon geeft 404 op niet-bestaande pagina's (sinds de
                    # sitewijziging ook op elke ?page=N). Dat is het einde van
                    # deze stad, geen bronfout.
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
        for link in soup.select('a[href*="/huurwoning/"]'):
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
        """Kleinste voorouder met prijs EN kenmerken = de volledige woningkaart.

        We eisen zowel de prijs (€) als een woningkenmerk (m² / kamers /
        Woonoppervlakte), zodat we niet per ongeluk een te kleine prijs-wrapper
        pakken. De eerste (kleinste) match vanaf de link omhoog is de kaart.
        """
        for ouder in link.parents:
            if ouder.name in ("body", "html", "[document]"):
                break
            tekst = ouder.get_text(" ", strip=True)
            heeft_prijs = "€" in tekst
            heeft_kenmerk = ("m" in tekst and "Woonoppervlakte" in tekst) or "kamer" in tekst
            if heeft_prijs and heeft_kenmerk:
                return ouder
        return None

    def _parse_kaart(self, href: str, kaart) -> Optional[Listing]:
        tekst = kaart.get_text(" ", strip=True)

        # Type bepalen; garageboxen/parkeerplaatsen overslaan.
        if any(t.lower() in tekst.lower() for t in OVERSLAAN_TYPES):
            return None
        woning_type = next((t for t in WONING_TYPES if t.lower() in tekst.lower()), None)

        # Stad uit de URL: /huurwoning/<stad>/<id>/<slug>
        delen = [d for d in href.split("/") if d]
        stad = delen[1].replace("-", " ").title() if len(delen) > 1 else None

        # Postcode + plaats uit de tekst (bv. "1113LC Diemen").
        postcode = None
        m_pc = re.search(r"\b(\d{4}\s?[A-Z]{2})\b", tekst)
        if m_pc:
            postcode = m_pc.group(1)

        # Woonoppervlak, kamers, prijs.
        m_opp = re.search(r"(\d+)\s*m", tekst)
        oppervlak = int(m_opp.group(1)) if m_opp else None

        m_kamers = re.search(r"(\d+)\s*kamer", tekst, re.I)
        slaapkamers = None
        if m_kamers:
            kamers = int(m_kamers.group(1))
            slaapkamers = max(kamers - 1, 0)   # kamers = incl. woonkamer
        elif "Geen kamers" in tekst:
            slaapkamers = 0

        # Kale huur: eerste prijs vlak voor "Kale huur".
        prijs = None
        m_prijs = re.search(r"€\s*([\d.]+)", tekst)
        if m_prijs:
            prijs = parse_prijs(m_prijs.group(0))

        # Oplevering -> gestoffeerd/gemeubileerd als plus voor "snel betrekken".
        oplevering = None
        for opl in ("Gemeubileerd en gestoffeerd", "Gemeubileerd", "Gestoffeerd", "Kaal"):
            if opl.lower() in tekst.lower():
                oplevering = opl
                break

        # Titel: straat uit de slug.
        slug = delen[-1] if delen else ""
        titel = slug.replace("-", " ").title() or (woning_type or "Huurwoning")

        # Afbeelding (lazy-loaded: sla data:-placeholders over).
        afbeelding = None
        img = kaart.find("img")
        if img:
            for attr in ("data-src", "data-lazy", "src", "data-original"):
                waarde = img.get(attr)
                if waarde and waarde.startswith("http"):
                    afbeelding = waarde
                    break

        gedeeld = woning_type == "Kamer"

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            buurt=stad,
            plaats=stad,
            postcode=postcode,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
