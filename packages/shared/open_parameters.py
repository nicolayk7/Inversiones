"""Loader for the methodology's Category B "architecture approved, parameter OPEN" numeric
constants (docs/wealth-engine-methodology.md §26, and the canonical table in
docs/wealth-engine-phase1b-implementation-spec.md §14) — e.g. the ROE soft floor, leverage bands,
winsorization bounds, the H4 margin-expansion threshold, the group-coverage minimum.

Every value in the shipped `open_parameters_v1.0.yaml` file is the **same illustrative value
already logged as OPEN** in the methodology — nothing here is a new number, and loading it does
not make it approved. The file is `status: PROVISIONAL` for that reason and is rejected under a
production configuration exactly like `packages/shared/component_weights.py`'s sub-metric
weights (rule 6) — these are two independent BLOCKED-value categories (sub-metric weights have
no illustrative value at all; OPEN parameters have an illustrative one that still needs
empirical calibration), so they get parallel, not shared, loaders.
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from packages.shared.config import settings

OPEN_PARAMETERS_DIR = Path(__file__).resolve().parents[2] / "config" / "wealth_engine"


class OpenParametersValidationError(ValueError):
    pass


class ProvisionalOpenParametersRejectedError(OpenParametersValidationError):
    pass


class WeightApprovalStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"


@dataclass(frozen=True)
class OpenParametersSet:
    version: str
    status: WeightApprovalStatus
    values: MappingProxyType

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@lru_cache(maxsize=None)
def load_open_parameters(
    version: str = "v1.0", *, allow_provisional: bool | None = None
) -> OpenParametersSet:
    path = OPEN_PARAMETERS_DIR / f"open_parameters_{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No OPEN-parameters file for version={version!r} at {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    status_raw = data.get("status")
    try:
        status = WeightApprovalStatus(status_raw)
    except ValueError as exc:
        raise OpenParametersValidationError(
            f"{path} must declare status: PROVISIONAL or APPROVED explicitly, got {status_raw!r}"
        ) from exc

    if allow_provisional is None:
        allow_provisional = settings.env != "production"

    if status is WeightApprovalStatus.PROVISIONAL and not allow_provisional:
        raise ProvisionalOpenParametersRejectedError(
            f"{path} is PROVISIONAL — refusing to load under a production configuration "
            f"(settings.env={settings.env!r}). Every value in it is still logged OPEN in the "
            "methodology (§26) and requires empirical calibration before production use."
        )

    values = data.get("values")
    if not values:
        raise OpenParametersValidationError(f"{path} has no 'values' mapping")

    return OpenParametersSet(
        version=data.get("version", version),
        status=status,
        values=MappingProxyType(dict(values)),
    )
