"""Interhouse scraper.

Interhouse is een landelijke verhuur-/verkoopmakelaar (interhouse.nl).
De zoekpagina (https://interhouse.nl/huurwoningen/) rendert de resultaten
client-side via een AJAX-endpoint onder /wp-admin/, en dat pad verbiedt
robots.txt. Gelukkig staan alle woningen als WordPress-posttype "property"
in de publieke REST API, en die is wel gewoon toegestaan:

    Lijst:   /wp-json/wp/v2/property?per_page=100&page=N
    Detail:  https://interhouse.nl/vastgoed/huur/<stad>/<type>/<slug>/

De REST-lijst bevat alleen titel + detail-link; prijs, oppervlak, kamers,
postcode en energielabel staan in de dt/dd-tabel op de detailpagina. We
filteren dus eerst op huur + stad via de detail-URL en halen daarna per
woning één detailpagina op (binnen max_woningen blijft dat beperkt).
"""
from __future__ import annotations

import html as html_mod
import re
from typing import List, Optional, Tuple

import requests
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

# Type-segmenten in de detail-URL die geen woonruimte zijn.
OVERSLAAN_URL_TYPES = ("parkeer", "garage", "berging", "bog")
# Zelfde check nogmaals op het "Type"-veld van de detailpagina (de URL bevat
# soms een letterlijke "%type%"-placeholder, dan is dit het vangnet).
OVERSLAAN_TYPES = ("parkeer", "garage", "garagebox", "berging", "bog")


class InterhouseSource(BaseSource):
    naam = "interhouse"
    basis_url = "https://interhouse.nl"

    def __init__(self, config, bron_conf):
        super().__init__(config, bron_conf)
        # Aantal REST-items per pagina; klein te zetten in tests.
        self._per_pagina = 100

    def _steden(self) -> List[str]:
        # Prefix-match op het stad-segment van de detail-URL, zodat
        # "amsterdam" ook "amsterdam-oost" en "amsterdam-zuid" meepakt.
        return [s.lower() for s in self.bron_conf.get("steden", ["amsterdam"])]

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        max_paginas = self.bron_conf.get("max_paginas", 2)
        gezien: set[str] = set()
        for pagina in range(1, max_paginas + 1):
            url = (
                f"{self.basis_url}/wp-json/wp/v2/property"
                f"?per_page={self._per_pagina}&page={pagina}"
            )
            try:
                resp = self.get(url)
            except requests.HTTPError as exc:
                # Voorbij de laatste pagina geeft WordPress 400
                # (rest_post_invalid_page_number) of 404: einde paginering.
                if exc.response is not None and exc.response.status_code in (400, 404):
                    break
                raise
            if resp is None:
                break
            try:
                items = resp.json()
            except ValueError:
                break
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if len(resultaat) >= self.max_woningen:
                    break
                kandidaat = self._filter_item(item)
                if kandidaat is None:
                    continue
                detail_url, titel, datum = kandidaat
                if detail_url in gezien:
                    continue
                gezien.add(detail_url)
                try:
                    detail = self.get(detail_url)
                except requests.HTTPError:
                    # Eén kapotte detailpagina mag de oogst niet blokkeren.
                    continue
                if detail is None:
                    continue
                try:
                    woning = self._parse_detail(detail_url, detail.text, titel, datum)
                except Exception:
                    continue
                if woning:
                    resultaat.append(woning)
            if len(items) < self._per_pagina or len(resultaat) >= self.max_woningen:
                break
        return resultaat[: self.max_woningen]

    def _filter_item(self, item: dict) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Beslis op basis van een REST-item of de woning interessant is.

        Geeft (detail_url, titel, datum_geplaatst) terug, of None om over
        te slaan. De detail-URL is /vastgoed/<offer>/<stad>/<type>/<slug>/.
        """
        link = item.get("link") or ""
        if "/vastgoed/huur/" not in link:
            return None       # koop of geen woning-link
        delen = link.split("/vastgoed/huur/", 1)[1].strip("/").split("/")
        if not delen or not delen[0]:
            return None
        stad_slug = delen[0].lower()
        if not any(stad_slug.startswith(s) for s in self._steden()):
            return None
        if len(delen) > 1 and any(t in delen[1].lower() for t in OVERSLAAN_URL_TYPES):
            return None       # parkeerplaats/garage/bedrijfspand
        titel = ((item.get("title") or {}).get("rendered") or "").strip()
        titel = html_mod.unescape(titel) or None
        datum = (item.get("date") or "")[:10] or None
        # Let op: soms bevat de link een letterlijke "%type%"-placeholder
        # (importfout bij Interhouse). Die pagina geeft 400 en wordt bij het
        # ophalen van de detailpagina netjes overgeslagen.
        return link, titel, datum

    def _parse_detail(
        self,
        url: str,
        pagina_html: str,
        titel: Optional[str] = None,
        datum: Optional[str] = None,
    ) -> Optional[Listing]:
        """Parseer de dt/dd-kenmerkentabel van een detailpagina."""
        soup = BeautifulSoup(pagina_html, "html.parser")

        velden = {}
        for dt in soup.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd is not None:
                velden[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)
        if not velden:
            return None

        woning_type = velden.get("Type", "")
        if any(t in woning_type.lower() for t in OVERSLAAN_TYPES):
            return None

        prijs = parse_prijs(velden.get("Huurprijs"))
        oppervlak = parse_oppervlak(velden.get("Woonoppervlakte"))

        # Slaapkamers direct, anders afleiden uit kamers (incl. woonkamer).
        slaapkamers = parse_int(velden.get("Aantal slaapkamers"))
        if slaapkamers is None:
            kamers = parse_int(velden.get("Aantal kamers"))
            if kamers is not None:
                slaapkamers = max(kamers - 1, 0)

        plaats = velden.get("Stad")
        adres = velden.get("Straatnaam")
        postcode = None
        m_pc = re.search(r"\b(\d{4}\s?[A-Z]{2})\b", velden.get("Postcode", ""))
        if m_pc:
            postcode = m_pc.group(1)

        buitenruimte, soort = detecteer_buitenruimte(velden.get("Voorzieningen"))
        if not buitenruimte and "Tuin oppervlakte" in velden:
            buitenruimte, soort = True, "tuin"

        # Kamers worden gedeeld bewoond.
        gedeeld = woning_type.strip().lower().startswith("kamer")

        afbeelding = None
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content", "").startswith("http"):
            afbeelding = og["content"]

        if not titel:
            titel = ", ".join(x for x in (adres, plaats) if x) or "Huurwoning"

        return Listing(
            titel=titel,
            type="huur",
            prijs=prijs,
            slaapkamers=slaapkamers,
            oppervlak_m2=oppervlak,
            buitenruimte=buitenruimte,
            buitenruimte_soort=soort,
            parkeren="parkeer" in velden.get("Voorzieningen", "").lower(),
            energielabel=parse_energielabel(velden.get("Energieklasse")),
            buurt=plaats,
            plaats=plaats,
            adres=adres,
            postcode=postcode,
            gedeelde_voorzieningen=gedeeld,
            vrije_sector_bevestigd=None,
            afbeelding_url=afbeelding,
            bron=self.naam,
            url=url,
            datum_geplaatst=datum,
        )
