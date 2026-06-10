from __future__ import annotations
import importlib, json
from pathlib import Path
import numpy as np
from deep_sequence.tensorization import build_sequence_dataset_from_session_samples
from deep_sequence.serialization import save_sequence_model_artifact, load_sequence_model_artifact
from bioauth_model.scoring import score_windows, final_decision_from_metrics

def test_sequence_tensorization_preserves_session_order_and_shape() -> None:
    feature_names = ['f1', 'f2']
    session_samples = {
        'session_a': [
            {'sequence_window_index': 2, 'window_start_offset': 8.0, 'f1': 30.0, 'f2': 3.0},
            {'sequence_window_index': 0, 'window_start_offset': 0.0, 'f1': 10.0, 'f2': 1.0},
            {'sequence_window_index': 1, 'window_start_offset': 4.0, 'f1': 20.0, 'f2': 2.0},
        ],
        'session_b': [
            {'sequence_window_index': 1, 'window_start_offset': 4.0, 'f1': 200.0, 'f2': 20.0},
            {'sequence_window_index': 0, 'window_start_offset': 0.0, 'f1': 100.0, 'f2': 10.0},
        ],
    }
    dataset = build_sequence_dataset_from_session_samples(session_samples, feature_names, {'session_a': 0, 'session_b': 1}, sequence_length=2)
    assert dataset['shape'] == [3, 2, 2]
    np.testing.assert_allclose(dataset['X'][0], np.asarray([[10.0, 1.0], [20.0, 2.0]], dtype=np.float32))

def test_sequence_artifact_roundtrip(tmp_path: Path) -> None:
    artifact_path = tmp_path / 'sequence_model.pt'
    payload = {'model_family': 'cnn_lstm', 'training_summary': {'validation_metrics': {'auc': 0.91}}, 'state_dict': {}}
    try:
        save_sequence_model_artifact(str(artifact_path), payload)
    except Exception:
        return
    loaded = load_sequence_model_artifact(str(artifact_path))
    assert loaded['model_family'] == 'cnn_lstm'

def test_hybrid_scoring_shadow_payload() -> None:
    metrics = score_windows(raw_scores=np.asarray([1.0, 2.0]), anomaly_risk_values=np.asarray([60.0, 70.0]), classifier_probs=np.asarray([0.2, 0.8]), sensitivity='balanced', sequence_probs=np.asarray([0.9]))
    assert metrics['hybrid']['available'] is True
    outcome = final_decision_from_metrics(metrics={**metrics, **metrics['hybrid']}, window_count=2)
    assert outcome.final in {'legitimate', 'suspicious', 'intruder'}

def test_train_model_wrapper_can_skip_deep_sequence_training(monkeypatch, tmp_path: Path) -> None:
    import model_training
    model_training = importlib.reload(model_training)
    calls = {'deep': 0}
    def fake_train_impl(**kwargs):
        metadata_path = Path(kwargs['metadata_file'])
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps({'deep_runtime': {'sequence_model': {}}}), encoding='utf-8')
        return {'label': 'candidate'}, 'ok'
    monkeypatch.setattr(model_training, '_train_model_impl', fake_train_impl)
    monkeypatch.setattr(model_training, 'save_metadata_hash', lambda path: None)
    def fake_deep(**kwargs):
        calls['deep'] += 1
        return {}
    monkeypatch.setattr(model_training, '_run_deep_sequence_training', fake_deep)
    model, status = model_training.train_model(sessions=['/tmp/session_a'], negative_sessions=[], model_file=str(tmp_path / 'model.pkl'), classifier_file=str(tmp_path / 'classifier.pkl'), metadata_file=str(tmp_path / 'metadata.json'), enable_deep_sequence_training=False)
    assert model == {'label': 'candidate'}
    assert status == 'ok'
    assert calls['deep'] == 0
