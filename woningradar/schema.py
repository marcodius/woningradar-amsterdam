"""Genormaliseerd woningschema plus hulpfuncties om ruwe data te normaliseren."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Eén genormaliseerde woningadvertentie."""

    titel: str
    type: str                          # "huur" of "koop"
    prijs: Optional[int] = None        # kale huur of vraagprijs in hele euro's
    servicekosten: Optional[int] = None
    slaapkamers: Optional[int] = None
    oppervlak_m2: Optional[int] = None
    buitenruimte: bool = False
    buitenruimte_soort: Optional[str] = None   # balkon/tuin/dakterras/...
    parkeren: bool = False
    energielabel: Optional[str] = None
    buurt: Optional[str] = None
    plaats: Optional[str] = None
    adres: Optional[str] = None
    postcode: Optional[str] = None
    erfpacht: Optional[str] = None      # afgekocht / eeuwigdurend afgekocht / lopende canon
    erfpacht_canon_per_jaar: Optional[int] = None
    inkomenseis: Optional[int] = None   # gevraagd bruto maandinkomen, indien bekend
    tijdelijk_contract: bool = False
    gedeelde_voorzieningen: bool = False
    vrije_sector_bevestigd: Optional[bool] = None   # None = onbekend/twijfel
    afbeelding_url: Optional[str] = None    # foto uit de bron, indien beschikbaar
    lat: Optional[float] = None             # breedtegraad (geocoding)
    lon: Optional[float] = None             # lengtegraad (geocoding)
    bron: str = ""
    url: str = ""
    datum_geplaatst: Optional[str] = None   # ISO-datum indien bekend
    ook_op: list = field(default_factory=list)   # andere bronnen na ontdubbeling

    # Afgeleide velden (gevuld door scoring/mortgage/orchestrator).
    id: Optional[str] = None
    score: Optional[float] = None
    indeling: Optional[str] = None          # topmatch / lage_match / afgewezen
    redenen: list = field(default_factory=list)
    waarschuwingen: list = field(default_factory=list)
    afwijs_redenen: list = field(default_factory=list)
    maandlast_koop: Optional[int] = None    # berekende bruto maandlast (koop)
    maandlast_aanname: Optional[str] = None

    def bereken_id(self) -> str:
        """Stabiele identifier voor ontdubbeling en bewaren in de frontend."""
        sleutel = _dedup_sleutel(self)
        return hashlib.sha1(sleutel.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Parse-hulpjes: ruwe strings van sites omzetten naar nette waarden.
# --------------------------------------------------------------------------

def parse_prijs(tekst: Optional[str]) -> Optional[int]:
    """'€ 1.750 p/m' -> 1750 ; '€ 425.000 k.k.' -> 425000."""
    if not tekst:
        return None
    tekst = tekst.replace("\xa0", " ")
    # Verwijder decimalen zoals ",50"
    tekst = re.sub(r",\d{2}\b", "", tekst)
    cijfers = re.sub(r"[^\d]", "", tekst)
    if not cijfers:
        return None
    try:
        return int(cijfers)
    except ValueError:
        return None


def parse_int(tekst: Optional[str]) -> Optional[int]:
    if tekst is None:
        return None
    if isinstance(tekst, (int, float)):
        return int(tekst)
    m = re.search(r"\d+", str(tekst).replace(".", ""))
    return int(m.group()) if m else None


def parse_oppervlak(tekst: Optional[str]) -> Optional[int]:
    """'75 m²' -> 75."""
    if tekst is None:
        return None
    if isinstance(tekst, (int, float)):
        return int(tekst)
    m = re.search(r"(\d+)\s*m", str(tekst))
    if m:
        return int(m.group(1))
    return parse_int(tekst)


def parse_energielabel(tekst: Optional[str]) -> Optional[str]:
    if not tekst:
        return None
    m = re.search(r"\b([A-G])(\+{0,4})\b", tekst.upper())
    return (m.group(1) + m.group(2)) if m else None


def detecteer_buitenruimte(tekst: Optional[str]) -> tuple[bool, Optional[str]]:
    if not tekst:
        return False, None
    tekst_l = tekst.lower()
    for soort in ("dakterras", "tuin", "balkon", "terras", "loggia"):
        if soort in tekst_l:
            return True, soort
    return False, None


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _dedup_sleutel(listing: "Listing") -> str:
    """
    Sleutel voor ontdubbeling. Bij voorkeur op adres+postcode, anders op een
    combinatie van kenmerken zodat dezelfde woning op meerdere bronnen samenvalt.
    """
    if listing.postcode and listing.adres:
        return _norm(listing.postcode) + _norm(listing.adres)
    if listing.adres and listing.plaats:
        return _norm(listing.adres) + _norm(listing.plaats)
    # Fallback: type + prijs + oppervlak + slaapkamers + buurt
    return "|".join(
        str(x) for x in (
            listing.type,
            listing.prijs,
            listing.oppervlak_m2,
            listing.slaapkamers,
            _norm(listing.buurt) or _norm(listing.plaats),
        )
    )
