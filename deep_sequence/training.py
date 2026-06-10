from __future__ import annotations

import os
import time
from typing import Any, Dict, Mapping, Sequence

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

from deep_runtime import DEFAULT_SEQUENCE_LENGTH, DEFAULT_TENSOR_LAYOUT
from .models import TORCH_AVAILABLE, SequenceCnnLstm, _torch_runtime
from .serialization import save_sequence_model_artifact
from .tensorization import SEQUENCE_DATA_VERSION, build_sequence_dataset_from_session_samples

SEQUENCE_TRAINING_VERSION = 'cnn-lstm-trainer-v1'


def _metric_dict(y_true: np.ndarray, probabilities: np.ndarray) -> Dict[str, Any]:
    y_arr = np.asarray(y_true, dtype=int)
    probs = np.asarray(probabilities, dtype=np.float32)
    preds = (probs >= 0.5).astype(int)
    tn = int(np.sum((y_arr == 0) & (preds == 0)))
    fp = int(np.sum((y_arr == 0) & (preds == 1)))
    fn = int(np.sum((y_arr == 1) & (preds == 0)))
    tp = int(np.sum((y_arr == 1) & (preds == 1)))
    legit = int(np.sum(y_arr == 0))
    intr = int(np.sum(y_arr == 1))
    auc = float(roc_auc_score(y_arr, probs)) if legit and intr else 0.0
    return {'auc': round(float(auc), 6), 'accuracy': round(float(accuracy_score(y_arr, preds)) if y_arr.size else 0.0, 6), 'f1': round(float(f1_score(y_arr, preds, zero_division=0)) if y_arr.size else 0.0, 6), 'precision': round(float(precision_score(y_arr, preds, zero_division=0)) if y_arr.size else 0.0, 6), 'recall': round(float(recall_score(y_arr, preds, zero_division=0)) if y_arr.size else 0.0, 6), 'far': round(float(fp / legit) if legit else 0.0, 6), 'frr': round(float(fn / intr) if intr else 0.0, 6), 'confusion_matrix': {'tn': tn, 'fp': fp, 'fn': fn, 'tp': tp}, 'sequence_count': int(y_arr.size)}


def _split_session_ids(labels_by_session: Mapping[str, int]):
    positive = [s for s, y in labels_by_session.items() if int(y) == 0]
    negative = [s for s, y in labels_by_session.items() if int(y) == 1]
    if len(positive) >= 2 and len(negative) >= 2:
        val_sessions = [positive[-1], negative[-1]]
        train_sessions = [s for s in labels_by_session.keys() if s not in set(val_sessions)]
        if train_sessions:
            return train_sessions, val_sessions, {'method': 'session_holdout', 'validation_sessions': list(val_sessions)}
    session_ids = list(labels_by_session.keys())
    return session_ids, session_ids, {'method': 'resubstitution', 'validation_sessions': list(session_ids)}


