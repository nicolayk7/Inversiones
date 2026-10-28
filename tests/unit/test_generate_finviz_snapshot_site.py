"""scripts/generate_finviz_snapshot_site.py's failure handling — no network: the Finviz provider is
replaced by a fake, and the output dir by a tmp_path. Covers the behaviors added 2026-10-28 after
a transient error killed a whole daily run and a delisted ticker (WBD) silently vanished:
per-ticker failures carry the previous data forward, 404s drop the ticker and its file, full runs
delete orphaned files, and partial runs never delete anything."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_finviz_snapshot_site as gen  # noqa: E402

from packages.providers.fundamentals.finviz import (  # noqa: E402
    FinvizNotFoundError,
    FinvizTransientError,
)

_FIELDS = {"Current stock price": "100.00", "Market capitalization": "1.00B"}


def _bars(n=3, close=100.0):
    return [
        {"date": f"2026-10-{i + 1:02d}", "open": close, "high": close, "low": close, "close": close, "volume": 1}
        for i in range(n)
    ]


class FakeProvider:
    """snapshot_errors / history_errors: ticker -> exception to raise."""

    def __init__(self, snapshot_errors=None, history_errors=None):
        self.snapshot_errors = snapshot_errors or {}
        self.history_errors = history_errors or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get_snapshot(self, ticker):
        if ticker in self.snapshot_errors:
            raise self.snapshot_errors[ticker]
        return {"ticker": ticker, "fields": dict(_FIELDS), "charts": None,
                "categories": {"sector": "Technology"}, "company_name": f"{ticker} Corp"}

    def get_price_history(self, ticker):
        if ticker in self.history_errors:
            raise self.history_errors[ticker]
        return _bars()


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(gen, "_REQUEST_DELAY_SECONDS", 0)
    return tmp_path


def _use(monkeypatch, provider):
    monkeypatch.setattr(gen, "FinvizFundamentalsProvider", lambda: provider)


def _write_previous(out, ticker, age=timedelta(days=1), price_history=None):
    data = {"ticker": ticker, "name": f"{ticker} Old Name",
            "generated_at": (datetime.now(timezone.utc) - age).isoformat(),
            "columns": [[{"label": "Price", "value": "90.00"}]], "price_history": price_history or _bars(5, 90.0)}
    (out / f"{ticker}.json").write_text(json.dumps(data))
    return data


def _read(out, name):
    return json.loads((out / f"{name}.json").read_text())


def test_transient_failure_carries_previous_data_forward(out, monkeypatch):
    previous = _write_previous(out, "FLAKY")
    _use(monkeypatch, FakeProvider(snapshot_errors={"FLAKY": FinvizTransientError("HTTP 503 after 3 attempts")}))

    gen.main(["AAA", "BBB", "FLAKY"])

    index = _read(out, "index")
    assert index["tickers"] == ["AAA", "BBB", "FLAKY"]          # kept, in TICKERS order
    assert index["names"]["FLAKY"] == "FLAKY Old Name"
    assert _read(out, "FLAKY") == previous                       # file untouched, old generated_at
    assert _read(out, "AAA")["name"] == "AAA Corp"


def test_unexpected_exception_on_one_ticker_does_not_abort_the_run(out, monkeypatch):
    _use(monkeypatch, FakeProvider(snapshot_errors={"BAD": KeyError("surprise markup")}))
    gen.main(["AAA", "BBB", "BAD"])
    assert _read(out, "index")["tickers"] == ["AAA", "BBB"]      # no previous file -> skipped


def test_carry_forward_has_an_age_limit(out, monkeypatch):
    _write_previous(out, "OLD", age=timedelta(days=10))
    _use(monkeypatch, FakeProvider(snapshot_errors={"OLD": FinvizTransientError("timeout")}))
    gen.main(["AAA", "BBB", "OLD"])
    assert "OLD" not in _read(out, "index")["tickers"]
    assert not (out / "OLD.json").exists()                       # full run: unlisted file removed


def test_404_drops_the_ticker_and_deletes_its_stale_file(out, monkeypatch):
    _write_previous(out, "WBD")
    _use(monkeypatch, FakeProvider(snapshot_errors={"WBD": FinvizNotFoundError("no quote page")}))
    gen.main(["AAA", "BBB", "WBD"])
    assert "WBD" not in _read(out, "index")["tickers"]
    assert not (out / "WBD.json").exists()


def test_full_run_removes_orphaned_files(out, monkeypatch):
    _write_previous(out, "LEFTINDEX")
    _use(monkeypatch, FakeProvider())
    gen.main(["AAA", "BBB"])
    assert sorted(p.stem for p in out.glob("*.json")) == ["AAA", "BBB", "index"]


def test_partial_run_never_deletes_files(out, monkeypatch):
    _write_previous(out, "OTHER")
    (out / "index.json").write_text(json.dumps({"tickers": ["OTHER"], "names": {}, "generated_at": "x"}))
    _use(monkeypatch, FakeProvider())
    gen.main(["AAA"], merge_index=True)
    assert (out / "OTHER.json").exists()
    assert _read(out, "index")["tickers"] == ["OTHER", "AAA"]


def test_price_history_failure_reuses_recent_previous_history(out, monkeypatch):
    previous = _write_previous(out, "BBB", price_history=_bars(7, 55.0))
    _use(monkeypatch, FakeProvider(history_errors={"BBB": FinvizTransientError("timeout")}))
    gen.main(["AAA", "BBB"])
    assert _read(out, "BBB")["price_history"] == previous["price_history"]
    assert _read(out, "BBB")["name"] == "BBB Corp"               # grid itself is fresh


def test_price_history_404_leaves_chart_empty_not_stale(out, monkeypatch):
    _write_previous(out, "PSKY", price_history=_bars(7, 55.0))
    _use(monkeypatch, FakeProvider(history_errors={"PSKY": FinvizNotFoundError("no price history")}))
    gen.main(["AAA", "PSKY"])
    assert _read(out, "PSKY")["price_history"] == []


def test_mass_failure_still_aborts_without_writing(out, monkeypatch):
    for t in ("A1", "A2", "A3"):
        _write_previous(out, t)
    err = FinvizTransientError("blocked")
    _use(monkeypatch, FakeProvider(snapshot_errors={"A1": err, "A2": err, "A3": err}))
    with pytest.raises(RuntimeError, match="0/3 tickers succeeded"):
        gen.main(["A1", "A2", "A3"])
    assert not (out / "index.json").exists()                     # carried-forward doesn't mask an outage


def test_github_warning_only_inside_actions(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    gen._gh_warning("t", "m")
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    gen._gh_warning("Tickers gone", "WBD returned 404")
    assert capsys.readouterr().out.strip() == "::warning title=Tickers gone::WBD returned 404"
