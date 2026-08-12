"""Point-in-time correctness of `packages.storage.repositories.prices_repository` against a real
Postgres (infra/docker-compose.yml). Uses a synthetic ticker so it never touches real price data.

Central invariant under test throughout: `available_at <= as_of`, never `ts <= as_of`. `ts` is the
trading day a bar describes; `available_at` is when *this system* could have known it — they are
never assumed equal (see `OHLCVBar`'s docstring and `prices_repository`'s PIT-decision docstring).
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, select

from packages.shared.schemas import OHLCVBar
from packages.storage.db import SessionLocal
from packages.storage.models.prices import PriceBarModel
from packages.storage.repositories import prices_repository as repo

pytestmark = pytest.mark.integration

TICKER = "TESTPX"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _bar(ts: str, available_at: str, close: float, source: str = "test") -> OHLCVBar:
    return OHLCVBar(
        ticker=TICKER, ts=date.fromisoformat(ts), open=close, high=close, low=close,
        close=close, volume=1000, available_at=_dt(available_at), source=source,
    )


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s
    async with SessionLocal() as cleanup:
        await cleanup.execute(delete(PriceBarModel).where(PriceBarModel.ticker == TICKER))
        await cleanup.commit()


# -- Test 1 — future knowledge excluded ------------------------------------------------------


async def test_future_available_at_is_excluded(session):
    bar = _bar(ts="2025-06-10", available_at="2025-06-10T21:00:00", close=100.0)
    await repo.save_daily_bars(session, [bar])

    result = await repo.get_price_as_of(session, TICKER, _dt("2025-06-10T20:00:00"))
    assert result is None  # available_at (21:00) > as_of (20:00): not yet knowable


# -- Test 2 — eligible data is returned ------------------------------------------------------


async def test_eligible_bar_is_returned(session):
    bar = _bar(ts="2025-06-10", available_at="2025-06-10T21:00:00", close=100.0)
    await repo.save_daily_bars(session, [bar])

    result = await repo.get_price_as_of(session, TICKER, _dt("2025-06-10T22:00:00"))
    assert result is not None
    assert result.close == 100.0
    assert result.ts.isoformat() == "2025-06-10"


# -- Test 3 — correct selection among several eligible bars ----------------------------------


async def test_selects_latest_eligible_ts_not_a_future_one(session):
    """Same conceptual guarantee `quant_core.backtest.latest_eligible` encodes (pick the latest
    eligible record, never a future one) — validated here at the repository/SQL level, since this
    repository does not call `latest_price_as_of` (see its module docstring: that helper keys on
    `ts` only and would be PIT-incorrect against bars that carry a real `available_at`)."""
    older = _bar(ts="2025-06-09", available_at="2025-06-09T21:00:00", close=98.0)
    newer = _bar(ts="2025-06-10", available_at="2025-06-10T21:00:00", close=100.0)
    future = _bar(ts="2025-06-11", available_at="2025-06-11T21:00:00", close=105.0)
    await repo.save_daily_bars(session, [older, newer, future])

    result = await repo.get_price_as_of(session, TICKER, _dt("2025-06-10T22:00:00"))
    assert result.close == 100.0  # newer, not future — future's available_at exceeds as_of


# -- Test 4 — ts ordering alone is not sufficient ---------------------------------------------


async def test_delayed_publication_means_ts_ordering_alone_is_wrong(session):
    """The exact bug `available_at <= as_of` exists to prevent: a bar for an EARLIER trading day
    published LATE must not be treated as knowable just because its `ts` precedes `as_of`.

    Friday's close (ts=06-13) is delayed 3 days (vendor issue) — not available until 06-17.
    Monday's close (ts=06-16) reports same-day. Querying as_of=06-15 (after Monday's ts but
    before Friday's late publication) must return NOTHING — not Friday's bar, even though
    06-13 <= 06-15. `latest_price_as_of` (which filters on `.ts`) would have wrongly returned
    Friday's bar here; this repository's `available_at`-keyed filter correctly excludes it."""
    friday_delayed = _bar(ts="2025-06-13", available_at="2025-06-17T21:00:00", close=100.0)
    await repo.save_daily_bars(session, [friday_delayed])

    result = await repo.get_price_as_of(session, TICKER, _dt("2025-06-15T12:00:00"))
    assert result is None  # NOT friday_delayed — its available_at (06-17) is still in the future

    # Once as_of reaches the real publication moment, it becomes correctly eligible.
    result_after_publication = await repo.get_price_as_of(session, TICKER, _dt("2025-06-17T22:00:00"))
    assert result_after_publication is not None
    assert result_after_publication.ts.isoformat() == "2025-06-13"


# -- Test 5 — idempotency ----------------------------------------------------------------------


async def test_save_is_idempotent_on_same_vintage(session):
    bar = _bar(ts="2025-06-10", available_at="2025-06-10T21:00:00", close=100.0)
    await repo.save_daily_bars(session, [bar])
    await repo.save_daily_bars(session, [bar])  # re-ingest, identical vintage

    count = await session.execute(
        select(PriceBarModel).where(PriceBarModel.ticker == TICKER, PriceBarModel.ts == date(2025, 6, 10))
    )
    assert len(count.scalars().all()) == 1


# -- Test 6 — multiple sources/vintages never silently overwrite each other -------------------


async def test_multiple_vintages_same_ts_coexist_not_overwritten(session):
    original = _bar(ts="2025-06-10", available_at="2025-06-10T21:00:00", close=100.0, source="vendor_a")
    correction = _bar(ts="2025-06-10", available_at="2025-06-11T13:00:00", close=101.0, source="vendor_a")
    other_source = _bar(ts="2025-06-10", available_at="2025-06-10T21:05:00", close=100.5, source="vendor_b")
    await repo.save_daily_bars(session, [original, correction, other_source])

    rows = await session.execute(
        select(PriceBarModel).where(PriceBarModel.ticker == TICKER, PriceBarModel.ts == date(2025, 6, 10))
    )
    assert len(rows.scalars().all()) == 3  # all three vintages persisted, none overwritten

    # As of right after the original prints (before the correction/other source), only original
    # is eligible.
    just_after_original = await repo.get_price_as_of(session, TICKER, _dt("2025-06-10T21:02:00"))
    assert just_after_original.close == 100.0

    # As of after all three, the query returns *a* most-recently-known vintage for that ts (which
    # specific source wins when several are simultaneously eligible for the same ts is an OPEN,
    # unresolved question — source-priority policy is out of scope for Phase 2). What's under
    # test here is only that no data was silently destroyed, not which source is authoritative.
    after_all = await repo.get_price_as_of(session, TICKER, _dt("2025-06-12T00:00:00"))
    assert after_all is not None
    assert after_all.close in (101.0, 100.5)


# -- Test 7 — explicit no-look-ahead scenario, mixed ts/available_at ordering ------------------


async def test_no_look_ahead_across_out_of_order_publication(session):
    """Bars arrive out of ts-order relative to their available_at: an older ts published late,
    and a newer ts published promptly. A query at each of three distinct as_of moments must only
    ever see what was truly knowable at that moment — never information whose available_at is
    later than as_of, regardless of how ts values relate to each other."""
    bar_a = _bar(ts="2025-06-10", available_at="2025-06-14T21:00:00", close=100.0)  # delayed
    bar_b = _bar(ts="2025-06-12", available_at="2025-06-12T21:00:00", close=103.0)  # prompt
    await repo.save_daily_bars(session, [bar_a, bar_b])

    # Before either is known.
    assert await repo.get_price_as_of(session, TICKER, _dt("2025-06-11T00:00:00")) is None

    # Only bar_b (prompt, ts=06-12) is known; bar_a (ts=06-10) is NOT, despite its earlier ts.
    mid = await repo.get_price_as_of(session, TICKER, _dt("2025-06-13T00:00:00"))
    assert mid is not None
    assert mid.ts.isoformat() == "2025-06-12"
    assert mid.close == 103.0

    # After bar_a's delayed publication, it becomes the latest known ts... but bar_b's ts is
    # still later, so bar_b remains the correct answer — bar_a becoming known does not change
    # which ts is most recent.
    late = await repo.get_price_as_of(session, TICKER, _dt("2025-06-15T00:00:00"))
    assert late is not None
    assert late.ts.isoformat() == "2025-06-12"
