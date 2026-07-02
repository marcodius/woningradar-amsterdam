"""Orchestrator: haalt alle bronnen op, normaliseert, ontdubbelt, scoort en
schrijft docs/listings.json voor de frontend.

Gebruik:
    python -m woningradar.run
    python -m woningradar.run --config pad/naar/config.yaml --out docs/listings.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from .config import DEFAULT_CONFIG_PATH, load_config
from .dedup import dedup
from .scoring import score_alles
from .sources import haal_alles_op

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO_ROOT, "docs", "listings.json")

# Amsterdamse tijd (CEST in de zomer). Voor weergave in de frontend.
TZ = timezone(timedelta(hours=2))


def _volgende_run(nu: datetime, interval_uren: int = 3) -> datetime:
    """Schat het volgende geplande moment (afgerond op het interval)."""
    volgende_uur = ((nu.hour // interval_uren) + 1) * interval_uren
    basis = nu.replace(minute=0, second=0, microsecond=0)
    return basis.replace(hour=0) + timedelta(hours=volgende_uur)


def main() -> None:
    parser = argparse.ArgumentParser(description="Woningradar scraper")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--interval-uren", type=int, default=3)
    args = parser.parse_args()

    config = load_config(args.config)

    print("Bronnen ophalen...")
    ruwe, status = haal_alles_op(config)
    print(f"Opgehaald: {len(ruwe)} woningen. Status per bron:")
    for bron, st in status.items():
        print(f"  - {bron}: {st}")

    # Ontdubbelen op adres/kenmerken.
    uniek = dedup(ruwe)
    print(f"Na ontdubbeling: {len(uniek)} woningen.")

    # Scoren en indelen.
    gescoord = score_alles(uniek, config)

    # Sorteren: eerst topmatches, dan op score aflopend.
    volgorde = {"topmatch": 0, "lage_match": 1, "afgewezen": 2}
    gescoord.sort(key=lambda l: (volgorde.get(l.indeling, 9), -(l.score or 0)))

    tellers = {
        "opgehaald": len(ruwe),
        "uniek": len(uniek),
        "topmatch": sum(1 for l in gescoord if l.indeling == "topmatch"),
        "lage_match": sum(1 for l in gescoord if l.indeling == "lage_match"),
        "afgewezen": sum(1 for l in gescoord if l.indeling == "afgewezen"),
    }

    nu = datetime.now(TZ)
    payload = {
        "bijgewerkt": nu.isoformat(timespec="minutes"),
        "volgende_run": _volgende_run(nu, args.interval_uren).isoformat(timespec="minutes"),
        "bron_status": status,
        "tellers": tellers,
        "criteria": {
            "huur_max_kaal": config["criteria"]["huur_max_kaal"],
            "koop_maandlast_max": config["criteria"]["koop_maandlast_max"],
        },
        "hypotheek": {
            "rente_jaarlijks": config["hypotheek"]["rente_jaarlijks"],
            "looptijd_jaren": config["hypotheek"]["looptijd_jaren"],
        },
        "woningen": [l.to_dict() for l in gescoord],
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"\nGeschreven naar {args.out}")
    print(
        f"Topmatches: {tellers['topmatch']} | "
        f"Lage matches: {tellers['lage_match']} | "
        f"Afgewezen: {tellers['afgewezen']}"
    )


if __name__ == "__main__":
    main()
