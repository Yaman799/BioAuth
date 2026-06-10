from __future__ import annotations

from typing import Callable

CANDIDATE_ARTIFACT_SCHEMA_VERSION = "bioauth-candidate-artifact-v1"


CANDIDATE_ARTIFACT_MANIFEST_SCHEMA_VERSION = "bioauth-candidate-artifact-manifest-v1"


CLASSICAL_CANDIDATE_ARTIFACT_BUILDER_VERSION = "p2b1-classical-candidate-artifact-builders-v1"


CLASSICAL_CANDIDATE_IDS: tuple[str, ...] = (
    "classic_lof",
    "classic_one_class_svm",
    "classic_gmm",
    "classic_scaled_manhattan",
    "classic_nn_mahalanobis",
)


CLASSICAL_CANDIDATE_ARTIFACT_FILENAMES: dict[str, str] = {
    "classic_lof": "classic_lof.pkl",
    "classic_one_class_svm": "classic_one_class_svm.pkl",
    "classic_gmm": "classic_gmm.pkl",
    "classic_scaled_manhattan": "classic_scaled_manhattan.pkl",
    "classic_nn_mahalanobis": "classic_nn_mahalanobis.pkl",
}


OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_BUILDER_VERSION = "p2b2-optional-supervised-candidate-artifact-builders-v1"


COMBINED_CANDIDATE_ARTIFACT_BUILDER_VERSION = "p2b4-report-only-candidate-artifacts-v1"


OPTIONAL_SUPERVISED_CANDIDATE_IDS: tuple[str, ...] = (
    "supervised_xgboost",
    "supervised_lightgbm",
    "supervised_catboost",
)


OPTIONAL_SUPERVISED_CANDIDATE_ARTIFACT_FILENAMES: dict[str, str] = {
    "supervised_xgboost": "supervised_xgboost.pkl",
    "supervised_lightgbm": "supervised_lightgbm.pkl",
    "supervised_catboost": "supervised_catboost.pkl",
}


DEEP_ONECLASS_CANDIDATE_ARTIFACT_BUILDER_VERSION = "p2b3-mouse-and-oneclass-deep-artifact-builders-v1"


DEEP_ONECLASS_CANDIDATE_IDS: tuple[str, ...] = (
    "mouse_autoencoder",
    "mouse_deep_svdd",
    "oneclass_lstm_autoencoder",
    "oneclass_conv_autoencoder",
    "oneclass_deep_svdd",
)


DEEP_ONECLASS_CANDIDATE_ARTIFACT_FILENAMES: dict[str, str] = {
    "mouse_autoencoder": "mouse_autoencoder.pt",
    "mouse_deep_svdd": "mouse_deep_svdd.pt",
    "oneclass_lstm_autoencoder": "oneclass_lstm_autoencoder.pt",
    "oneclass_conv_autoencoder": "oneclass_conv_autoencoder.pt",
    "oneclass_deep_svdd": "oneclass_deep_svdd.pt",
}


KEYBOARD_DEEP_CANDIDATE_ARTIFACT_BUILDER_VERSION = "p2b4-keyboard-deep-artifact-builders-v1"


KEYBOARD_DEEP_CANDIDATE_IDS: tuple[str, ...] = (
    "keyboard_bigru_cnn_attention",
    "keyboard_type2branch",
    "keyboard_typeformer",
    "keyboard_siamese_triplet",
)


KEYBOARD_DEEP_CANDIDATE_ARTIFACT_FILENAMES: dict[str, str] = {
    "keyboard_bigru_cnn_attention": "keyboard_bigru_cnn_attention.pt",
    "keyboard_type2branch": "keyboard_type2branch.pt",
    "keyboard_typeformer": "keyboard_typeformer.pt",
    "keyboard_siamese_triplet": "keyboard_siamese_triplet.pt",
}


DEEP_SEQUENCE_CANDIDATE_ARTIFACT_BUILDER_VERSION = "phase3-deep-sequence-candidate-artifact-builders-v1"


DEEP_SEQUENCE_CANDIDATE_IDS: tuple[str, ...] = (
    "mouse_resnet_gru",
    "combined_cnn_lstm",
)


DEEP_SEQUENCE_CANDIDATE_ARTIFACT_FILENAMES: dict[str, str] = {
    "mouse_resnet_gru": "mouse_resnet_gru.pt",
    "combined_cnn_lstm": "combined_cnn_lstm.pt",
}


ALL_REPORT_ONLY_CANDIDATE_IDS: tuple[str, ...] = (
    *CLASSICAL_CANDIDATE_IDS,
    *OPTIONAL_SUPERVISED_CANDIDATE_IDS,
    *DEEP_ONECLASS_CANDIDATE_IDS,
    *KEYBOARD_DEEP_CANDIDATE_IDS,
    *DEEP_SEQUENCE_CANDIDATE_IDS,
)


OPTIONAL_SUPERVISED_DEPENDENCIES: dict[str, str] = {
    "supervised_xgboost": "xgboost",
    "supervised_lightgbm": "lightgbm",
    "supervised_catboost": "catboost",
}


OPTIONAL_SUPERVISED_MODEL_FAMILIES: dict[str, str] = {
    "supervised_xgboost": "xgboost",
    "supervised_lightgbm": "lightgbm",
    "supervised_catboost": "catboost",
}


MIN_SUPERVISED_OWNER_SAMPLES = 10


MIN_SUPERVISED_INTRUDER_SAMPLES = 1


RECOMMENDED_SUPERVISED_INTRUDER_SAMPLES = 10


MIN_DEEP_SEQUENCE_WINDOWS = 4


MIN_DEEP_SEQUENCE_LENGTH = 3


MIN_KEYBOARD_SEQUENCE_WINDOWS = 4


MIN_KEYBOARD_SEQUENCE_LENGTH = 3


MIN_DEEP_SEQUENCE_NATIVE_WINDOWS = 4


MIN_COMBINED_SEQUENCE_WINDOWS = 4


MIN_TYPEFORMER_FREE_TEXT_LENGTH = 8


DEFAULT_DEEP_MAX_EPOCHS = 3


DEFAULT_DEEP_BATCH_SIZE = 8


DEFAULT_DEEP_LEARNING_RATE = 1e-3


NEAR_CONSTANT_STD_EPSILON = 1e-8


MANIFEST_FILENAME = "candidate_artifacts_manifest.json"


DEFAULT_THRESHOLD_QUANTILE = 0.95


MAX_DENSITY_MODEL_FEATURES = 128


_MIN_CLASSICAL_SAMPLES = {
    "classic_scaled_manhattan": 2,
    "classic_nn_mahalanobis": 2,
    "classic_one_class_svm": 5,
    "classic_lof": 5,
    "classic_gmm": 4,
}


AtomicBytesWriter = Callable[[str, bytes], None]


AtomicTextWriter = Callable[[str, str], None]
