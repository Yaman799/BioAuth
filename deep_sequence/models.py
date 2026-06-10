from __future__ import annotations

import importlib.util
from functools import lru_cache
from typing import Any, Sequence

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None
DEFAULT_SEQUENCE_CONV_CHANNELS = 32
DEFAULT_SEQUENCE_HIDDEN_SIZE = 32
DEFAULT_SEQUENCE_DROPOUT = 0.15


@lru_cache(maxsize=1)
def _torch_runtime():
    if not TORCH_AVAILABLE:
        raise RuntimeError("PyTorch is not available; SequenceCnnLstm cannot be constructed.")
    import torch
    import torch.nn as nn

    return torch, nn


@lru_cache(maxsize=1)
def _sequence_impl_class():
    _torch, nn = _torch_runtime()

    class _SequenceCnnLstm(nn.Module):
        def __init__(self, *, feature_dim: int, conv_channels: int = DEFAULT_SEQUENCE_CONV_CHANNELS, hidden_size: int = DEFAULT_SEQUENCE_HIDDEN_SIZE, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            in_features = max(1, int(feature_dim))
            conv_out = max(8, int(conv_channels))
            hidden = max(8, int(hidden_size))
            drop = max(0.0, min(0.5, float(dropout)))
            self.conv = nn.Sequential(
                nn.Conv1d(in_features, conv_out, kernel_size=3, padding=1), nn.ReLU(),
                nn.Conv1d(conv_out, conv_out, kernel_size=3, padding=1), nn.ReLU(), nn.Dropout(drop),
            )
            self.lstm = nn.LSTM(input_size=conv_out, hidden_size=hidden, batch_first=True)
            self.head = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(drop), nn.Linear(hidden, 1))

        def forward(self, inputs: Any):
            x = inputs.float().transpose(1, 2)
            x = self.conv(x).transpose(1, 2)
            _outputs, (hidden, _cell) = self.lstm(x)
            return self.head(hidden[-1]).squeeze(-1)

    return _SequenceCnnLstm


class SequenceCnnLstm:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        impl = _sequence_impl_class()
        return impl(*args, **kwargs)


DEFAULT_KEYBOARD_SEQUENCE_FEATURES = (
    "key_hold_mean",
    "key_hold_std",
    "flight_mean",
    "flight_std",
    "keys_per_second",
    "backspace_rate",
    "typing_burst_rate",
    "digraph_latency_mean",
)
DEFAULT_MOUSE_SEQUENCE_FEATURES = (
    "dx",
    "dy",
    "distance",
    "velocity",
    "acceleration",
    "angle_change",
    "click_state",
    "scroll_delta",
    "drag_state",
)
DEEP_VERIFIER_SCORE_DIRECTION = "higher_score_more_suspicious"
DEEP_VERIFIER_EXPERIMENTAL = True
DEEP_VERIFIER_CAN_LOCK_ALONE = False


def _assert_sequence_tensor_shape(inputs: Any, *, min_sequence_length: int = 2):
    if not hasattr(inputs, "dim") or inputs.dim() != 3:
        raise ValueError("expected NTF sequence tensor with shape (batch, sequence, features)")
    if int(inputs.shape[1]) < int(min_sequence_length):
        raise ValueError("sequence_too_short")
    if int(inputs.shape[2]) <= 0:
        raise ValueError("feature_dim_missing")


