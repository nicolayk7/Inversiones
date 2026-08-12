"""Sub-metric weight loader: architecture approved, values BLOCKED (Phase 1B decision). Every
shipped file must be PROVISIONAL and must be rejected under a production configuration (rule 6)
— this is the coded guardrail behind "no implementation can accidentally invent production
weights"."""

import pytest

from packages.shared.component_weights import (
    ComponentWeightsValidationError,
    ProvisionalWeightsRejectedError,
    WeightApprovalStatus,
    load_component_weights,
)


@pytest.mark.parametrize("group", ["quality", "growth", "fcf", "valuation"])
def test_provisional_weights_load_in_dev(group):
    weights = load_component_weights(group, "v1.0", allow_provisional=True)
    assert weights.status == WeightApprovalStatus.PROVISIONAL
    assert sum(weights.weights.values()) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("group", ["quality", "growth", "fcf", "valuation"])
def test_provisional_weights_rejected_under_production(group):
    with pytest.raises(ProvisionalWeightsRejectedError):
        load_component_weights(group, "v1.0", allow_provisional=False)


def test_unknown_group_is_rejected():
    with pytest.raises(ComponentWeightsValidationError):
        load_component_weights("moat", "v1.0", allow_provisional=True)


def test_missing_version_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_component_weights("quality", "v99.9", allow_provisional=True)


def test_missing_status_is_rejected(tmp_path, monkeypatch):
    import packages.shared.component_weights as cw

    bad_file = tmp_path / "quality_vbad.yaml"
    bad_file.write_text("version: vbad\nweights:\n  a: 1.0\n", encoding="utf-8")
    monkeypatch.setattr(cw, "COMPONENT_WEIGHTS_DIR", tmp_path)
    cw.load_component_weights.cache_clear()

    with pytest.raises(ComponentWeightsValidationError):
        cw.load_component_weights("quality", "vbad", allow_provisional=True)
    cw.load_component_weights.cache_clear()


def test_weights_not_summing_to_one_is_rejected(tmp_path, monkeypatch):
    import packages.shared.component_weights as cw

    bad_file = tmp_path / "quality_vbad2.yaml"
    bad_file.write_text("version: vbad2\nstatus: PROVISIONAL\nweights:\n  a: 0.5\n  b: 0.2\n", encoding="utf-8")
    monkeypatch.setattr(cw, "COMPONENT_WEIGHTS_DIR", tmp_path)
    cw.load_component_weights.cache_clear()

    with pytest.raises(ComponentWeightsValidationError):
        cw.load_component_weights("quality", "vbad2", allow_provisional=True)
    cw.load_component_weights.cache_clear()
