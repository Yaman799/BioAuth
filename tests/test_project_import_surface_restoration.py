from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _install_if_missing(monkeypatch, name: str, module: types.ModuleType) -> None:
    if name not in sys.modules and not _module_available(name):
        monkeypatch.setitem(sys.modules, name, module)


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass

    def fit(self, *args, **kwargs):
        return self

    def predict(self, *args, **kwargs):
        return []

    def predict_proba(self, *args, **kwargs):
        return []

    def decision_function(self, *args, **kwargs):
        return []

    def __call__(self, *args, **kwargs):
        return _Dummy()


def _install_external_dependency_shims(monkeypatch) -> None:
    """Install test-only shims for unavailable third-party packages only.

    These shims intentionally do not provide or mask project modules such as
    training_core, utils.identity, or bio_platform.secrets. The test verifies
    those modules are restored as real source files in the archive.
    """

    np = types.ModuleType("numpy")
    np.ndarray = object
    np.array = lambda *a, **k: []
    np.asarray = lambda *a, **k: []
    np.zeros = lambda *a, **k: []
    np.ones = lambda *a, **k: []
    np.concatenate = lambda seq, *a, **k: []
    np.percentile = lambda *a, **k: 0.0
    np.mean = lambda *a, **k: 0.0
    np.std = lambda *a, **k: 0.0
    np.median = lambda *a, **k: 0.0
    np.sum = lambda *a, **k: 0
    np.isfinite = lambda *a, **k: True
    np.nan_to_num = lambda x, *a, **k: x
    np.random = types.SimpleNamespace(seed=lambda *a, **k: None)
    np.float32 = float
    np.float64 = float
    np.int64 = int
    _install_if_missing(monkeypatch, "numpy", np)

    pd = types.ModuleType("pandas")
    pd.DataFrame = _Dummy
    pd.Series = _Dummy
    pd.read_csv = lambda *a, **k: _Dummy()
    _install_if_missing(monkeypatch, "pandas", pd)

    sklearn = types.ModuleType("sklearn")
    ensemble = types.ModuleType("sklearn.ensemble")
    ensemble.RandomForestClassifier = _Dummy
    ensemble.IsolationForest = _Dummy
    metrics = types.ModuleType("sklearn.metrics")
    metrics.accuracy_score = lambda *a, **k: 0.0
    metrics.confusion_matrix = lambda *a, **k: [[0, 0], [0, 0]]
    metrics.f1_score = lambda *a, **k: 0.0
    metrics.precision_score = lambda *a, **k: 0.0
    metrics.recall_score = lambda *a, **k: 0.0
    metrics.roc_auc_score = lambda *a, **k: 0.0
    model_selection = types.ModuleType("sklearn.model_selection")
    model_selection.StratifiedShuffleSplit = _Dummy
    _install_if_missing(monkeypatch, "sklearn", sklearn)
    _install_if_missing(monkeypatch, "sklearn.ensemble", ensemble)
    _install_if_missing(monkeypatch, "sklearn.metrics", metrics)
    _install_if_missing(monkeypatch, "sklearn.model_selection", model_selection)

    crypto = types.ModuleType("cryptography")
    exceptions_mod = types.ModuleType("cryptography.exceptions")

    class InvalidSignature(Exception):
        pass

    exceptions_mod.InvalidSignature = InvalidSignature
    fernet_mod = types.ModuleType("cryptography.fernet")

    class Fernet:
        @staticmethod
        def generate_key():
            return b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

        def __init__(self, key):
            self.key = key

        def encrypt(self, data):
            return data

        def decrypt(self, data):
            return data

    fernet_mod.Fernet = Fernet
    hazmat = types.ModuleType("cryptography.hazmat")
    primitives = types.ModuleType("cryptography.hazmat.primitives")
    asym = types.ModuleType("cryptography.hazmat.primitives.asymmetric")
    ed25519 = types.ModuleType("cryptography.hazmat.primitives.asymmetric.ed25519")

    class Ed25519PublicKey:
        def verify(self, *args, **kwargs):
            return None

    ed25519.Ed25519PublicKey = Ed25519PublicKey
    serialization = types.ModuleType("cryptography.hazmat.primitives.serialization")
    serialization.load_pem_public_key = lambda *a, **k: Ed25519PublicKey()
    _install_if_missing(monkeypatch, "cryptography", crypto)
    _install_if_missing(monkeypatch, "cryptography.exceptions", exceptions_mod)
    _install_if_missing(monkeypatch, "cryptography.fernet", fernet_mod)
    _install_if_missing(monkeypatch, "cryptography.hazmat", hazmat)
    _install_if_missing(monkeypatch, "cryptography.hazmat.primitives", primitives)
    _install_if_missing(monkeypatch, "cryptography.hazmat.primitives.asymmetric", asym)
    _install_if_missing(monkeypatch, "cryptography.hazmat.primitives.asymmetric.ed25519", ed25519)
    _install_if_missing(monkeypatch, "cryptography.hazmat.primitives.serialization", serialization)

    for name in (
        "lightgbm",
        "pyod",
        "pyod.models",
        "pyod.models.iforest",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtQml",
    ):
        _install_if_missing(monkeypatch, name, types.ModuleType(name))


def test_restored_project_import_surface_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = [
        "training_core/__init__.py",
        "training_core/calibration.py",
        "training_core/data.py",
        "training_core/context_models.py",
        "training_core/selection.py",
        "training_core/supervised.py",
        "training_core/pipeline.py",
        "training_core/transitions.py",
        "utils/__init__.py",
        "utils/identity.py",
        "bio_platform/secrets.py",
    ]
    missing = [rel for rel in expected if not (root / rel).is_file()]
    assert missing == []
    assert not (root / "reports" / "phase1_validation").exists()
    assert (root / "reports" / "safety").is_dir()


def test_import_smoke_for_restored_project_surfaces(monkeypatch) -> None:
    _install_external_dependency_shims(monkeypatch)
    for name in (
        "bio_platform",
        "security",
        "artifact_integrity",
        "model_training",
        "model_metadata",
        "metadata_core.dashboard",
        "metadata_core.auto_promotion",
        "model",
    ):
        importlib.import_module(name)


def test_slugify_username_restored_behavior() -> None:
    from utils.identity import slugify_username

    assert slugify_username(" Jane Doe!! ") == "jane_doe"
    assert slugify_username("...Root---") == "root"
    assert len(slugify_username("A" * 80)) == 40


def test_secret_backend_surface_restored() -> None:
    from bio_platform.secrets import get_secret_backend_name, load_or_create_secret

    assert get_secret_backend_name() in {"keyring", "windows-dpapi", "local-file"}
    assert callable(load_or_create_secret)


def _run_direct() -> None:
    tests = [
        test_restored_project_import_surface_files_exist,
        test_import_smoke_for_restored_project_surfaces,
        test_slugify_username_restored_behavior,
        test_secret_backend_surface_restored,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} project import surface restoration tests passed")


if __name__ == "__main__":
    _run_direct()
