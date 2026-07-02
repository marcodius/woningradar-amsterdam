"""Geocoding via de PDOK Locatieserver (gratis, geen sleutel, NL-breed).

Zet adres/postcode om naar lat/lon en verrijkt zo nodig de buurt. Resultaten
worden lokaal gecachet (data/geocode_cache.json) zodat we niet elke run opnieuw
bevragen. PDOK is de officiele geocoder van de Nederlandse overheid (BAG).
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional, Tuple

import requests

from .schema import Listing

PDOK_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
CACHE_PAD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "geocode_cache.json",
)


def _laad_cache() -> dict:
    try:
        with open(CACHE_PAD, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _bewaar_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PAD), exist_ok=True)
    with open(CACHE_PAD, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)


def _zoekterm(listing: Listing) -> Optional[str]:
    delen = []
    if listing.adres:
        delen.append(listing.adres)
    if listing.postcode:
        delen.append(listing.postcode)
    if not listing.adres and listing.buurt:
        delen.append(listing.buurt)
    if listing.plaats:
        delen.append(listing.plaats)
    term = " ".join(delen).strip()
    return term or None


def _parse_point(punt: str) -> Optional[Tuple[float, float]]:
    # "POINT(4.912 52.351)" -> (52.351, 4.912)  (lat, lon)
    m = re.search(r"POINT\(([-\d.]+)\s+([-\d.]+)\)", punt or "")
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    return lat, lon


def geocode_term(term: str, timeout: int = 15) -> Optional[Tuple[float, float, Optional[str]]]:
    """Geef (lat, lon, buurtnaam) voor een zoekterm, of None."""
    try:
        resp = requests.get(
            PDOK_URL,
            params={"q": term, "fq": "type:adres", "rows": 1},
            timeout=timeout,
            headers={"User-Agent": "Woningradar/1.0"},
        )
        resp.raise_for_status()
        docs = resp.json().get("response", {}).get("docs", [])
        if not docs:
            return None
        doc = docs[0]
        punt = _parse_point(doc.get("centroide_ll", ""))
        if not punt:
            return None
        return punt[0], punt[1], doc.get("buurtnaam")
    except Exception:
        return None


def geocode_listings(
    listings: List[Listing],
    max_calls: int = 60,
    delay: float = 0.3,
) -> List[Listing]:
    """
    Vul lat/lon voor woningen die nog geen coordinaten hebben. Gebruikt de cache
    en beperkt het aantal live-verzoeken (max_calls) per run.
    """
    cache = _laad_cache()
    calls = 0
    for l in listings:
        if l.lat is not None and l.lon is not None:
            continue
        term = _zoekterm(l)
        if not term:
            continue
        if term in cache:
            gegevens = cache[term]
        elif calls < max_calls:
            resultaat = geocode_term(term)
            calls += 1
            time.sleep(delay)
            gegevens = (
                {"lat": resultaat[0], "lon": resultaat[1], "buurt": resultaat[2]}
                if resultaat else None
            )
            cache[term] = gegevens
        else:
            continue

        if gegevens:
            l.lat = gegevens["lat"]
            l.lon = gegevens["lon"]
            if not l.buurt and gegevens.get("buurt"):
                l.buurt = gegevens["buurt"]

    _bewaar_cache(cache)
    return listings
