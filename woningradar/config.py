"""Configuratie inladen vanuit config.yaml."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict

import yaml

# Pad naar config.yaml (repo-root, een niveau boven deze module).
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.yaml",
)


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> Dict[str, Any]:
    """Laad en cache de configuratie."""
    path = path or os.environ.get("WONINGRADAR_CONFIG", DEFAULT_CONFIG_PATH)
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    import json

    print(json.dumps(load_config(), indent=2, ensure_ascii=False))
