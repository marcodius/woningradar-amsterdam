"""Bronregister: koppelt confignamen aan scrapermodules."""
from __future__ import annotations

from typing import Any, Dict, List

from ..schema import Listing
from .base import BaseSource
from .demo import DemoSource
from .directwonen import DirectwonenSource
from .funda import FundaSource
from .huurstunt import HuurstuntSource
from .huurwoningen import HuurwoningenSource
from .huurwoningencom import HuurwoningenComSource
from .ikwilhuren import IkwilhurenSource
from .interhouse import InterhouseSource
from .kamernet import KamernetSource
from .maxxhuren import MaxxhurenSource
from .nederwoon import NederwoonSource
from .pararius import ParariusSource
from .rentola import RentolaSource
from .vbo import VboSource
from .vbt import VbtSource

# Configsleutel -> klasse
REGISTER: Dict[str, type[BaseSource]] = {
    "demo": DemoSource,
    "nederwoon": NederwoonSource,
    "huurwoningen": HuurwoningenSource,
    "pararius": ParariusSource,
    "funda": FundaSource,
    "ikwilhuren": IkwilhurenSource,
    "huurwoningencom": HuurwoningenComSource,
    "huurstunt": HuurstuntSource,
    "rentola": RentolaSource,
    "directwonen": DirectwonenSource,
    "interhouse": InterhouseSource,
    "vbt": VbtSource,
    "kamernet": KamernetSource,
    "maxxhuren": MaxxhurenSource,
    "vbo": VboSource,
}


def actieve_bronnen(config: Dict[str, Any]) -> List[BaseSource]:
    """Instantieer alle ingeschakelde bronnen uit de config."""
    bronnen: List[BaseSource] = []
    for naam, klasse in REGISTER.items():
        bron_conf = config.get("bronnen", {}).get(naam, {})
        if bron_conf.get("ingeschakeld"):
            bronnen.append(klasse(config, bron_conf))
    return bronnen


def haal_alles_op(config: Dict[str, Any]) -> tuple[List[Listing], Dict[str, str]]:
    """
    Draai elke ingeschakelde bron. Fouten in één bron laten de rest doorlopen.
    Geeft (woningen, status-per-bron) terug.
    """
    resultaat: List[Listing] = []
    status: Dict[str, str] = {}
    for bron in actieve_bronnen(config):
        try:
            woningen = bron.haal_op()
            resultaat.extend(woningen)
            status[bron.naam] = f"ok ({len(woningen)})"
        except Exception as exc:  # bewust breed: één bron mag de rest niet breken
            status[bron.naam] = f"fout: {exc}"
    return resultaat, status
