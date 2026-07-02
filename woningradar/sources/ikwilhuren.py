"""ikwilhuren.nu scraper (MVGM).

ikwilhuren.nu is het huurplatform van vastgoedbeheerder MVGM met
server-gerenderde lijstpagina's (Bootstrap-kaarten, geen JS nodig).

Let op: het zoekveld op de site werkt via een POST met CSRF-token en een
geo-id uit een autocomplete-endpoint; die zoekopdracht blijft in de
serversessie hangen en is voor een scraper onbetrouwbaar. De kale lijst
(https://ikwilhuren.nu/aanbod/?page=N) is landelijk en gesorteerd op
nieuwste eerst. We pagineren daarom door de landelijke lijst en filteren
zelf op plaats (uit de detail-URL), wat voor een radar prima werkt.

Kaartstructuur (div.card-woning):
  - a.stretched-link  href="/object/<plaats>-<postcode>-<nr>-<straat>-<hash>/"
  - titel:            "Appartement Schipholweg 232"
  - locatie:          "2316XD Leiden"
  - onderbalk:        "€ 1.166,- /mnd  46 m²  1 slaapkamer"
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

# Woningtype staat vooraan in de kaarttitel.
WONING_TYPES = ["Appartement", "Studio", "Kamer", "Eengezinswoning", "Woonhuis", "Maisonnette", "Penthouse"]
OVERSLAAN_WOORDEN = ["parkeerplaats", "parkeer", "garagebox", "garage", "berging"]

# Standaard: Amsterdam en directe omgeving (plaats komt uit de object-URL).
STANDAARD_PLAATSEN = [
    "amsterdam", "amstelveen", "diemen", "duivendrecht", "weesp",
    "zaandam", "badhoevedorp", "landsmeer", "ouderkerk aan de amstel",
]


class IkwilhurenSource(BaseSource):
    naam = "ikwilhuren"
    basis_url = "https://ikwilhuren.nu"

    def _plaatsen(self) -> List[str]:
        """Plaatsnamen (kleine letters) om op te filteren; leeg = alles."""
        return [p.lower() for p in self.bron_conf.get("plaatsen", STANDAARD_PLAATSEN)]

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        gezien: set[str] = set()
        max_paginas = self.bron_conf.get("max_paginas", 5)
        for pagina in range(1, max_paginas + 1):
            url = f"{self.basis_url}/aanbod/"
            if pagina > 1:
                url += f"?page={pagina}"
            try:
                resp = self.get(url)
            except requests.HTTPError as exc:
                # 404 op een vervolgpagina = einde paginering, geen bronfout.
                if exc.response is not None and exc.response.status_code == 404:
                    break
                raise
            if resp is None:
                break
            woningen = self._parse_lijst(resp.text)
            if not woningen:
                # Voorbij de laatste pagina redirect de site naar een lege/
                # eerste pagina; geen kaarten = klaar.
                break
            nieuw = 0
            for woning in woningen:
                if woning.url in gezien:
                    continue
                gezien.add(woning.url)
                nieuw += 1
                if self._plaats_gewenst(woning.plaats):
                    resultaat.append(woning)
            if nieuw == 0:
                # Alleen al bekende kaarten: de site herhaalt de laatste
                # pagina, dus stoppen.
                break
            if len(resultaat) >= self.max_woningen:
                break
        return resultaat[: self.max_woningen]

    def _plaats_gewenst(self, plaats: Optional[str]) -> bool:
        gewenst = self._plaatsen()
        if not gewenst:
            return True
        return bool(plaats) and plaats.lower() in gewenst

    def _parse_lijst(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        for kaart in soup.select("div.card-woning"):
            try:
                woning = self._parse_kaart(kaart)
                if woning:
                    woningen.append(woning)
            except Exception:
                continue
        return woningen

    def _parse_kaart(self, kaart) -> Optional[Listing]:
        link = kaart.select_one("a.stretched-link") or kaart.select_one('a[href*="/object/"]')
        if link is None:
            return None
        href = link.get("href", "")
        titel = link.get_text(" ", strip=True)
        if not href or not titel:
            return None

        # Parkeerplaatsen, garages e.d. overslaan.
        if any(w in titel.lower() for w in OVERSLAAN_WOORDEN):
            return None

        tekst = kaart.get_text(" ", strip=True)
        woning_type = next((t for t in WONING_TYPES if titel.lower().startswith(t.lower())), None)

        # Plaats + postcode uit de detail-URL: /object/<plaats>-<postcode>-...
        plaats = None
        m_url = re.search(r"/object/(.+?)-(\d{4}[a-z]{2})-", href, re.I)
        if m_url:
            plaats = m_url.group(1).replace("-", " ").title()

        # Postcode uit de kaarttekst (bv. "2316XD Leiden").
        postcode = None
        m_pc = re.search(r"\b(\d{4}\s?[A-Z]{2})\b", tekst)
        if m_pc:
            postcode = m_pc.group(1)
        # Plaats uit de tekst als fallback: "2316XD Leiden".
        if plaats is None and m_pc:
            m_plaats = re.search(re.escape(m_pc.group(1)) + r"\s+([A-Za-z'\- ]+?)(?:\s{2,}|$|\sDirect|\sBeschikbaar)", tekst)
            if m_plaats:
                plaats = m_plaats.group(1).strip().title()

        # Prijs: "€ 1.166,- /mnd".
        prijs = None
        m_prijs = re.search(r"€\s*([\d.,]+)", tekst)
        if m_prijs:
            prijs = parse_prijs(m_prijs.group(0))

        # Oppervlak: "46 m²" (de sup rendert als "46 m 2").
        oppervlak = None
        m_opp = re.search(r"(\d+)\s*m\s*[²2]", tekst)
        if m_opp:
            oppervlak = int(m_opp.group(1))

        # Slaapkamers: "1 slaapkamer" / "2 slaapkamers".
        slaapkamers = None
        m_slk = re.search(r"(\d+)\s*slaapkamer", tekst, re.I)
        if m_slk:
            slaapkamers = int(m_slk.group(1))

        # Adres: de titel minus het woningtype ("Schipholweg 232").
        adres = titel
        if woning_type:
            adres = re.sub(rf"^{woning_type}\s*", "", titel, flags=re.I).strip() or None

        # Afbeelding (thumbnails staan op a.static.nbo.nl, soms protocol-relatief).
        afbeelding = None
        img = kaart.find("img")
        if img:
            for attr in ("data-src", "src"):
                waarde = img.get(attr)
                if waarde and (waarde.startswith("http") or waarde.startswith("//")):
                    afbeelding = "https:" + waarde if waarde.startswith("//") else waarde
                    break

        gedeeld = woning_type == "Kamer"

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            plaats=plaats,
            adres=adres,
            postcode=postcode,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
