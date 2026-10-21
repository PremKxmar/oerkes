"""Loads the per-merger YAML file. The file name is the correlationId."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.getenv("MERGER_CONFIG_DIR", ROOT / "config" / "mergers"))

RISK_ORDER = ["LOW", "MEDIUM", "HIGH"]


@lru_cache(maxsize=None)
def load_merger(correlation_id):
    path = CONFIG_DIR / f"{correlation_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No merger config at {path}. The correlationId must match a file in {CONFIG_DIR}.")
    with open(path) as f:
        return yaml.safe_load(f)


def max_risk(*risks):
    known = [r for r in risks if r in RISK_ORDER]
    return max(known, key=RISK_ORDER.index) if known else "LOW"
