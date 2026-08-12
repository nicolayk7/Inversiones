"""Weights v1.0 must match the frozen architecture decision exactly and always sum to 1.0 —
this is the coded guardrail behind rule 9 (LLM cannot modify/decide weights)."""

from dataclasses import FrozenInstanceError

import pytest

from packages.shared.weights import WeightsValidationError, load_weights


def test_v1_0_loads():
    weights = load_weights("v1.0")
    assert weights.version == "v1.0"


@pytest.mark.parametrize("group", ["wealth", "trading", "options", "opportunity"])
def test_each_group_sums_to_one(group):
    weights = load_weights("v1.0")
    total = sum(getattr(weights, group).values())
    assert total == pytest.approx(1.0, abs=1e-6)


def test_wealth_weights_match_frozen_values():
    weights = load_weights("v1.0")
    assert weights.wealth == {
        "quality": 0.25,
        "growth": 0.25,
        "fcf": 0.15,
        "moat": 0.15,
        "valuation": 0.20,
    }


def test_opportunity_weights_exclude_risk():
    weights = load_weights("v1.0")
    assert "risk" not in weights.opportunity, "Risk is a gate, not a weighted score input (rule 8)"


def test_weights_group_item_assignment_is_rejected():
    weights = load_weights("v1.0")
    with pytest.raises(TypeError):
        weights.wealth["quality"] = 0.99


@pytest.mark.parametrize("group", ["wealth", "trading", "options", "opportunity"])
def test_weights_group_field_reassignment_is_rejected(group):
    weights = load_weights("v1.0")
    with pytest.raises(FrozenInstanceError):
        setattr(weights, group, {})


def test_cached_instance_is_shared_and_stays_immutable_across_callers():
    first = load_weights("v1.0")
    second = load_weights("v1.0")
    assert first is second  # same cached object — mutating one would corrupt both

    with pytest.raises(TypeError):
        first.trading["momentum"] = 0.99

    # unaffected by the rejected mutation attempt above
    assert second.trading["momentum"] == 0.20


def test_unknown_version_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_weights("v99.9")


def test_missing_group_is_rejected(tmp_path, monkeypatch):
    import packages.shared.weights as weights_module

    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("version: bad\nwealth:\n  quality: 1.0\n", encoding="utf-8")
    monkeypatch.setattr(weights_module, "WEIGHTS_DIR", tmp_path)
    weights_module.load_weights.cache_clear()

    with pytest.raises(WeightsValidationError):
        weights_module.load_weights("bad")
    weights_module.load_weights.cache_clear()
