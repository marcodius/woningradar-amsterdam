"""Basisklasse voor bronnen: nette HTTP, rate limiting en robots.txt."""
from __future__ import annotations

import time
import urllib.robotparser as robotparser
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from ..schema import Listing


class BaseSource:
    """
    Erf hiervan voor een nieuwe bron. Implementeer .haal_op().
    Zet klasse-attribuut `naam` en gebruik self.get() voor requests.
    """

    naam: str = "onbekend"
    basis_url: str = ""

    def __init__(self, config: Dict[str, Any], bron_conf: Dict[str, Any]):
        self.config = config
        self.bron_conf = bron_conf
        net = config.get("netwerk", {})
        self.delay = net.get("request_delay_seconden", 2.5)
        self.timeout = net.get("timeout_seconden", 20)
        self.respecteer_robots = net.get("respecteer_robots", True)
        self.max_woningen = net.get("max_woningen_per_bron", 60)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": net.get("user_agent", "Woningradar/1.0"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
        })
        self._laatste_request = 0.0
        self._robots: Optional[robotparser.RobotFileParser] = None

    # ---- HTTP-hulp met rate limiting en robots-check ----

    def _rate_limit(self) -> None:
        verstreken = time.time() - self._laatste_request
        if verstreken < self.delay:
            time.sleep(self.delay - verstreken)
        self._laatste_request = time.time()

    def _robots_toestaan(self, url: str) -> bool:
        if not self.respecteer_robots:
            return True
        if self._robots is None:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = robotparser.RobotFileParser()
            try:
                rp.set_url(robots_url)
                rp.read()
            except Exception:
                # robots.txt niet leesbaar: wees voorzichtig en sta toe,
                # maar de bron blijft verantwoordelijk voor nette omgang.
                rp = None
            self._robots = rp
        if self._robots is None:
            return True
        ua = self.session.headers.get("User-Agent", "*")
        return self._robots.can_fetch(ua, url)

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """GET met rate limiting, robots-check en nette foutafhandeling."""
        if not self._robots_toestaan(url):
            raise PermissionError(f"robots.txt verbiedt {url}")
        self._rate_limit()
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        if resp.status_code == 403:
            raise PermissionError(f"Geblokkeerd (403) door {self.naam}: {url}")
        if resp.status_code == 429:
            raise RuntimeError(f"Rate limited (429) door {self.naam}")
        resp.raise_for_status()
        return resp

    # ---- Hulp voor bron-URL's ----

    def prijs_max(self) -> Optional[int]:
        """Bovengrens huurprijs voor bron-URL's met een prijsfilter.

        Standaard de budgetgrens (`criteria.huur_max_kaal`), zodat we het
        paginabudget besteden aan betaalbare woningen in plaats van aan dure.
        Per bron te overschrijven met `prijs_max` in de config; 0/None = uit.
        """
        eigen = self.bron_conf.get("prijs_max")
        if eigen is not None:
            return int(eigen) or None
        grens = self.config.get("criteria", {}).get("huur_max_kaal")
        return int(grens) if grens else None

    # ---- Te implementeren door subklassen ----

    def haal_op(self) -> List[Listing]:
        raise NotImplementedError