def train_sequence_model_candidate(*, session_samples: Mapping[str, Sequence[Mapping[str, Any]]], feature_names: Sequence[str], labels_by_session: Mapping[str, int], artifact_path: str, sequence_length: int = DEFAULT_SEQUENCE_LENGTH, stride: int = 1, max_epochs: int = 4, batch_size: int = 16, learning_rate: float = 1e-3, early_stopping_patience: int = 2, seed: int = 17) -> Dict[str, Any]:
    summary = {'version': SEQUENCE_TRAINING_VERSION, 'model_family': 'cnn_lstm', 'framework': 'pytorch' if TORCH_AVAILABLE else None, 'tensor_layout': DEFAULT_TENSOR_LAYOUT, 'sequence_data_version': SEQUENCE_DATA_VERSION, 'sequence_length': int(max(2, sequence_length)), 'stride': int(max(1, stride)), 'status': 'disabled', 'trained': False, 'artifact_file': None, 'artifact_written': False, 'reason': None, 'train_metrics': {}, 'validation_metrics': {}, 'split': {}, 'sequence_data': {}}
    if not TORCH_AVAILABLE:
        summary['reason'] = 'pytorch_unavailable'
        return summary
    torch, nn = _torch_runtime()
    from torch.utils.data import DataLoader, TensorDataset

    def _dataset(payload: Mapping[str, Any]):
        X = np.asarray(payload.get('X'), dtype=np.float32)
        y = np.asarray(payload.get('y'), dtype=np.float32)
        return TensorDataset(torch.from_numpy(X), torch.from_numpy(y))

    labels = {str(k): int(v or 0) for k, v in dict(labels_by_session or {}).items()}
    if not labels:
        summary['reason'] = 'labels_missing'
        return summary
    train_sessions, val_sessions, split = _split_session_ids(labels)
    train_payload = build_sequence_dataset_from_session_samples({s: session_samples.get(s, []) for s in train_sessions}, feature_names, labels, sequence_length=sequence_length, stride=stride)
    val_payload = build_sequence_dataset_from_session_samples({s: session_samples.get(s, []) for s in val_sessions}, feature_names, labels, sequence_length=sequence_length, stride=stride)
    summary['split'] = {**split, 'train_sessions': list(train_sessions), 'validation_sessions': list(val_sessions)}
    summary['sequence_data'] = {'version': train_payload.get('version'), 'tensor_layout': train_payload.get('tensor_layout'), 'feature_count': int(train_payload.get('feature_count') or 0), 'sequence_length': int(train_payload.get('sequence_length') or 0), 'ordering_keys': list(train_payload.get('ordering_keys') or []), 'train_sequence_count': int(train_payload.get('sequence_count') or 0), 'validation_sequence_count': int(val_payload.get('sequence_count') or 0)}
    if int(train_payload.get('sequence_count') or 0) < 4:
        summary['reason'] = 'insufficient_sequence_windows'
        return summary
    if len(set(np.asarray(train_payload.get('y'), dtype=int).tolist())) < 2:
        summary['reason'] = 'insufficient_label_diversity'
        return summary
    torch.manual_seed(int(seed))
    np.random.seed(int(seed))
    model = SequenceCnnLstm(feature_dim=int(train_payload.get('feature_count') or 1))
    train_loader = DataLoader(_dataset(train_payload), batch_size=max(1, int(batch_size)), shuffle=True)
    val_loader = DataLoader(_dataset(val_payload), batch_size=max(1, int(batch_size)), shuffle=False)
    y_train = np.asarray(train_payload.get('y'), dtype=int)
    pos = max(1, int(np.sum(y_train == 1)))
    neg = max(1, int(np.sum(y_train == 0)))
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([float(neg / pos)], dtype=torch.float32))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    best_state = None
    best_loss = None
    patience = 0
    started = time.time()
    for _epoch in range(1, max(1, int(max_epochs)) + 1):
        model.train()
        for xb, yb in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(xb), yb.float())
            loss.backward()
            optimizer.step()
        model.eval()
        losses = []
        with torch.no_grad():
            for xb, yb in val_loader:
                losses.append(float(criterion(model(xb), yb.float()).item()))
        current_loss = float(np.mean(losses)) if losses else 0.0
        if best_loss is None or current_loss <= best_loss - 1e-5:
            best_loss = current_loss
            best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= max(1, int(early_stopping_patience)):
                break
    if best_state is None:
        summary['reason'] = 'training_failed'
        return summary
    model.load_state_dict(best_state)

    def _predict(payload: Mapping[str, Any]) -> np.ndarray:
        loader = DataLoader(_dataset(payload), batch_size=max(1, int(batch_size)), shuffle=False)
        probs = []
        with torch.no_grad():
            for xb, _yb in loader:
                probs.append(torch.sigmoid(model(xb)).cpu().numpy())
        return np.concatenate(probs) if probs else np.asarray([], dtype=np.float32)

    train_probs = _predict(train_payload)
    val_probs = _predict(val_payload)
    train_metrics = _metric_dict(np.asarray(train_payload.get('y'), dtype=int), train_probs)
    validation_metrics = _metric_dict(np.asarray(val_payload.get('y'), dtype=int), val_probs)
    artifact_payload = {'artifact_version': SEQUENCE_TRAINING_VERSION, 'model_family': 'cnn_lstm', 'framework': 'pytorch', 'state_dict': best_state, 'model_config': {'feature_dim': int(train_payload.get('feature_count') or 0), 'sequence_length': int(train_payload.get('sequence_length') or 0)}, 'training_summary': {'train_metrics': train_metrics, 'validation_metrics': validation_metrics, 'best_validation_loss': round(float(best_loss or 0.0), 6)}, 'feature_names': list(train_payload.get('feature_names') or []), 'tensor_layout': DEFAULT_TENSOR_LAYOUT, 'sequence_data_version': SEQUENCE_DATA_VERSION, 'saved_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
    save_sequence_model_artifact(artifact_path, artifact_payload)
    summary.update({'status': 'trained_for_shadow_runtime', 'trained': True, 'artifact_file': os.path.basename(artifact_path), 'artifact_written': True, 'reason': None, 'train_metrics': train_metrics, 'validation_metrics': validation_metrics, 'training_seconds': round(float(max(0.0, time.time() - started)), 3), 'best_validation_loss': round(float(best_loss or 0.0), 6)})
    return summary
