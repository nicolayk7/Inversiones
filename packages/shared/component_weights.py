"""Loader for sub-metric ("component") weights within one Wealth top-level group
(quality/growth/fcf/valuation) — the architecture approved in the Phase 1B design closure
(docs/wealth-engine-phase1b-implementation-spec.md §0.2), mirroring `packages/shared/weights.py`'s
pattern for the frozen top-level weights.

**No production weight file exists.** This module's job is to make the composition layer callable
end-to-end without embedding a single production sub-metric weight number in code — every file it
loads must declare its own `status: PROVISIONAL | APPROVED` explicitly, and a PROVISIONAL file is
refused outright in a production configuration (rule 6 of the Phase 1B implementation
authorization). There is no code path in this module that can silently invent or default a weight
value — a missing file raises `FileNotFoundError`, not a fallback.
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import yaml

from packages.shared.config import settings

COMPONENT_WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "config" / "weights" / "wealth_components"

# The four Wealth top-level groups that decompose into sub-metrics per the methodology's §14
# pseudocode. Moat is intentionally absent — MOAT_SCORE aggregation is fully deferred (Phase 1B
# decision 8), so it never reaches this loader.
_GROUPS = ("quality", "growth", "fcf", "valuation")


class ComponentWeightsValidationError(ValueError):
    pass


class ProvisionalWeightsRejectedError(ComponentWeightsValidationError):
    """Raised when a PROVISIONAL weight file is loaded under a production configuration."""


class WeightApprovalStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"


@dataclass(frozen=True)
class ComponentWeightsSet:
    group: str
    version: str
    status: WeightApprovalStatus
    weights: MappingProxyType


def _validate_sums_to_one(group: str, weights: dict[str, float], tol: float = 1e-6) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > tol:
        raise ComponentWeightsValidationError(
            f"component weights for group={group!r} must sum to 1.0, got {total}"
        )


@lru_cache(maxsize=None)
def load_component_weights(
    group: str, version: str = "v1.0", *, allow_provisional: bool | None = None
) -> ComponentWeightsSet:
    """Load sub-metric weights for one Wealth component group.

    `allow_provisional`: if `None` (default), derived from `settings.env != "production"` — i.e.
    a production environment rejects PROVISIONAL files automatically (rule 6), while dev/local/CI
    accept them so the pipeline stays executable and testable (rule 5). Pass an explicit bool to
    override for a specific call (e.g. a test that wants to assert the rejection itself).
    """
    if group not in _GROUPS:
        raise ComponentWeightsValidationError(
            f"unknown component weight group {group!r}; expected one of {_GROUPS}"
        )

    path = COMPONENT_WEIGHTS_DIR / f"{group}_{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No sub-metric weight file for group={group!r} version={version!r} at {path}. "
            "Production sub-metric weight VALUES are not approved (Phase 1B design decision #1, "
            "§0.2 of the implementation spec) — this is the expected state until a real, "
            "calibrated file is authored and approved through this same architecture."
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    status_raw = data.get("status")
    try:
        status = WeightApprovalStatus(status_raw)
    except ValueError as exc:
        raise ComponentWeightsValidationError(
            f"{path} must declare status: PROVISIONAL or APPROVED explicitly, got {status_raw!r}"
        ) from exc

    if allow_provisional is None:
        allow_provisional = settings.env != "production"

    if status is WeightApprovalStatus.PROVISIONAL and not allow_provisional:
        raise ProvisionalWeightsRejectedError(
            f"{path} is PROVISIONAL — refusing to load under a production configuration "
            f"(settings.env={settings.env!r}). Production requires an APPROVED weight file; "
            "PROVISIONAL weights exist only to make the pipeline executable/testable in "
            "development (rule 5 of the Phase 1B implementation authorization), never as a "
            "stand-in for an approved methodology value."
        )

    weights = data.get("weights")
    if not weights:
        raise ComponentWeightsValidationError(f"{path} has no 'weights' mapping")
    _validate_sums_to_one(group, weights)

    return ComponentWeightsSet(
        group=group,
        version=data.get("version", version),
        status=status,
        weights=MappingProxyType(dict(weights)),
    )
