"""Harde filters, scoring en indeling van woningen."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .mortgage import bereken_koop_maandlast
from .schema import Listing


# --------------------------------------------------------------------------
# Harde filters -> woning wordt afgewezen als er een reden terugkomt.
# --------------------------------------------------------------------------

def harde_filters(listing: Listing, config: Dict[str, Any]) -> List[str]:
    """Geeft een lijst met afwijsredenen. Leeg = voldoet aan de harde eisen."""
    c = config["criteria"]
    redenen: List[str] = []

    # 1. Zelfstandigheid / gedeelde voorzieningen
    if c.get("zelfstandig_verplicht") and listing.gedeelde_voorzieningen:
        redenen.append("Gedeelde voorzieningen of kamerverhuur")

    # 2. Minimaal aantal slaapkamers (studio zonder slaapkamer valt af)
    if listing.slaapkamers is not None and listing.slaapkamers < c["min_slaapkamers"]:
        redenen.append(
            f"Minder dan {c['min_slaapkamers']} slaapkamer (studio zonder aparte slaapkamer)"
        )

    # 3. Locatie
    if not _locatie_toegestaan(listing, c):
        redenen.append("Locatie buiten Amsterdam en directe, OV-bereikbare omgeving")

    # 4. Budget
    if listing.type == "huur":
        if listing.prijs is not None and listing.prijs > c["huur_max_kaal"]:
            redenen.append(
                f"Kale huur EUR {listing.prijs} boven grens van EUR {c['huur_max_kaal']}"
            )
    elif listing.type == "koop":
        maandlast = listing.maandlast_koop
        if maandlast is not None and maandlast > c["koop_maandlast_max"]:
            redenen.append(
                f"Koop-maandlast EUR {maandlast} boven grens van EUR {c['koop_maandlast_max']}"
            )

    return redenen


def _locatie_toegestaan(listing: Listing, criteria: Dict[str, Any]) -> bool:
    toegestaan = [p.lower() for p in criteria.get("toegestane_plaatsen", [])]
    if not toegestaan:
        return True
    velden = " ".join(
        str(v).lower() for v in (listing.plaats, listing.buurt, listing.adres, listing.postcode) if v
    )
    if not velden.strip():
        # Onbekende locatie: niet hard afwijzen, wel als waarschuwing elders.
        return True
    return any(plaats in velden for plaats in toegestaan)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def score_listing(listing: Listing, config: Dict[str, Any]) -> Listing:
    """
    Bereken maandlast (koop), pas harde filters toe, scoor en deel in.
    Vult listing.score, .indeling, .redenen, .waarschuwingen, .afwijs_redenen.
    """
    listing.id = listing.id or listing.bereken_id()

    # Koop: eerst maandlast berekenen (nodig voor budgetfilter).
    if listing.type == "koop":
        bereken_koop_maandlast(listing, config)

    # Harde filters
    afwijs = harde_filters(listing, config)
    listing.afwijs_redenen = afwijs

    s = config["scoring"]
    punten = float(s["basis"])
    redenen: List[str] = []
    waarschuwingen: List[str] = []

    # --- Bonuspunten ---
    b = s["bonus"]

    marge = _budget_marge(listing, config)
    if marge is not None:
        if marge >= 0.15:
            punten += b["ruim_binnen_budget"]
            redenen.append(f"Ruim binnen budget ({int(marge * 100)}% onder de grens)")
        elif marge >= 0.05:
            punten += b["licht_binnen_budget"]
            redenen.append(f"Binnen budget ({int(marge * 100)}% onder de grens)")

    if listing.slaapkamers and listing.slaapkamers > 1:
        extra = min(
            (listing.slaapkamers - 1) * b["extra_slaapkamer"],
            b["extra_slaapkamer_max"],
        )
        punten += extra
        redenen.append(f"{listing.slaapkamers} slaapkamers")

    if listing.buitenruimte:
        punten += b["buitenruimte"]
        soort = listing.buitenruimte_soort or "buitenruimte"
        redenen.append(f"Buitenruimte ({soort})")

    if listing.parkeren:
        punten += b["parkeren"]
        redenen.append("Parkeerplek of vergunninggebied")

    if _nabij_ov(listing, config):
        punten += b["nabij_ov"]
        redenen.append("Nabij NS/metro, goede OV-verbinding")

    if listing.oppervlak_m2 and listing.oppervlak_m2 >= b["groot_oppervlak_drempel_m2"]:
        punten += b["groot_oppervlak"]
        redenen.append(f"Ruim woonoppervlak ({listing.oppervlak_m2} m2)")

    if listing.energielabel and listing.energielabel[0].upper() in ("A", "B", "C"):
        punten += b["gunstig_energielabel"]
        redenen.append(f"Gunstig energielabel ({listing.energielabel})")

    # --- Strafpunten / waarschuwingen ---
    st = s["straf"]

    if listing.type == "koop" and listing.erfpacht:
        if "lopend" in listing.erfpacht.lower() or "canon" in listing.erfpacht.lower():
            punten -= st["lopende_erfpachtcanon"]
            canon = (
                f" (EUR {listing.erfpacht_canon_per_jaar}/jaar)"
                if listing.erfpacht_canon_per_jaar else ""
            )
            waarschuwingen.append(f"Lopende erfpachtcanon{canon}")

    if listing.tijdelijk_contract:
        punten -= st["tijdelijk_contract"]
        waarschuwingen.append("Tijdelijk contract")

    if listing.servicekosten and listing.servicekosten > st["hoge_servicekosten_drempel"]:
        punten -= st["hoge_servicekosten"]
        waarschuwingen.append(f"Hoge servicekosten (EUR {listing.servicekosten}/mnd)")

    if listing.type == "huur" and listing.vrije_sector_bevestigd is not True:
        punten -= st["twijfel_vrije_sector"]
        waarschuwingen.append("Onduidelijk of dit echt vrije sector is")

    if listing.inkomenseis and listing.prijs:
        if listing.inkomenseis > st["inkomenseis_factor"] * listing.prijs:
            punten -= st["hoge_inkomenseis"]
            waarschuwingen.append(f"Hoge inkomenseis (EUR {listing.inkomenseis}/mnd)")

    if not (listing.plaats or listing.buurt or listing.adres):
        waarschuwingen.append("Locatie onbekend, controleer bij de bron")

    # Vermoedelijk sociale/gereguleerde huur: opvallend lage prijs per m² (of
    # absoluut lage huur). Niet afwijzen, wel labelen — zulke woningen vergen
    # meestal inschrijving (WoningNet) en een inkomenstoets.
    if _mogelijk_gereguleerd(listing, config):
        listing.mogelijk_gereguleerd = True
        punten -= st.get("mogelijk_sociale_huur", 1)
        waarschuwingen.append(
            "Mogelijk sociale/gereguleerde huur (lage prijs per m²) — "
            "vaak inschrijving en inkomenseis"
        )

    # Schaal naar 1-10
    score = max(1.0, min(10.0, punten))
    listing.score = round(score, 1)
    listing.redenen = redenen
    listing.waarschuwingen = waarschuwingen

    # Indeling
    listing.indeling = _indeling(listing, config)
    return listing


def _mogelijk_gereguleerd(listing: Listing, config: Dict[str, Any]) -> bool:
    """Heuristiek voor sociale/gereguleerde huur op basis van prijsniveau.

    Amsterdamse vrije-sector huur ligt rond €25-35/m²/maand; sociale en
    corporatiehuur rond €10-15/m². Een lage prijs per m² (of een absoluut lage
    kale huur als het oppervlak ontbreekt) is dus een sterk signaal.
    """
    if listing.type != "huur" or not listing.prijs:
        return False
    c = config.get("criteria", {})
    per_m2_drempel = c.get("sociale_huur_prijs_per_m2", 18)
    huur_drempel = c.get("sociale_huur_kale_huur", 700)
    if listing.oppervlak_m2 and listing.oppervlak_m2 > 0:
        return (listing.prijs / listing.oppervlak_m2) < per_m2_drempel
    return listing.prijs < huur_drempel


def _budget_marge(listing: Listing, config: Dict[str, Any]) -> float | None:
    """Fractie onder de budgetgrens (0.2 = 20% onder de grens)."""
    c = config["criteria"]
    if listing.type == "huur" and listing.prijs:
        grens = c["huur_max_kaal"]
        return (grens - listing.prijs) / grens
    if listing.type == "koop" and listing.maandlast_koop:
        grens = c["koop_maandlast_max"]
        return (grens - listing.maandlast_koop) / grens
    return None


def _nabij_ov(listing: Listing, config: Dict[str, Any]) -> bool:
    trefwoorden = [t.lower() for t in config["criteria"].get("ov_knooppunten_trefwoorden", [])]
    velden = " ".join(
        str(v).lower() for v in (listing.buurt, listing.plaats, listing.adres, listing.titel) if v
    )
    return any(t in velden for t in trefwoorden)


def _indeling(listing: Listing, config: Dict[str, Any]) -> str:
    if listing.afwijs_redenen:
        return "afgewezen"
    ind = config["scoring"]["indeling"]
    if listing.score >= ind["topmatch_min"]:
        return "topmatch"
    if listing.score >= ind["lage_match_min"]:
        return "lage_match"
    return "afgewezen"


def score_alles(listings: List[Listing], config: Dict[str, Any]) -> List[Listing]:
    return [score_listing(l, config) for l in listings]