@lru_cache(maxsize=1)
def _keyboard_impl_class():
    _torch, nn = _torch_runtime()

    class _KeyboardBiGruCnnAttention(nn.Module):
        """Experimental keyboard verifier: 1D-CNN + BiGRU + attention pooling.

        Input layout is NTF (batch, sequence, features). Output is a single logit
        per sequence; higher sigmoid(logit) means more suspicious/intruder-like.
        """

        def __init__(self, *, feature_dim: int, cnn_channels: int = 32, gru_hidden_size: int = 32, attention_hidden_size: int = 32, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            in_features = max(1, int(feature_dim))
            channels = max(8, int(cnn_channels))
            hidden = max(8, int(gru_hidden_size))
            attn_hidden = max(8, int(attention_hidden_size))
            drop = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = in_features
            self.experimental = True
            self.can_lock_alone = False
            self.score_direction = DEEP_VERIFIER_SCORE_DIRECTION
            self.cnn_branch = nn.Sequential(
                nn.Conv1d(in_features, channels, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Conv1d(channels, channels, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Dropout(drop),
            )
            self.bigru_branch = nn.GRU(input_size=in_features, hidden_size=hidden, batch_first=True, bidirectional=True)
            joined_dim = channels + (2 * hidden)
            self.attention = nn.Sequential(
                nn.Linear(joined_dim, attn_hidden),
                nn.Tanh(),
                nn.Linear(attn_hidden, 1),
            )
            self.head = nn.Sequential(
                nn.Linear(joined_dim, max(8, hidden)),
                nn.ReLU(),
                nn.Dropout(drop),
                nn.Linear(max(8, hidden), 1),
            )

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            x = inputs.float()
            local = self.cnn_branch(x.transpose(1, 2)).transpose(1, 2)
            temporal, _hidden = self.bigru_branch(x)
            joined = _torch.cat([local, temporal], dim=-1)
            weights = _torch.softmax(self.attention(joined), dim=1)
            pooled = (weights * joined).sum(dim=1)
            return self.head(pooled).squeeze(-1)

    return _KeyboardBiGruCnnAttention


@lru_cache(maxsize=1)
def _mouse_impl_class():
    _torch, nn = _torch_runtime()

    class _ResidualTemporalBlock(nn.Module):
        def __init__(self, channels: int, *, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            drop = max(0.0, min(0.5, float(dropout)))
            self.net = nn.Sequential(
                nn.Conv1d(channels, channels, kernel_size=3, padding=1),
                nn.BatchNorm1d(channels),
                nn.ReLU(),
                nn.Dropout(drop),
                nn.Conv1d(channels, channels, kernel_size=3, padding=1),
                nn.BatchNorm1d(channels),
            )
            self.activation = nn.ReLU()

        def forward(self, x: Any):
            return self.activation(x + self.net(x))

    class _MouseResNetGruVerifier(nn.Module):
        """Experimental LT-AMouse-inspired 1D-ResNet + GRU verifier.

        Input layout is NTF (batch, sequence, features). Output is a single logit
        per sequence; higher sigmoid(logit) means more suspicious/intruder-like.
        """

        def __init__(self, *, feature_dim: int, channels: int = 32, residual_blocks: int = 2, gru_hidden_size: int = 32, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            in_features = max(1, int(feature_dim))
            ch = max(8, int(channels))
            hidden = max(8, int(gru_hidden_size))
            blocks = max(1, int(residual_blocks))
            drop = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = in_features
            self.experimental = True
            self.can_lock_alone = False
            self.score_direction = DEEP_VERIFIER_SCORE_DIRECTION
            self.input_projection = nn.Sequential(
                nn.Conv1d(in_features, ch, kernel_size=1),
                nn.BatchNorm1d(ch),
                nn.ReLU(),
            )
            self.residual_stack = nn.Sequential(*[_ResidualTemporalBlock(ch, dropout=drop) for _ in range(blocks)])
            self.gru = nn.GRU(input_size=ch, hidden_size=hidden, batch_first=True)
            self.head = nn.Sequential(
                nn.Linear(hidden, hidden),
                nn.ReLU(),
                nn.Dropout(drop),
                nn.Linear(hidden, 1),
            )

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            x = inputs.float().transpose(1, 2)
            x = self.input_projection(x)
            x = self.residual_stack(x).transpose(1, 2)
            outputs, _hidden = self.gru(x)
            return self.head(outputs[:, -1, :]).squeeze(-1)

    return _MouseResNetGruVerifier


class KeyboardBiGruCnnAttention:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        impl = _keyboard_impl_class()
        return impl(*args, **kwargs)


class MouseResNetGruVerifier:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        impl = _mouse_impl_class()
        return impl(*args, **kwargs)



@lru_cache(maxsize=1)
def _lstm_autoencoder_impl_class():
    _torch, nn = _torch_runtime()

    class _SequenceLstmAutoencoder(nn.Module):
        """One-class sequence LSTM autoencoder architecture.

        Forward returns a reconstruction with the same NTF shape as the input.
        Scoring is intentionally not embedded here; Hybrid Candidate adapters
        must load trained artifacts and thresholds before reporting risk.
        """

        def __init__(self, *, feature_dim: int, hidden_size: int = DEFAULT_SEQUENCE_HIDDEN_SIZE, latent_size: int = 16, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            in_features = max(1, int(feature_dim))
            hidden = max(8, int(hidden_size))
            latent = max(4, int(latent_size))
            drop = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = in_features
            self.can_lock_alone = False
            self.score_direction = "higher_reconstruction_error_more_suspicious"
            self.encoder = nn.LSTM(input_size=in_features, hidden_size=hidden, batch_first=True)
            self.to_latent = nn.Sequential(nn.Linear(hidden, latent), nn.Tanh(), nn.Dropout(drop))
            self.from_latent = nn.Sequential(nn.Linear(latent, hidden), nn.ReLU())
            self.decoder = nn.LSTM(input_size=hidden, hidden_size=hidden, batch_first=True)
            self.output_projection = nn.Linear(hidden, in_features)

        def encode(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            _outputs, (hidden, _cell) = self.encoder(inputs.float())
            return self.to_latent(hidden[-1])

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            x = inputs.float()
            latent = self.encode(x)
            repeated = self.from_latent(latent).unsqueeze(1).repeat(1, x.shape[1], 1)
            decoded, _hidden = self.decoder(repeated)
            return self.output_projection(decoded)

    return _SequenceLstmAutoencoder


@lru_cache(maxsize=1)
def _conv_autoencoder_impl_class():
    _torch, nn = _torch_runtime()

    class _SequenceConvAutoencoder(nn.Module):
        """One-class 1D convolutional sequence autoencoder architecture.

        Forward returns a reconstruction with the same NTF shape as the input.
        Risk must be computed by an artifact-gated offline adapter.
        """

        def __init__(self, *, feature_dim: int, channels: int = DEFAULT_SEQUENCE_CONV_CHANNELS, latent_channels: int = 16, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            in_features = max(1, int(feature_dim))
            ch = max(8, int(channels))
            latent = max(4, int(latent_channels))
            drop = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = in_features
            self.can_lock_alone = False
            self.score_direction = "higher_reconstruction_error_more_suspicious"
            self.encoder = nn.Sequential(
                nn.Conv1d(in_features, ch, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Dropout(drop),
                nn.Conv1d(ch, latent, kernel_size=3, padding=1),
                nn.ReLU(),
            )
            self.decoder = nn.Sequential(
                nn.Conv1d(latent, ch, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Dropout(drop),
                nn.Conv1d(ch, in_features, kernel_size=3, padding=1),
            )

        def encode(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            return self.encoder(inputs.float().transpose(1, 2))

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            encoded = self.encode(inputs)
            return self.decoder(encoded).transpose(1, 2)

    return _SequenceConvAutoencoder


@lru_cache(maxsize=1)
def _deep_svdd_impl_class():
    _torch, nn = _torch_runtime()

    class _SequenceDeepSvddNetwork(nn.Module):
        """Encoder/head used by one-class Deep SVDD candidates.

        Forward returns an embedding. Distance-to-center risk is only valid when
        a trained artifact supplies the center vector and threshold.
        """

        def __init__(self, *, feature_dim: int, embedding_dim: int = 16, hidden_size: int = DEFAULT_SEQUENCE_HIDDEN_SIZE, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            in_features = max(1, int(feature_dim))
            hidden = max(8, int(hidden_size))
            embedding = max(2, int(embedding_dim))
            drop = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = in_features
            self.embedding_dim = embedding
            self.can_lock_alone = False
            self.score_direction = "higher_distance_to_center_more_suspicious"
            self.encoder = nn.GRU(input_size=in_features, hidden_size=hidden, batch_first=True)
            self.head = nn.Sequential(
                nn.Linear(hidden, hidden),
                nn.ReLU(),
                nn.Dropout(drop),
                nn.Linear(hidden, embedding),
            )

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            outputs, _hidden = self.encoder(inputs.float())
            pooled = outputs.mean(dim=1)
            return self.head(pooled)

    return _SequenceDeepSvddNetwork


class SequenceLstmAutoencoder:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        impl = _lstm_autoencoder_impl_class()
        return impl(*args, **kwargs)


class SequenceConvAutoencoder:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        impl = _conv_autoencoder_impl_class()
        return impl(*args, **kwargs)


class SequenceDeepSvddNetwork:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        impl = _deep_svdd_impl_class()
        return impl(*args, **kwargs)


class MouseAutoencoder:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("feature_dim", len(DEFAULT_MOUSE_SEQUENCE_FEATURES))
        impl = _conv_autoencoder_impl_class()
        return impl(*args, **kwargs)


class MouseDeepSvddNetwork:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("feature_dim", len(DEFAULT_MOUSE_SEQUENCE_FEATURES))
        impl = _deep_svdd_impl_class()
        return impl(*args, **kwargs)



@lru_cache(maxsize=1)
def _keyboard_type2branch_impl_class():
    _torch, nn = _torch_runtime()

    class _KeyboardType2BranchInspired(nn.Module):
        """Type2Branch-inspired offline keyboard embedding model.

        This first version intentionally says inspired: it combines a BiGRU
        branch, a 1D-CNN branch, and attention fusion, but does not claim the
        full academic objective. Scores are only valid through artifact-gated
        offline adapters.
        """

        def __init__(self, *, feature_dim: int, cnn_channels: int = 32, gru_hidden_size: int = 32, embedding_dim: int = 32, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            f = max(1, int(feature_dim)); c = max(8, int(cnn_channels)); h = max(8, int(gru_hidden_size)); e = max(4, int(embedding_dim)); d = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = f; self.embedding_dim = e; self.can_lock_alone = False; self.score_direction = "higher_distance_to_template_more_suspicious"
            self.bigru_branch = nn.GRU(input_size=f, hidden_size=h, batch_first=True, bidirectional=True)
            self.cnn_branch = nn.Sequential(nn.Conv1d(f, c, 3, padding=1), nn.ReLU(), nn.Dropout(d), nn.Conv1d(c, c, 3, padding=1), nn.ReLU())
            joined = (2 * h) + c
            self.attention = nn.Sequential(nn.Linear(joined, max(8, h)), nn.Tanh(), nn.Linear(max(8, h), 1))
            self.projection = nn.Sequential(nn.Linear(joined, max(e, h)), nn.ReLU(), nn.Dropout(d), nn.Linear(max(e, h), e))

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            x = inputs.float()
            temporal, _hidden = self.bigru_branch(x)
            local = self.cnn_branch(x.transpose(1, 2)).transpose(1, 2)
            joined = _torch.cat([temporal, local], dim=-1)
            weights = _torch.softmax(self.attention(joined), dim=1)
            pooled = (weights * joined).sum(dim=1)
            return nn.functional.normalize(self.projection(pooled), p=2, dim=-1)

    return _KeyboardType2BranchInspired


@lru_cache(maxsize=1)
def _keyboard_typeformer_impl_class():
    _torch, nn = _torch_runtime()

    class _PositionalEncoding(nn.Module):
        def __init__(self, dim: int, max_length: int = 512) -> None:
            super().__init__()
            dim = max(2, int(dim)); max_length = max(8, int(max_length))
            position = _torch.arange(max_length, dtype=_torch.float32).unsqueeze(1)
            div = _torch.exp(_torch.arange(0, dim, 2, dtype=_torch.float32) * (-_torch.log(_torch.tensor(10000.0)) / dim))
            pe = _torch.zeros(max_length, dim, dtype=_torch.float32)
            pe[:, 0::2] = _torch.sin(position * div)
            if dim > 1:
                pe[:, 1::2] = _torch.cos(position * div[:pe[:, 1::2].shape[1]])
            self.register_buffer("pe", pe.unsqueeze(0), persistent=False)

        def forward(self, x: Any):
            return x + self.pe[:, :x.shape[1], :].to(device=x.device, dtype=x.dtype)

    class _KeyboardTypeFormerInspired(nn.Module):
        """TypeFormer-inspired offline keyboard free-text encoder."""

        def __init__(self, *, feature_dim: int, model_dim: int = 32, num_heads: int = 4, num_layers: int = 2, embedding_dim: int = 32, feedforward_dim: int = 64, dropout: float = DEFAULT_SEQUENCE_DROPOUT, min_free_text_length: int = 8) -> None:
            super().__init__()
            f = max(1, int(feature_dim)); dim = max(8, int(model_dim)); heads = max(1, int(num_heads))
            while dim % heads != 0 and heads > 1: heads -= 1
            e = max(4, int(embedding_dim)); d = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = f; self.model_dim = dim; self.embedding_dim = e; self.min_free_text_length = max(2, int(min_free_text_length)); self.can_lock_alone = False; self.score_direction = "higher_distance_to_template_more_suspicious"
            self.input_projection = nn.Linear(f, dim)
            self.position_encoding = _PositionalEncoding(dim)
            layer = nn.TransformerEncoderLayer(d_model=dim, nhead=heads, dim_feedforward=max(dim, int(feedforward_dim)), dropout=d, batch_first=True, activation="gelu")
            self.encoder = nn.TransformerEncoder(layer, num_layers=max(1, int(num_layers)))
            self.pool_attention = nn.Sequential(nn.Linear(dim, dim), nn.Tanh(), nn.Linear(dim, 1))
            self.projection = nn.Sequential(nn.Linear(dim, dim), nn.GELU(), nn.Dropout(d), nn.Linear(dim, e))

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=self.min_free_text_length)
            encoded = self.encoder(self.position_encoding(self.input_projection(inputs.float())))
            weights = _torch.softmax(self.pool_attention(encoded), dim=1)
            pooled = (weights * encoded).sum(dim=1)
            return nn.functional.normalize(self.projection(pooled), p=2, dim=-1)

    return _KeyboardTypeFormerInspired


@lru_cache(maxsize=1)
def _keyboard_siamese_triplet_impl_class():
    _torch, nn = _torch_runtime()

    class _KeyboardSiameseTripletVerifier(nn.Module):
        """Shared encoder for offline Siamese/Triplet keyboard verification."""

        def __init__(self, *, feature_dim: int, hidden_size: int = 32, embedding_dim: int = 32, dropout: float = DEFAULT_SEQUENCE_DROPOUT) -> None:
            super().__init__()
            f = max(1, int(feature_dim)); h = max(8, int(hidden_size)); e = max(4, int(embedding_dim)); d = max(0.0, min(0.5, float(dropout)))
            self.feature_dim = f; self.embedding_dim = e; self.can_lock_alone = False; self.score_direction = "higher_distance_to_reference_more_suspicious"
            self.encoder = nn.GRU(input_size=f, hidden_size=h, batch_first=True, bidirectional=True)
            self.projection = nn.Sequential(nn.Linear(2*h, h), nn.ReLU(), nn.Dropout(d), nn.Linear(h, e))

        def forward(self, inputs: Any):
            _assert_sequence_tensor_shape(inputs, min_sequence_length=2)
            outputs, _hidden = self.encoder(inputs.float())
            return nn.functional.normalize(self.projection(outputs.mean(dim=1)), p=2, dim=-1)

        def pair_distance(self, left: Any, right: Any):
            return _torch.linalg.vector_norm(self.forward(left) - self.forward(right), dim=-1)

        def triplet_distances(self, anchor: Any, positive: Any, negative: Any):
            anchor_embedding = self.forward(anchor)
            return (_torch.linalg.vector_norm(anchor_embedding - self.forward(positive), dim=-1), _torch.linalg.vector_norm(anchor_embedding - self.forward(negative), dim=-1))

    return _KeyboardSiameseTripletVerifier


class KeyboardType2BranchInspired:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return _keyboard_type2branch_impl_class()(*args, **kwargs)


class KeyboardTypeFormerInspired:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return _keyboard_typeformer_impl_class()(*args, **kwargs)


class KeyboardSiameseTripletVerifier:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        return _keyboard_siamese_triplet_impl_class()(*args, **kwargs)


def advanced_keyboard_metadata(*, architecture: str, feature_names: Sequence[str] | None = None, sequence_length: int | None = None, min_free_text_length: int | None = None, threshold_source: str = "artifact_required") -> dict[str, Any]:
    metadata = deep_verifier_metadata(architecture=architecture, input_modality="keyboard", feature_names=feature_names, sequence_length=sequence_length, threshold_source=threshold_source)
    metadata.update({"schema_version": "advanced-keyboard-candidate-metadata-v1", "artifact_required": True, "weights_required": True, "threshold_required": True, "training_metadata_required": True, "reference_template_required": True, "untrained_scores_valid": False, "can_vote_default": False, "can_lock_alone": False, "can_influence_device": False, "runtime_authoritative": False, "min_free_text_length": int(min_free_text_length or 0)})
    return metadata

def one_class_deep_metadata(*, architecture: str, input_modality: str, feature_names: Sequence[str] | None = None, sequence_length: int | None = None, threshold_source: str = "artifact_required") -> dict[str, Any]:
    metadata = deep_verifier_metadata(
        architecture=architecture,
        input_modality=input_modality,
        feature_names=feature_names,
        sequence_length=sequence_length,
        threshold_source=threshold_source,
    )
    metadata.update(
        {
            "schema_version": "one-class-deep-metadata-v1",
            "artifact_required": True,
            "weights_required": True,
            "threshold_required": True,
            "training_metadata_required": True,
            "untrained_scores_valid": False,
            "can_vote_default": False,
            "can_lock_alone": False,
            "can_influence_device": False,
            "runtime_authoritative": False,
        }
    )
    return metadata

def deep_verifier_metadata(*, architecture: str, input_modality: str, feature_names: Sequence[str] | None = None, sequence_length: int | None = None, threshold_source: str = "not_calibrated") -> dict[str, Any]:
    features = [str(name) for name in list(feature_names or []) if str(name or "").strip()]
    return {
        "schema_version": "phase8-deep-verifier-metadata-v1",
        "architecture": str(architecture),
        "input_modality": str(input_modality),
        "sequence_length": int(sequence_length or 0),
        "feature_schema": features,
        "feature_count": int(len(features)),
        "score_direction": DEEP_VERIFIER_SCORE_DIRECTION,
        "threshold_source": str(threshold_source or "not_calibrated"),
        "experimental": True,
        "runtime_authoritative": False,
        "can_lock_alone": False,
        "can_influence_device": False,
        "default_decision": "abstain",
        "status": "experimental_shadow_only",
    }


__all__ = [
    "TORCH_AVAILABLE",
    "DEFAULT_SEQUENCE_CONV_CHANNELS",
    "DEFAULT_SEQUENCE_HIDDEN_SIZE",
    "DEFAULT_SEQUENCE_DROPOUT",
    "SequenceCnnLstm",
    "KeyboardBiGruCnnAttention",
    "MouseResNetGruVerifier",
    "SequenceLstmAutoencoder",
    "SequenceConvAutoencoder",
    "SequenceDeepSvddNetwork",
    "MouseAutoencoder",
    "MouseDeepSvddNetwork",
    "KeyboardType2BranchInspired",
    "KeyboardTypeFormerInspired",
    "KeyboardSiameseTripletVerifier",
    "DEFAULT_KEYBOARD_SEQUENCE_FEATURES",
    "DEFAULT_MOUSE_SEQUENCE_FEATURES",
    "DEEP_VERIFIER_SCORE_DIRECTION",
    "DEEP_VERIFIER_EXPERIMENTAL",
    "DEEP_VERIFIER_CAN_LOCK_ALONE",
    "deep_verifier_metadata",
    "one_class_deep_metadata",
    "advanced_keyboard_metadata",
    "_torch_runtime",
]
