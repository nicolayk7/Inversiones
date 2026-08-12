"""Loader for the frozen, versioned score weights (architecture v1.0, rule 9).

Weights live in config/weights/{version}.yaml as static, human-edited files.
This module only loads and validates them — it has no code path that lets a
caller construct a WeightsSet from anything other than a version file on
disk, which is the point: an LLM agent can *read* a WeightsSet, it cannot
produce one.

Immutability is enforced at two levels, not one:
- `WeightsSet` is a frozen dataclass, so `weights.wealth = {...}` raises.
- Each group is a `MappingProxyType` over a private copy of the parsed dict,
  so `weights.wealth["quality"] = 0.99` also raises — a frozen dataclass
  alone does NOT stop that; it only blocks reassigning the field itself, not
  mutating the mutable object the field points to.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import yaml

WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "config" / "weights"

_GROUPS = ("wealth", "trading", "options", "opportunity")

WeightsGroup = MappingProxyType[str, float]


class WeightsValidationError(ValueError):
    pass


@dataclass(frozen=True)
class WeightsSet:
    version: str
    wealth: WeightsGroup
    trading: WeightsGroup
    options: WeightsGroup
    opportunity: WeightsGroup


def _validate_sums_to_one(group: str, weights: dict[str, float], tol: float = 1e-6) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > tol:
        raise WeightsValidationError(
            f"weights['{group}'] must sum to 1.0, got {total} — check config/weights file"
        )


@lru_cache(maxsize=None)
def load_weights(version: str = "v1.0") -> WeightsSet:
    path = WEIGHTS_DIR / f"{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No frozen weights file for version {version!r} at {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    missing = [g for g in _GROUPS if g not in data]
    if missing:
        raise WeightsValidationError(f"{path} is missing weight group(s): {missing}")

    for group in _GROUPS:
        _validate_sums_to_one(group, data[group])

    return WeightsSet(
        version=data.get("version", version),
        wealth=MappingProxyType(dict(data["wealth"])),
        trading=MappingProxyType(dict(data["trading"])),
        options=MappingProxyType(dict(data["options"])),
        opportunity=MappingProxyType(dict(data["opportunity"])),
    )
