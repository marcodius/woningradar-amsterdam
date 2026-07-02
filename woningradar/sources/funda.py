"""Funda scraper (best-effort).

BELANGRIJK: Funda verbiedt scrapen en blokkeert bots actief (o.a. via
uitgebreide botdetectie). Deze module staat standaard UIT in config.yaml.
Voor legitiem gebruik biedt Funda een Partner-API aan; dat is de nette route.

Deze module probeert de publieke zoekpagina met 'requests'. In de praktijk zal
Funda dit vrijwel altijd blokkeren (403 of een botpagina). Dan wordt de bron
netjes overgeslagen. Voor JavaScript-rendering is Playwright nodig; zie README.
Zowel huur als koop wordt ondersteund op basis van config.
"""
from __future__ import annotations

import json
import re
from typing import List

from bs4 import BeautifulSoup

from ..schema import Listing, parse_oppervlak, parse_prijs
from .base import BaseSource


class FundaSource(BaseSource):
    naam = "funda"
    basis_url = "https://www.funda.nl"

    def _zoek_urls(self) -> list[tuple[str, str]]:
        """(type, url) voor huur en/of koop op basis van budget."""
        c = self.config["criteria"]
        urls = []
        # Huur
        urls.append((
            "huur",
            f"{self.basis_url}/zoeken/huur?selected_area=%5B%22amsterdam%22%5D"
            f"&price=%220-{c['huur_max_kaal']}%22",
        ))
        # Koop: ruwe prijsbovengrens afgeleid van maandlastgrens (indicatief).
        # ~1500/mnd annuiteit bij 4,1% -> ~ 310.000; iets ruimer zoeken.
        urls.append((
            "koop",
            f"{self.basis_url}/zoeken/koop?selected_area=%5B%22amsterdam%22%5D"
            f"&price=%220-350000%22",
        ))
        return urls

    def haal_op(self) -> List[Listing]:
        resultaat: List[Listing] = []
        for type_, url in self._zoek_urls():
            resp = self.get(url)
            if resp is None:
                continue
            resultaat.extend(self._parse(resp.text, type_))
            if len(resultaat) >= self.max_woningen:
                break
        return resultaat[: self.max_woningen]

    def _parse(self, html: str, type_: str) -> List[Listing]:
        """
        Funda rendert resultaten deels via JSON in de pagina. We proberen eerst
        gestructureerde data (JSON-LD / __NUXT__), anders vallen we terug op HTML.
        """
        woningen = self._parse_json_ld(html, type_)
        if woningen:
            return woningen
        return self._parse_html(html, type_)

    def _parse_json_ld(self, html: str, type_: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            items = data.get("itemListElement") if isinstance(data, dict) else None
            if not items:
                continue
            for it in items:
                url = it.get("url") or (it.get("item") or {}).get("url")
                naam = it.get("name") or (it.get("item") or {}).get("name") or "Funda-woning"
                if url:
                    woningen.append(Listing(
                        titel=naam,
                        type=type_,
                        plaats="Amsterdam",
                        vrije_sector_bevestigd=None,
                        bron=self.naam,
                        url=url,
                    ))
        return woningen

    def _parse_html(self, html: str, type_: str) -> List[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        woningen: List[Listing] = []
        for kaart in soup.select("[data-test-id='search-result-item'], .search-result"):
            try:
                link = kaart.select_one("a[href*='/detail/'], a[href]")
                if not link:
                    continue
                url = link.get("href", "")
                if url.startswith("/"):
                    url = self.basis_url + url
                titel = link.get_text(strip=True) or "Funda-woning"
                tekst = kaart.get_text(" ", strip=True)
                woningen.append(Listing(
                    titel=titel,
                    type=type_,
                    prijs=parse_prijs(tekst),
                    oppervlak_m2=parse_oppervlak(tekst),
                    plaats="Amsterdam",
                    vrije_sector_bevestigd=None,
                    bron=self.naam,
                    url=url,
                ))
            except Exception:
                continue
        return woningen
