"""Black-Scholes pricing, greeks, IV rank, expected move. Implemented starting Phase 1 — Options
Intelligence v1 is part of the MVP thin-slice (architecture v1.0, decision #1), scoped to Long
Call / Long Put / Debit Spread. Additional strategies (Bull Put Spread, Iron Condor, ...) are
Phase 2."""


def black_scholes_greeks(
    spot: float, strike: float, days_to_expiry: int, iv: float, rate: float, option_type: str
) -> dict[str, float]:
    raise NotImplementedError("Options Intelligence — Phase 1")


def expected_move(spot: float, iv: float, days_to_expiry: int) -> float:
    raise NotImplementedError("Options Intelligence — Phase 1")


def iv_rank(current_iv: float, iv_history: list[float]) -> float:
    raise NotImplementedError("Options Intelligence — Phase 1")

