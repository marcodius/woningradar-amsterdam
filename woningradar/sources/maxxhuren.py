"""Maxx Huren (maxxhuren.nl) scraper.

Maxx is een landelijke verhuurder/aanhuurmakelaar (vestigingen o.a. Zwolle,
Groningen, Utrecht). Het regio-aanbod wisselt; de scoring filtert zelf op
plaats, dus we halen gewoon het hele aanbod op.

Lijstpagina: https://maxxhuren.nl/woonruimte-huren/
(NB: /woning-huren/ bestaat niet en geeft een 404-pagina.)

De site is een Webflow-pagina zonder paginering: alle objecten staan als
kaarten op één pagina (een ?page=N parameter wordt genegeerd en geeft
dezelfde inhoud terug). We lezen daarom maximaal `max_paginas` pagina's,
maar stoppen zodra een pagina geen nieuwe woningen oplevert.

Kaartstructuur (per object):
  <a id="object-<id>" href="/objects/ads/view/id-<id>/" class="object ...">
    <div class="object-reeds-verhuurd">Reeds verhuurd</div>   (optioneel)
    <div class="text-block-34">Celebesstraat 25-a</div>       (adres)
    <div class="plaatsnaam-object">Groningen</div>
    <div class="type-woonruimte-object">Studio</div>
    <div class="huurprijs-object">€501,28 per maand</div>
    <div class="oppervlak-object">15m²</div>
    <div class="text-block-35">1 kamers</div>
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..schema import Listing, parse_prijs
from .base import BaseSource

# Berging/garage/parkeerplaats zijn geen woonruimte; overslaan.
OVERSLAAN_TYPES = ["berging", "garage", "garagebox", "parkeerplaats", "parkeren"]

# Bij deze types deel je voorzieningen (badkamer/keuken).
GEDEELDE_TYPES = ["kamer"]


class MaxxhurenSource(BaseSource):
    naam = "maxxhuren"
    basis_url = "https://maxxhuren.nl"

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        gezien: set[str] = set()
        max_paginas = self.bron_conf.get("max_paginas", 1)
        for pagina in range(1, max_paginas + 1):
            url = f"{self.basis_url}/woonruimte-huren/"
            if pagina > 1:
                url += f"?page={pagina}"
            try:
                resp = self.get(url)
            except requests.HTTPError as exc:
                # 404 tijdens paginering = einde van het aanbod, geen bronfout.
                if exc.response is not None and exc.response.status_code == 404:
                    break
                raise
            if resp is None:
                break
            woningen = self._parse_lijst(resp.text)
            # Geen (nieuwe) woningen? Dan herhaalt de site zichzelf: stoppen.
            nieuw = [w for w in woningen if w.url not in gezien]
            if not nieuw:
                break
            for woning in nieuw:
                gezien.add(woning.url)
                resultaat.append(woning)
            if len(resultaat) >= self.max_woningen:
                break
        return resultaat[: self.max_woningen]

    def _parse_lijst(self, html: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        for kaart in soup.select('a[href*="/objects/ads/view/"]'):
            try:
                woning = self._parse_kaart(kaart)
                if woning:
                    woningen.append(woning)
            except Exception:
                # Eén kapotte kaart mag de oogst niet blokkeren.
                continue
        return woningen

    def _parse_kaart(self, kaart) -> Optional[Listing]:
        href = kaart.get("href", "")
        if not href:
            return None

        def veld(selector: str) -> Optional[str]:
            el = kaart.select_one(selector)
            tekst = el.get_text(" ", strip=True) if el else ""
            return tekst or None

        # Type bepalen; bergingen/garages/parkeerplaatsen overslaan.
        woning_type = veld(".type-woonruimte-object")
        if woning_type and woning_type.lower() in OVERSLAAN_TYPES:
            return None

        # Reeds verhuurde objecten zijn niet meer beschikbaar.
        if kaart.select_one(".object-reeds-verhuurd"):
            return None

        adres = veld(".text-block-34")
        plaats = veld(".plaatsnaam-object")

        # Prijs: "€501,28 per maand" -> 501 (parse_prijs knipt decimalen af).
        prijs = parse_prijs(veld(".huurprijs-object"))

        # Oppervlak: "23m²" -> 23.
        oppervlak = None
        m_opp = re.search(r"(\d+)\s*m", veld(".oppervlak-object") or "")
        if m_opp:
            oppervlak = int(m_opp.group(1))

        # Kamers: "1 kamers" (soms leeg: " kamers"). Kamers incl. woonkamer.
        slaapkamers = None
        m_kamers = re.search(r"(\d+)\s*kamer", kaart.get_text(" ", strip=True), re.I)
        if m_kamers:
            slaapkamers = max(int(m_kamers.group(1)) - 1, 0)

        # Afbeelding.
        afbeelding = None
        img = kaart.find("img")
        if img:
            for attr in ("data-src", "src"):
                waarde = img.get(attr)
                if waarde and waarde.startswith("http"):
                    afbeelding = waarde
                    break

        gedeeld = bool(woning_type) and woning_type.lower() in GEDEELDE_TYPES

        titel = adres or woning_type or "Huurwoning"

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            gedeelde_voorzieningen=gedeeld,
            plaats=plaats,
            adres=adres,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=urljoin(self.basis_url, href),
        )
