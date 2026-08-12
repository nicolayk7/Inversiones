"""MetricResult — the value/status/reason contract every Quant Core calculation returns instead
of a bare float, so "why is this missing" survives to the caller instead of collapsing into an
ambiguous `None` (Phase 1B implementation spec §6, §11.1). No Quant Core function returns a bare
`float | None`; every one returns (or is composed from) a MetricResult.

Five statuses, matching distinct methodology concepts that must never collapse into one another:
- OK — computed normally.
- N/A — a hard rule says this metric doesn't apply / can't be computed (e.g. ROE with equity <= 0,
  C3; FCF Conversion with NI <= 0, C2).
- LOW_RELIABILITY — computed, but flagged as thin/unstable (e.g. ROE soft floor, C3). Never reused
  for "a whole methodology component is missing" (spec §5, BalanceSheetMultiplier decision).
- INSUFFICIENT_DATA — group coverage fell below the configured threshold (§13).
- UNSUPPORTED — a sector gate or an unimplemented/blocked methodology component blocks this
  metric entirely (e.g. ROIC for a Bank; WEALTH_SCORE while BalanceSheetMultiplier is blocked).
"""

from enum import StrEnum

from pydantic import BaseModel


class MetricStatus(StrEnum):
    OK = "OK"
    NA = "N/A"
    LOW_RELIABILITY = "LOW_RELIABILITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNSUPPORTED = "UNSUPPORTED"


class MetricResult(BaseModel):
    value: float | None = None
    status: MetricStatus
    reason: str | None = None

    @classmethod
    def ok(cls, value: float) -> "MetricResult":
        return cls(value=value, status=MetricStatus.OK)

    @classmethod
    def na(cls, reason: str) -> "MetricResult":
        return cls(value=None, status=MetricStatus.NA, reason=reason)

    @classmethod
    def low_reliability(cls, value: float, reason: str) -> "MetricResult":
        return cls(value=value, status=MetricStatus.LOW_RELIABILITY, reason=reason)

    @classmethod
    def insufficient_data(cls, reason: str) -> "MetricResult":
        return cls(value=None, status=MetricStatus.INSUFFICIENT_DATA, reason=reason)

    @classmethod
    def unsupported(cls, reason: str) -> "MetricResult":
        return cls(value=None, status=MetricStatus.UNSUPPORTED, reason=reason)

    @property
    def is_ok(self) -> bool:
        return self.status == MetricStatus.OK
