"""VBO / Vastgoed Nederland scraper — KOOPwoningen (de enige koop-bron).

vbo.nl stuurt door naar aanbod.vastgoednederland.nl, waar het aanbod
server-gerenderd staat. Per kaart (a.propertyLink > figure.property) is
beschikbaar: straat, plaats, vraagprijs (k.k.), woonoppervlak, aantal
slaapkamers en energielabel. Detailverrijking (erfpacht e.d.) kan later.

Lijstpagina: https://aanbod.vastgoednederland.nl/koopwoningen/<stad>
Paginering:  ?p=2, ?p=3, ... — een pagina voorbij het einde geeft gewoon
             HTTP 200 met nul kaarten, dus 'geen kaarten' = klaar. Een 404
             behandelen we voor de zekerheid ook als einde.
Detail-link: /koopwoningen/<stad>/woning-<id>-<straat-slug>
"""
from __future__ import annotations

import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

# Parkeerplaatsen, garageboxen e.d. zijn geen woningen.
OVERSLAAN_TREFWOORDEN = ["parkeer", "parking", "garage", "berging"]


class VboSource(BaseSource):
    naam = "vbo"
    basis_url = "https://aanbod.vastgoednederland.nl"

    def _steden(self) -> List[str]:
        return self.bron_conf.get("steden", ["amsterdam"])

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 2)
        for stad in self._steden():
            for pagina in range(1, max_paginas + 1):
                url = f"{self.basis_url}/koopwoningen/{stad}"
                if pagina > 1:
                    url += f"?p={pagina}"
                try:
                    resp = self.get(url)
                except requests.HTTPError as exc:
                    # 404 = einde paginering / onbekende stad, geen bronfout.
                    if exc.response is not None and exc.response.status_code == 404:
                        break
                    raise
                if resp is None:
                    break
                woningen = self._parse_lijst(resp.text)
                if not woningen:
                    # Pagina voorbij het einde geeft 200 met nul kaarten.
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
        for link in soup.select("a.propertyLink"):
            href = link.get("href", "")
            if not href or href in gezien:
                continue
            gezien.add(href)
            try:
                woning = self._parse_kaart(href, link)
                if woning:
                    woningen.append(woning)
            except Exception:
                continue
        return woningen

    def _parse_kaart(self, href: str, kaart) -> Optional[Listing]:
        # Straat/adres: eigen span, anders de alt-tekst van de foto.
        straat_el = kaart.select_one(".street")
        straat = straat_el.get_text(strip=True) if straat_el else None
        if not straat:
            img_alt = kaart.find("img")
            straat = img_alt.get("alt", "").strip() if img_alt else None
        if not straat:
            return None

        # Parkeerplaatsen/garages overslaan (check ook de URL-slug).
        controle = f"{straat} {href}".lower()
        if any(t in controle for t in OVERSLAAN_TREFWOORDEN):
            return None

        # Plaats.
        plaats_el = kaart.select_one(".city")
        plaats = plaats_el.get_text(strip=True) if plaats_el else None

        # Vraagprijs, bv. "€ 550.000,- k.k.".
        prijs = None
        prijs_el = kaart.select_one(".price")
        if prijs_el:
            prijs = parse_prijs(prijs_el.get_text(strip=True))
        # Prijs op aanvraag e.d. -> None laten; wel meenemen.

        tekst = kaart.get_text(" ", strip=True)

        # Woonoppervlak: getal voor "m²".
        oppervlak = None
        m_opp = re.search(r"(\d+)\s*m²", tekst)
        if m_opp:
            oppervlak = int(m_opp.group(1))

        # Slaapkamers: getal naast het bed-icoon.
        slaapkamers = None
        bed_icoon = kaart.select_one(".icon-bed")
        if bed_icoon and bed_icoon.parent:
            m_bed = re.search(r"(\d+)", bed_icoon.parent.get_text(" ", strip=True))
            if m_bed:
                slaapkamers = int(m_bed.group(1))

        # Energielabel: eigen span, bv. "A+++".
        energielabel = None
        label_el = kaart.select_one(".energielabel")
        if label_el:
            energielabel = label_el.get_text(strip=True) or None

        # Postcode staat niet op de kaart; soms wel in de omliggende tekst.
        postcode = None
        m_pc = re.search(r"\b(\d{4}\s?[A-Z]{2})\b", tekst)
        if m_pc:
            postcode = m_pc.group(1)

        return Listing(
            titel=straat,
            type="koop",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            energielabel=energielabel,
            plaats=plaats,
            adres=straat,
            postcode=postcode,
            afbeelding_url=self._afbeelding(kaart),
            bron=self.naam,
            url=href,
        )

    @staticmethod
    def _afbeelding(kaart) -> Optional[str]:
        img = kaart.find("img")
        if not img:
            return None
        for attr in ("data-src", "data-lazy", "src", "data-original"):
            waarde = img.get(attr)
            if waarde and waarde.startswith("http"):
                return waarde
        return None
