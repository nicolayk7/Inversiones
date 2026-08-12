"""Massive (formerly Polygon.io) `MarketDataProvider` adapter — implements
`get_daily_bars(ticker, start, end) -> list[OHLCVBar]` against Massive's daily aggregates
endpoint. Market Data Foundation Phase 3: adapter only. No Storage, no ingestion orchestration,
no Wealth Engine wiring — `packages/storage/repositories/prices_repository.py` (Phase 2) is not
touched or called from here; that wiring is a separate, not-yet-authorized phase.

Endpoint (confirmed against massive.com's own docs, reached during this pass):
    GET https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
        ?adjusted=true&sort=asc&limit=50000&apiKey=...

Confirmed from the official docs:
- Base host `api.massive.com` — confirmed via the sample response's own `next_url` field, not
  guessed.
- Each `results[]` entry's `t` is "the Unix millisecond timestamp for the start of the aggregate
  window", in Eastern Time. Sample from the docs: `t=1577941200000` for a bar the docs describe
  as the 2020-01-02 trading day.
- `adjusted` (query param, default `true`) applies **split** adjustment to OHLC; docs did not
  mention dividend adjustment as part of this flag at all — there is no dividend-adjusted-close
  concept in this endpoint's response, so none is invented here.
- Response also carries `vw` (volume-weighted average price) and `n` (transaction count) per
  bar — both ignored here. The canonical `OHLCVBar` has no field for either, and this pass does
  not widen the DTO (out of scope — continuity brief's "no amplíes el DTO sin autorización").

Explicit, disclosed choice — `adjusted=true` is passed explicitly, not left to the documented
default: this system has no CorporateAction/split-handling pipeline yet (CLAUDE.md: "buyback y
M&A todavía no tienen representación aprobada"), so unadjusted OHLC would create silent price
discontinuities across a real split with nothing downstream able to reconcile them. Split-adjusted
series is the only choice that doesn't require a pipeline this system does not have.

NOT confirmed by the docs pages reached during this pass (disclosed, not guessed):
- The response shape / status code for a genuinely invalid or nonexistent ticker, as distinct
  from a valid ticker with zero bars in the requested range. Neither failure mode was shown with
  an example. This adapter treats `status != "OK"` as an error (surfacing the body's own message
  where present) and an `OK` response with an empty/absent `results` list as "no data for this
  range" — a valid, non-error outcome. That is the only distinction the confirmed schema supports.
- The exact JSON body shape of an authentication-failure response. 401/403 status codes for a
  missing/invalid API key are confirmed; the body shape was not shown in the pages reached, so
  this adapter reports the HTTP status only, never a guessed body field.

available_at provenance: ASSUMED / CONVENTION — NOT provider-supplied.
Massive's aggregates response carries no publication-lag or "available since" field anywhere —
only `t`, the window's start. `available_at` is therefore derived, not read, using the same
disclosed convention `packages.providers.fundamentals.sec_edgar` already applies to filing dates:
treat the trading day as available at end-of-day UTC. This is deliberately conservative, not
optimistic — daily bars are in practice available within hours of the 4pm ET close, well before
23:59:59 UTC the same calendar date — so this convention never claims the data was knowable
earlier than it plausibly was. `ts` (the trading day) and `available_at` are never collapsed into
each other; see the two computed independently in `_to_bar` below.
"""

from datetime import date, datetime, time, timezone

import httpx

from packages.shared.config import settings
from packages.shared.schemas import OHLCVBar

_AGGS_URL = "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"


class MassiveProviderError(RuntimeError):
    """Base for every error this adapter raises — never silently swallowed into an empty or
    fabricated result."""


class MassiveAuthError(MassiveProviderError):
    """Missing or rejected API key (HTTP 401/403, or no key configured at all)."""


class MassiveRateLimitError(MassiveProviderError):
    """HTTP 429 — subscription-tier rate limit exceeded."""


class MassiveResponseError(MassiveProviderError):
    """Response did not match the confirmed schema (non-"OK" status, missing `results`, or a
    result entry missing a required OHLC field) — never fabricate an `OHLCVBar` from it."""


def _end_of_day_utc(d: date) -> datetime:
    # See module docstring's "available_at provenance" section. Mirrors
    # packages.providers.fundamentals.sec_edgar's _available_at convention exactly.
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


class MassiveMarketDataProvider:
    def __init__(self, client: httpx.Client | None = None, api_key: str | None = None):
        self._api_key = api_key if api_key is not None else settings.massive_api_key
        if not self._api_key:
            raise MassiveAuthError(
                "No Massive API key configured — set MASSIVE_API_KEY in .env "
                "(packages.shared.config.Settings.massive_api_key)"
            )
        self._client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MassiveMarketDataProvider":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- MarketDataProvider ----------------------------------------------------------------

    def get_daily_bars(self, ticker: str, start: date, end: date) -> list[OHLCVBar]:
        url = _AGGS_URL.format(ticker=ticker, start=start.isoformat(), end=end.isoformat())
        response = self._client.get(
            url,
            params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": self._api_key},
        )

        if response.status_code in (401, 403):
            raise MassiveAuthError(
                f"Massive authentication failed (HTTP {response.status_code}) for {ticker!r}"
            )
        if response.status_code == 429:
            raise MassiveRateLimitError(f"Massive rate limit exceeded (HTTP 429) fetching {ticker!r}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MassiveProviderError(
                f"Massive request failed for {ticker!r}: HTTP {response.status_code}"
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise MassiveResponseError(f"Massive returned a non-JSON response for {ticker!r}") from exc

        status = body.get("status")
        if status != "OK":
            raise MassiveResponseError(
                f"Massive returned status={status!r} for {ticker!r}: "
                f"{body.get('error') or body.get('message') or '(no message in response body)'}"
            )

        results = body.get("results")
        if results is None:
            raise MassiveResponseError(
                f"Massive response for {ticker!r} has no 'results' key — malformed response"
            )
        if not results:
            return []  # genuinely no bars in this range — not an error, not fabricated data

        return [self._to_bar(ticker, entry) for entry in results]

    def _to_bar(self, ticker: str, entry: dict) -> OHLCVBar:
        required = ("o", "h", "l", "c", "v", "t")
        missing = [f for f in required if f not in entry]
        if missing:
            raise MassiveResponseError(
                f"Massive result entry for {ticker!r} is missing field(s) {missing} — refusing to "
                "fabricate a bar from an incomplete entry"
            )

        # t: Unix ms timestamp for the START of the aggregate window (confirmed — see module
        # docstring). ET is always behind UTC (4h EDT / 5h EST) and never crosses past midnight
        # into the next UTC calendar date, so ET midnight always falls within the SAME UTC date —
        # taking this timestamp's UTC date directly yields the correct ET trading day, with no
        # timezone-conversion dependency needed. Verified against the docs' own sample:
        # t=1577941200000 -> 2020-01-02T05:00:00Z -> date 2020-01-02, the trading day the docs'
        # example describes.
        window_start_utc = datetime.fromtimestamp(entry["t"] / 1000, tz=timezone.utc)
        trading_day = window_start_utc.date()

        return OHLCVBar(
            ticker=ticker,
            ts=trading_day,
            open=float(entry["o"]),
            high=float(entry["h"]),
            low=float(entry["l"]),
            close=float(entry["c"]),
            volume=int(entry["v"]),
            available_at=_end_of_day_utc(trading_day),
            source="massive",
        )
