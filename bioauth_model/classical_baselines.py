"""Classical BioAuth baseline verifiers for offline evaluation.

Phase 7 adds Scaled Manhattan, NN-Mahalanobis, and One-Class SVM baselines
for comparison only. They are not runtime-authoritative, cannot lock alone,
and always use the Phase 2 score convention: higher score means more
suspicious / intruder-like.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence

import numpy as np

from evaluation_core.metrics import LABEL_CONVENTION, _binary_metrics, calibrate_thresholds, predict_labels_at_threshold

BASELINE_SCORE_DIRECTION = "higher_score_more_suspicious"
CLASSICAL_BASELINE_SCHEMA_VERSION = "phase7-classical-baselines-v1"
DEFAULT_MIN_GENUINE_SAMPLES = 2
DEFAULT_EPSILON = 1e-6
DEFAULT_COVARIANCE_REGULARIZATION = 1e-4
SKLEARN_CLASSICAL_BASELINES_AVAILABLE = None


def _load_sklearn_one_class_svm() -> tuple[Any | None, Any | None, bool]:
    global SKLEARN_CLASSICAL_BASELINES_AVAILABLE
    try:
        from sklearn.preprocessing import StandardScaler as _StandardScaler
        from sklearn.svm import OneClassSVM as _OneClassSVM
    except Exception:  # pragma: no cover
        SKLEARN_CLASSICAL_BASELINES_AVAILABLE = False
        return None, None, False
    SKLEARN_CLASSICAL_BASELINES_AVAILABLE = True
    return _StandardScaler, _OneClassSVM, True


@dataclass(frozen=True)
class ClassicalScoreResult:
    available: bool
    status: str
    risk_score: float | None
    decision: str
    reason_codes: tuple[str, ...]
    can_lock_alone: bool = False
    score_direction: str = BASELINE_SCORE_DIRECTION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": bool(self.available),
            "status": self.status,
            "risk_score": None if self.risk_score is None else float(self.risk_score),
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "can_lock_alone": False,
            "score_direction": self.score_direction,
        }


def _matrix(values: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        raise ValueError("Classical baseline inputs must be a 2D feature matrix.")
    return np.where(np.isfinite(arr), arr, 0.0) if arr.size else arr


def _unavailable(reason: str) -> ClassicalScoreResult:
    return ClassicalScoreResult(False, "unavailable", None, "abstain", (reason,))


def _decision(score: float | None, threshold: float | None) -> str:
    if score is None or threshold is None:
        return "abstain"
    return "intruder" if float(score) >= float(threshold) else "genuine"


def _metadata(*, baseline_type: str, available: bool, reason: str, threshold: float | None, sample_count: int, feature_count: int | None, feature_names: Sequence[str] | None, feature_schema_version: str | None, hyperparameters: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": CLASSICAL_BASELINE_SCHEMA_VERSION,
        "baseline_type": baseline_type,
        "available": bool(available),
        "reason": reason,
        "threshold": None if threshold is None else float(threshold),
        "score_direction": BASELINE_SCORE_DIRECTION,
        "label_convention": dict(LABEL_CONVENTION),
        "trained_on": "genuine_owner_windows_only",
        "sample_count": int(sample_count),
        "feature_count": None if feature_count is None else int(feature_count),
        "feature_names": list(feature_names or []),
        "feature_schema_version": feature_schema_version,
        "hyperparameters": dict(hyperparameters),
        "can_lock_alone": False,
        "runtime_authoritative": False,
        "safety_invariants": {
            "no_single_model_can_lock": True,
            "face_confirmation_required_before_lock": True,
            "developer_direct_influence_default": False,
        },
    }


class ScaledManhattanVerifier:
    baseline_type = "scaled_manhattan"

    def __init__(self, *, epsilon: float = DEFAULT_EPSILON, scale_method: str = "std") -> None:
        self.epsilon = max(float(epsilon), 1e-12)
        self.scale_method = str(scale_method or "std")
        self.template_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.threshold_: float | None = None
        self.available_ = False
        self.reason_ = "not_fit"
        self.n_samples_ = 0
        self.n_features_in_: int | None = None

    def fit(self, genuine_features: Sequence[Sequence[float]] | np.ndarray, *, threshold: float | None = None) -> "ScaledManhattanVerifier":
        X = _matrix(genuine_features)
        self.n_samples_ = int(X.shape[0])
        self.n_features_in_ = int(X.shape[1]) if X.ndim == 2 and X.shape[1] else None
        if X.shape[0] < DEFAULT_MIN_GENUINE_SAMPLES or X.shape[1] < 1:
            self.available_ = False
            self.reason_ = "insufficient_genuine_samples"
            return self
        self.template_ = np.mean(X, axis=0)
        if self.scale_method == "mad":
            median = np.median(X, axis=0)
            scale = np.median(np.abs(X - median), axis=0)
        else:
            scale = np.std(X, axis=0, ddof=0)
        self.scale_ = np.where(np.abs(scale) < self.epsilon, self.epsilon, scale)
        self.available_ = True
        self.reason_ = "ok"
        scores = self.score_samples(X)
        finite = scores[np.isfinite(scores)]
        self.threshold_ = float(threshold) if threshold is not None else float(np.quantile(finite, 0.95))
        return self

    def score_samples(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = _matrix(features)
        if self.template_ is None or self.scale_ is None or not self.available_ or X.shape[1] != self.template_.shape[0]:
            return np.full((X.shape[0],), np.nan, dtype=float)
        return np.mean(np.abs((X - self.template_) / self.scale_), axis=1).astype(float)

    def score_one(self, features: Sequence[float] | np.ndarray) -> ClassicalScoreResult:
        if not self.available_:
            return _unavailable(self.reason_)
        score = self.score_samples(np.asarray(features, dtype=float).reshape(1, -1))[0]
        if not np.isfinite(score):
            return _unavailable("feature_schema_mismatch")
        return ClassicalScoreResult(True, "ok", float(score), _decision(float(score), self.threshold_), ("ok",))

    def metadata(self, *, feature_names: Sequence[str] | None = None, feature_schema_version: str | None = None) -> Dict[str, Any]:
        return _metadata(baseline_type=self.baseline_type, available=self.available_, reason=self.reason_, threshold=self.threshold_, sample_count=self.n_samples_, feature_count=self.n_features_in_, feature_names=feature_names, feature_schema_version=feature_schema_version, hyperparameters={"epsilon": self.epsilon, "scale_method": self.scale_method})


class NNMahalanobisVerifier:
    baseline_type = "nn_mahalanobis"

    def __init__(self, *, regularization: float = DEFAULT_COVARIANCE_REGULARIZATION) -> None:
        self.regularization = max(float(regularization), 1e-12)
        self.reference_: np.ndarray | None = None
        self.inv_cov_: np.ndarray | None = None
        self.threshold_: float | None = None
        self.available_ = False
        self.reason_ = "not_fit"
        self.used_pinv_ = False
        self.n_samples_ = 0
        self.n_features_in_: int | None = None

    def fit(self, genuine_features: Sequence[Sequence[float]] | np.ndarray, *, threshold: float | None = None) -> "NNMahalanobisVerifier":
        X = _matrix(genuine_features)
        self.n_samples_ = int(X.shape[0])
        self.n_features_in_ = int(X.shape[1]) if X.ndim == 2 and X.shape[1] else None
        if X.shape[0] < DEFAULT_MIN_GENUINE_SAMPLES or X.shape[1] < 1:
            self.available_ = False
            self.reason_ = "insufficient_genuine_samples"
            return self
        cov = np.atleast_2d(np.cov(X, rowvar=False, ddof=0)).astype(float)
        try:
            self.inv_cov_ = np.linalg.inv(cov + np.eye(cov.shape[0]) * self.regularization)
            self.used_pinv_ = False
        except np.linalg.LinAlgError:
            self.inv_cov_ = np.linalg.pinv(cov + np.eye(cov.shape[0]) * self.regularization)
            self.used_pinv_ = True
        self.reference_ = X.astype(float)
        self.available_ = True
        self.reason_ = "ok"
        scores = self.score_samples(X)
        finite = scores[np.isfinite(scores)]
        self.threshold_ = float(threshold) if threshold is not None else float(np.quantile(finite, 0.95))
        return self

    def score_samples(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = _matrix(features)
        if self.reference_ is None or self.inv_cov_ is None or not self.available_ or X.shape[1] != self.reference_.shape[1]:
            return np.full((X.shape[0],), np.nan, dtype=float)
        out = []
        for row in X:
            diff = self.reference_ - row
            dist = np.einsum("ij,jk,ik->i", diff, self.inv_cov_, diff)
            dist = np.where(np.isfinite(dist), dist, np.inf)
            out.append(float(np.sqrt(max(0.0, float(np.min(dist))))))
        return np.asarray(out, dtype=float)

    def score_one(self, features: Sequence[float] | np.ndarray) -> ClassicalScoreResult:
        if not self.available_:
            return _unavailable(self.reason_)
        score = self.score_samples(np.asarray(features, dtype=float).reshape(1, -1))[0]
        if not np.isfinite(score):
            return _unavailable("feature_schema_mismatch")
        return ClassicalScoreResult(True, "ok", float(score), _decision(float(score), self.threshold_), ("ok",))

    def metadata(self, *, feature_names: Sequence[str] | None = None, feature_schema_version: str | None = None) -> Dict[str, Any]:
        return _metadata(baseline_type=self.baseline_type, available=self.available_, reason=self.reason_, threshold=self.threshold_, sample_count=self.n_samples_, feature_count=self.n_features_in_, feature_names=feature_names, feature_schema_version=feature_schema_version, hyperparameters={"regularization": self.regularization, "used_pinv": self.used_pinv_})


class OneClassSVMBaseline:
    baseline_type = "one_class_svm"

    def __init__(self, *, kernel: str = "rbf", nu: float = 0.05, gamma: str | float = "scale", min_samples: int = 5) -> None:
        self.kernel = str(kernel or "rbf")
        self.nu = max(1e-6, min(0.999, float(nu)))
        self.gamma = gamma
        self.min_samples = int(max(2, min_samples))
        self.scaler_: Any | None = None
        self.model_: Any | None = None
        self.threshold_: float | None = None
        self.available_ = False
        self.reason_ = "not_fit"
        self.n_samples_ = 0
        self.n_features_in_: int | None = None

    def fit(self, genuine_features: Sequence[Sequence[float]] | np.ndarray, *, threshold: float | None = None) -> "OneClassSVMBaseline":
        X = _matrix(genuine_features)
        self.n_samples_ = int(X.shape[0])
        self.n_features_in_ = int(X.shape[1]) if X.ndim == 2 and X.shape[1] else None
        if X.shape[0] < self.min_samples or X.shape[1] < 1:
            self.available_ = False
            self.reason_ = "insufficient_genuine_samples"
            return self
        scaler_cls, svm_cls, sklearn_available = _load_sklearn_one_class_svm()
        if not sklearn_available or scaler_cls is None or svm_cls is None:
            self.available_ = False
            self.reason_ = "sklearn_unavailable"
            return self
        self.scaler_ = scaler_cls()
        X_scaled = self.scaler_.fit_transform(X)
        self.model_ = svm_cls(kernel=self.kernel, nu=self.nu, gamma=self.gamma)
        self.model_.fit(X_scaled)
        self.available_ = True
        self.reason_ = "ok"
        scores = self.score_samples(X)
        finite = scores[np.isfinite(scores)]
        self.threshold_ = float(threshold) if threshold is not None else float(np.quantile(finite, 0.95))
        return self

    def score_samples(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = _matrix(features)
        if self.scaler_ is None or self.model_ is None or not self.available_:
            return np.full((X.shape[0],), np.nan, dtype=float)
        expected = int(getattr(self.scaler_, "n_features_in_", X.shape[1]))
        if X.shape[1] != expected:
            return np.full((X.shape[0],), np.nan, dtype=float)
        raw = np.asarray(self.model_.decision_function(self.scaler_.transform(X)), dtype=float).reshape(-1)
        return (-raw).astype(float)

    def score_one(self, features: Sequence[float] | np.ndarray) -> ClassicalScoreResult:
        if not self.available_:
            return _unavailable(self.reason_)
        score = self.score_samples(np.asarray(features, dtype=float).reshape(1, -1))[0]
        if not np.isfinite(score):
            return _unavailable("feature_schema_mismatch")
        return ClassicalScoreResult(True, "ok", float(score), _decision(float(score), self.threshold_), ("ok",))

    def metadata(self, *, feature_names: Sequence[str] | None = None, feature_schema_version: str | None = None) -> Dict[str, Any]:
        return _metadata(baseline_type=self.baseline_type, available=self.available_, reason=self.reason_, threshold=self.threshold_, sample_count=self.n_samples_, feature_count=self.n_features_in_, feature_names=feature_names, feature_schema_version=feature_schema_version, hyperparameters={"kernel": self.kernel, "nu": self.nu, "gamma": self.gamma, "min_samples": self.min_samples})


def build_classical_baselines(genuine_features: Sequence[Sequence[float]] | np.ndarray, *, feature_names: Sequence[str] | None = None, feature_schema_version: str | None = None, one_class_svm_config: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    cfg = dict(one_class_svm_config or {})
    baselines = {
        "scaled_manhattan": ScaledManhattanVerifier().fit(genuine_features),
        "nn_mahalanobis": NNMahalanobisVerifier().fit(genuine_features),
        "one_class_svm": OneClassSVMBaseline(kernel=str(cfg.get("kernel", "rbf")), nu=float(cfg.get("nu", 0.05)), gamma=cfg.get("gamma", "scale"), min_samples=int(cfg.get("min_samples", 5))).fit(genuine_features),
    }
    return {
        "schema_version": CLASSICAL_BASELINE_SCHEMA_VERSION,
        "score_direction": BASELINE_SCORE_DIRECTION,
        "runtime_authoritative": False,
        "can_lock_alone": False,
        "baselines": {name: verifier.metadata(feature_names=feature_names, feature_schema_version=feature_schema_version) for name, verifier in baselines.items()},
    }


def evaluate_classical_baselines(genuine_train_features: Sequence[Sequence[float]] | np.ndarray, evaluation_features: Sequence[Sequence[float]] | np.ndarray, y_true: Sequence[int], *, target_far: float | None = None, one_class_svm_config: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    X_train = _matrix(genuine_train_features)
    X_eval = _matrix(evaluation_features)
    y_arr = np.asarray(list(y_true), dtype=int)
    if X_eval.shape[0] != y_arr.size:
        raise ValueError("evaluation_features and y_true must have the same number of rows.")
    cfg = dict(one_class_svm_config or {})
    objects = {
        "scaled_manhattan": ScaledManhattanVerifier().fit(X_train),
        "nn_mahalanobis": NNMahalanobisVerifier().fit(X_train),
        "one_class_svm": OneClassSVMBaseline(kernel=str(cfg.get("kernel", "rbf")), nu=float(cfg.get("nu", 0.05)), gamma=cfg.get("gamma", "scale"), min_samples=int(cfg.get("min_samples", 5))).fit(X_train),
    }
    result: Dict[str, Any] = {"schema_version": CLASSICAL_BASELINE_SCHEMA_VERSION, "score_direction": BASELINE_SCORE_DIRECTION, "label_convention": dict(LABEL_CONVENTION), "can_lock_alone": False, "runtime_authoritative": False, "baselines": {}}
    for name, verifier in objects.items():
        meta = verifier.metadata()
        if not meta.get("available"):
            result["baselines"][name] = {"available": False, "reason": meta.get("reason"), "metadata": meta, "metrics": None, "thresholds": None, "can_lock_alone": False}
            continue
        scores = verifier.score_samples(X_eval)
        scores = np.where(np.isfinite(scores), scores, 0.0)
        thresholds = calibrate_thresholds(y_arr, scores, target_far=target_far)
        threshold = thresholds.get("global_threshold") if thresholds.get("available") else meta.get("threshold")
        y_pred = predict_labels_at_threshold(scores, float(threshold if threshold is not None else 0.0))
        metrics = _binary_metrics(y_arr, y_pred, scores)
        metrics["baseline_type"] = name
        metrics["decision_threshold"] = None if threshold is None else float(threshold)
        result["baselines"][name] = {"available": True, "reason": "ok", "metadata": meta, "metrics": metrics, "thresholds": thresholds, "can_lock_alone": False}
    return result


__all__ = [
    "BASELINE_SCORE_DIRECTION",
    "CLASSICAL_BASELINE_SCHEMA_VERSION",
    "DEFAULT_COVARIANCE_REGULARIZATION",
    "DEFAULT_EPSILON",
    "SKLEARN_CLASSICAL_BASELINES_AVAILABLE",
    "ClassicalScoreResult",
    "NNMahalanobisVerifier",
    "OneClassSVMBaseline",
    "ScaledManhattanVerifier",
    "build_classical_baselines",
    "evaluate_classical_baselines",
]
