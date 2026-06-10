from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from bioauth_model.classical_baselines import ClassicalScoreResult

from .common import _decision, _matrix

@dataclass
class SklearnOneClassRiskArtifact:
    """Small picklable wrapper around sklearn one-class estimators.

    The wrapper converts sklearn's "higher is more normal" score conventions into
    BioAuth Hybrid Direct's report convention: higher risk means more suspicious.
    """

    estimator: Any
    candidate_id: str
    model_family: str
    feature_names: tuple[str, ...]
    threshold_: float | None
    threshold_source: str
    training_sample_count: int
    score_method: str
    artifact_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def threshold(self) -> float | None:
        return self.threshold_

    def _as_matrix(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = _matrix(features)
        expected = len(self.feature_names)
        if expected and X.shape[1] != expected:
            return np.full((X.shape[0], expected or X.shape[1]), np.nan, dtype=float)
        return X

    def score_samples(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = self._as_matrix(features)
        if X.size == 0 or np.isnan(X).any():
            return np.full((X.shape[0],), np.nan, dtype=float)
        if self.score_method == "negative_decision_function" and hasattr(self.estimator, "decision_function"):
            raw = np.asarray(self.estimator.decision_function(X), dtype=float).reshape(-1)
            return (-raw).astype(float)
        if hasattr(self.estimator, "score_samples"):
            raw = np.asarray(self.estimator.score_samples(X), dtype=float).reshape(-1)
            return (-raw).astype(float)
        if hasattr(self.estimator, "decision_function"):
            raw = np.asarray(self.estimator.decision_function(X), dtype=float).reshape(-1)
            return (-raw).astype(float)
        return np.full((X.shape[0],), np.nan, dtype=float)

    def score_one(self, features: Sequence[float] | np.ndarray) -> ClassicalScoreResult:
        score = self.score_samples(np.asarray(features, dtype=float).reshape(1, -1))[0]
        if not math.isfinite(float(score)):
            return ClassicalScoreResult(False, "unavailable", None, "abstain", ("feature_schema_mismatch",))
        return ClassicalScoreResult(True, "ok", float(score), _decision(float(score), self.threshold_), ("ok",))

    def metadata(self) -> dict[str, Any]:
        return dict(self.artifact_metadata)


@dataclass(frozen=True)
class OptionalSupervisedDependencySpec:
    """Resolved optional supervised dependency information.

    Tests may pass this spec to exercise available/missing dependency paths
    without installing optional packages. Production resolution imports only the
    requested local optional dependency and never vendors or installs packages.
    """

    candidate_id: str
    dependency_name: str
    model_family: str
    estimator_class: Any | None = None
    dependency_version: str | None = None
    available: bool = False
    dependency_status: str = "dependency_missing"
    import_error: str = ""


@dataclass
class SupervisedRiskArtifact:
    """Picklable report-only wrapper for optional supervised classifiers."""

    estimator: Any
    candidate_id: str
    model_family: str
    feature_names: tuple[str, ...]
    threshold_: float | None
    threshold_source: str
    training_sample_count: int
    owner_sample_count: int
    intruder_sample_count: int
    dependency_name: str
    dependency_version: str | None
    artifact_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def threshold(self) -> float | None:
        return self.threshold_

    def _as_matrix(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = _matrix(features)
        expected = len(self.feature_names)
        if expected and X.shape[1] != expected:
            return np.full((X.shape[0], expected or X.shape[1]), np.nan, dtype=float)
        return X

    def predict_proba(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = self._as_matrix(features)
        if X.size == 0 or np.isnan(X).any() or not hasattr(self.estimator, "predict_proba"):
            return np.empty((X.shape[0], 0), dtype=float)
        return np.asarray(self.estimator.predict_proba(X), dtype=float)

    def decision_function(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = self._as_matrix(features)
        if X.size == 0 or np.isnan(X).any() or not hasattr(self.estimator, "decision_function"):
            return np.full((X.shape[0],), np.nan, dtype=float)
        return np.asarray(self.estimator.decision_function(X), dtype=float).reshape(-1)

    def predict(self, features: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
        X = self._as_matrix(features)
        if X.size == 0 or np.isnan(X).any() or not hasattr(self.estimator, "predict"):
            return np.full((X.shape[0],), 0, dtype=int)
        return np.asarray(self.estimator.predict(X))

    def metadata(self) -> dict[str, Any]:
        return dict(self.artifact_metadata)

# Preserve old pickle paths for artifacts created through the compatibility facade.
SklearnOneClassRiskArtifact.__module__ = "training_core.candidate_artifact_builders"
OptionalSupervisedDependencySpec.__module__ = "training_core.candidate_artifact_builders"
SupervisedRiskArtifact.__module__ = "training_core.candidate_artifact_builders"
