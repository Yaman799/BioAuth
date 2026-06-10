from __future__ import annotations

from deep_sequence.models import deep_verifier_metadata
from deep_sequence.tensorization import build_keyboard_sequence_tensor, build_mouse_sequence_tensor
from deep_sequence.inference import run_experimental_keyboard_verifier, run_experimental_mouse_verifier
from deep_runtime import build_deep_runtime_metadata_contract
from evaluation_core.reporting import _build_summary_markdown
from hybrid_direct_contract import build_default_hybrid_direct_state, build_hybrid_direct_state


def _keyboard_samples(count: int = 6):
    return [
        {
            "sequence_window_index": idx,
            "key_hold_mean": 0.1 + idx * 0.01,
            "key_hold_std": 0.02,
            "flight_mean": 0.12 + idx * 0.01,
            "flight_std": 0.03,
            "keys_per_second": 4.0 + idx,
            "backspace_rate": 0.01,
            "typing_burst_rate": 2.0,
            "digraph_latency_mean": 0.14,
        }
        for idx in range(count)
    ]


def _mouse_samples(count: int = 6):
    return [
        {
            "sequence_window_index": idx,
            "dx": 0.5 + idx * 0.1,
            "dy": 0.4 + idx * 0.1,
            "distance": 0.8 + idx * 0.1,
            "velocity": 10.0 + idx,
            "acceleration": 0.2 + idx * 0.01,
            "angle_change": 0.03 * idx,
            "click_state": 1.0 if idx % 2 else 0.0,
            "scroll_delta": 0.0,
            "drag_state": 0.0,
        }
        for idx in range(count)
    ]


def test_keyboard_tensor_abstains_on_short_or_missing_sequence() -> None:
    missing = build_keyboard_sequence_tensor([], sequence_length=4)
    assert missing["available"] is False
    assert missing["decision"] == "abstain"
    assert missing["reason"] == "missing_modality_features"
    assert missing["fusion_weight"] == 0.0
    assert missing["can_lock_alone"] is False

    too_short = build_keyboard_sequence_tensor(_keyboard_samples(2), sequence_length=4)
    assert too_short["available"] is False
    assert too_short["decision"] == "abstain"
    assert too_short["reason"] == "sequence_too_short"
    assert too_short["fusion_weight"] == 0.0


def test_mouse_tensor_abstains_on_short_or_missing_sequence() -> None:
    missing = build_mouse_sequence_tensor([], sequence_length=4)
    assert missing["available"] is False
    assert missing["decision"] == "abstain"
    assert missing["reason"] == "missing_modality_features"
    assert missing["fusion_weight"] == 0.0
    assert missing["can_lock_alone"] is False

    too_short = build_mouse_sequence_tensor(_mouse_samples(1), sequence_length=4)
    assert too_short["available"] is False
    assert too_short["decision"] == "abstain"
    assert too_short["reason"] == "sequence_too_short"


def test_keyboard_and_mouse_tensors_have_ntf_shape_when_available() -> None:
    keyboard = build_keyboard_sequence_tensor(_keyboard_samples(6), sequence_length=4)
    mouse = build_mouse_sequence_tensor(_mouse_samples(6), sequence_length=4)
    assert keyboard["available"] is True
    assert mouse["available"] is True
    assert keyboard["shape"] == [1, 4, 8]
    assert mouse["shape"] == [1, 4, 9]
    assert keyboard["fusion_weight"] == 0.0
    assert mouse["fusion_weight"] == 0.0


def test_experimental_inference_abstain_payloads_are_non_authoritative() -> None:
    keyboard = run_experimental_keyboard_verifier(window_samples=[], sequence_length=4)
    mouse = run_experimental_mouse_verifier(window_samples=[], sequence_length=4)
    for payload in (keyboard, mouse):
        assert payload["decision"] == "abstain"
        assert payload["experimental"] is True
        assert payload["runtime_authoritative"] is False
        assert payload["can_lock_alone"] is False
        assert payload["can_influence_device"] is False
        assert payload["fusion_weight"] == 0.0


def test_deep_verifier_metadata_and_runtime_contract_are_non_authoritative() -> None:
    metadata = deep_verifier_metadata(
        architecture="keyboard_bigru_cnn_attention",
        input_modality="keyboard",
        feature_names=["key_hold_mean", "flight_mean"],
        sequence_length=8,
    )
    assert metadata["experimental"] is True
    assert metadata["runtime_authoritative"] is False
    assert metadata["can_lock_alone"] is False
    assert metadata["can_influence_device"] is False
    assert metadata["score_direction"] == "higher_score_more_suspicious"
    assert metadata["threshold_source"] == "not_calibrated"

    contract = build_deep_runtime_metadata_contract(sequence_length=8)
    verifiers = contract["experimental_deep_verifiers"]
    assert verifiers["can_lock_alone"] is False
    assert verifiers["can_influence_device"] is False
    assert verifiers["verifiers"]["keyboard"]["architecture"] == "keyboard_bigru_cnn_attention"
    assert verifiers["verifiers"]["mouse"]["architecture"] == "mouse_resnet_gru"
    assert verifiers["verifiers"]["type2branch_candidate"]["status"] == "future_candidate_disabled"
    assert verifiers["verifiers"]["typeformer_candidate"]["status"] == "future_candidate_disabled"


def test_hybrid_direct_state_marks_keyboard_and_mouse_verifiers_as_backend_owned_experimental() -> None:
    state = build_default_hybrid_direct_state(timestamp="2026-05-04T00:00:00Z")
    assert state["enabled"] is False
    for key, architecture in (("keyboard_risk", "keyboard_bigru_cnn_attention"), ("mouse_risk", "mouse_resnet_gru")):
        payload = state[key]
        assert payload["architecture"] == architecture
        assert payload["experimental"] is True
        assert payload["decision"] == "abstain"
        assert payload["can_lock"] is False
        assert payload["can_lock_alone"] is False
        assert payload["can_influence_device"] is False

    normalized = build_hybrid_direct_state({"keyboard_risk": {"available": True, "score": 0.9, "can_lock": True, "can_influence_device": True}})
    assert normalized["keyboard_risk"]["score"] == 0.9
    assert normalized["keyboard_risk"]["can_lock"] is False
    assert normalized["keyboard_risk"]["can_lock_alone"] is False
    assert normalized["keyboard_risk"]["can_influence_device"] is False


def test_evaluation_summary_mentions_experimental_deep_verifiers_without_lock_authority() -> None:
    report = {
        "generated_at": "2026-05-04",
        "primary_evaluation": "candidate_bundle",
        "evaluations": {"candidate_bundle": {"metrics": {}}},
        "experimental_deep_verifiers": {
            "score_direction": "higher_score_more_suspicious",
            "can_lock_alone": False,
            "verifiers": {
                "keyboard": {"architecture": "keyboard_bigru_cnn_attention"},
                "mouse": {"architecture": "mouse_resnet_gru"},
            },
        },
    }
    summary = _build_summary_markdown(report)
    assert "Experimental deep verifiers:" in summary
    assert "keyboard" in summary and "mouse" in summary
    assert "Experimental deep verifiers can lock alone: False" in summary
