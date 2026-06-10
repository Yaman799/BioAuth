"""security.py — central security helpers for BioAuth.

This module intentionally keeps cryptographic primitives and integrity sidecars in one
place so model loading, live-session capture and runtime state use the same rules.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import stat
import subprocess
import sys
import tempfile
import threading
import shutil
from functools import lru_cache

from cryptography.fernet import Fernet

from bio_platform.secrets import get_secret_backend_name, load_or_create_secret
from paths import models_dir

LOGGER = logging.getLogger(__name__)


def _active_security_after_reload():
    """Return the current security module when an imported stale function survived reload."""
    import sys

    active = sys.modules.get(__name__)
    if active is not None and getattr(active, "__dict__", None) is not globals():
        return active
    return None

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
else:
    DATA_BLOB = None  # type: ignore[assignment]

MODELS_DIR = models_dir()
KEY_FILE = os.path.join(MODELS_DIR, "secret.key")
KEY_FILE_DPAPI = os.path.join(MODELS_DIR, "secret.key.dpapi")
HASH_FILE = os.path.join(MODELS_DIR, "model.hash")
CLASSIFIER_HASH_FILE = os.path.join(MODELS_DIR, "classifier.hash")

MODEL_INTEGRITY_LABEL = b"bioauth.model.integrity.v2"
METADATA_INTEGRITY_LABEL = b"bioauth.metadata.integrity.v1"
CLASSIFIER_INTEGRITY_LABEL = b"bioauth.classifier.integrity.v2"

_FILE_LOCK = threading.RLock()


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _calculate_bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _calculate_file_sha256(path: str) -> str:
    return _calculate_bytes_sha256(_read_file_bytes(path))


def _integrity_hmac_key(label: bytes) -> bytes:
    return hmac.new(get_or_create_key(), label, hashlib.sha256).digest()


def _calculate_bytes_hmac(content: bytes, label: bytes) -> str:
    return hmac.new(_integrity_hmac_key(label), content, hashlib.sha256).hexdigest()


def _calculate_file_hmac(path: str, label: bytes) -> str:
    return _calculate_bytes_hmac(_read_file_bytes(path), label)


def _encode_integrity_value(digest: str, scheme: str = "hmac-sha256") -> str:
    return f"{scheme}:{digest}"


def _read_saved_integrity(path: str) -> tuple[str, str]:
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    if ":" in raw:
        scheme, digest = raw.split(":", 1)
        return scheme.strip().lower(), digest.strip().lower()
    return "sha256", raw.strip().lower()


def atomic_write_bytes(path: str, data: bytes) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def _global_model_file() -> str:
    return os.path.join(MODELS_DIR, "model.pkl")


def _model_hash_path(model_path: str) -> str:
    if os.path.normcase(os.path.abspath(model_path)) == os.path.normcase(os.path.abspath(_global_model_file())):
        return HASH_FILE
    return os.path.join(os.path.dirname(model_path), "model.hash")


def _metadata_hash_path(metadata_path: str) -> str:
    return os.path.join(os.path.dirname(metadata_path), "metadata.hash")


def _classifier_hash_path(classifier_path: str) -> str:
    if os.path.normcase(os.path.abspath(classifier_path)) == os.path.normcase(os.path.abspath(os.path.join(MODELS_DIR, "classifier.pkl"))):
        return CLASSIFIER_HASH_FILE
    return os.path.join(os.path.dirname(classifier_path), "classifier.hash")


def _restrict_secret_key_permissions(path: str) -> None:
    """Restrict the local master secret to owner read/write where possible."""
    if not os.path.exists(path):
        return
    try:
        if os.name == "posix":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        elif os.name == "nt":
            import getpass
            user = getpass.getuser()
            if user:
                subprocess.run(
                    ["icacls", path, "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.warning("Failed restricting local secret permissions for %s", os.path.basename(path), exc_info=True)


def secret_storage_backend() -> str:
    """Return the active secret-storage backend name for diagnostics/tests."""
    return get_secret_backend_name()


@lru_cache(maxsize=1)
def get_or_create_key() -> bytes:
    """Return the app's symmetric master key.

    The lru_cache keeps a single in-memory copy for the process lifetime so repeated
    encryption / integrity checks do not re-open the key file or platform secret store
    for every event. Use ``reset_security_caches()`` in tests or if future runtime
    key-rotation flows need to force a refresh.
    """
    return load_or_create_secret(
        secret_name="master-key",
        plaintext_path=KEY_FILE,
        protected_path=KEY_FILE_DPAPI,
        generate_secret=Fernet.generate_key,
        restrict_permissions=_restrict_secret_key_permissions,
    )


def _dpapi_save_key(key: bytes) -> None:
    """Best-effort Windows-only storage using DPAPI, with a plaintext fallback."""
    try:
        blob = _dpapi_protect(key)
        if blob:
            atomic_write_bytes(KEY_FILE_DPAPI, blob)
            _restrict_secret_key_permissions(KEY_FILE_DPAPI)
            return
    except Exception:
        LOGGER.warning("DPAPI key protection failed; falling back to restricted local key file.", exc_info=True)
    try:
        atomic_write_bytes(KEY_FILE, key)
        _restrict_secret_key_permissions(KEY_FILE)
    except Exception:
        LOGGER.exception("Failed writing restricted local master key fallback.")


def _dpapi_load_key() -> bytes | None:
    try:
        if os.path.exists(KEY_FILE_DPAPI):
            blob = _read_file_bytes(KEY_FILE_DPAPI)
            if blob:
                out = _dpapi_unprotect(blob)
                if out:
                    return out
    except Exception:
        LOGGER.warning("Failed loading DPAPI-protected master key; trying restricted local key fallback.", exc_info=True)
        return None
    try:
        if os.path.exists(KEY_FILE):
            key = _read_file_bytes(KEY_FILE)
            return key or None
    except OSError:
        LOGGER.warning("Failed reading restricted local master key fallback.", exc_info=True)
        return None
    return None


def _dpapi_protect(data: bytes) -> bytes | None:
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()

        if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            return None
        try:
            ptr = ctypes.cast(out_blob.pbData, ctypes.POINTER(ctypes.c_char))
            return ctypes.string_at(ptr, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        LOGGER.warning("DPAPI protect operation failed.", exc_info=True)
        return None


def _dpapi_unprotect(blob: bytes) -> bytes | None:
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        in_blob = DATA_BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            return None
        try:
            ptr = ctypes.cast(out_blob.pbData, ctypes.POINTER(ctypes.c_char))
            return ctypes.string_at(ptr, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        LOGGER.warning("DPAPI unprotect operation failed.", exc_info=True)
        return None


def session_state_hmac_key() -> bytes:
    """Derive a dedicated key for HMAC(session_state) from the Fernet secret."""
    master = get_or_create_key()
    return hmac.new(master, b"bioauth.session_state.v1", hashlib.sha256).digest()


def canonical_session_state_json(data: dict) -> str:
    """JSON for signing: sorted keys, no _integrity field."""
    body = {k: v for k, v in data.items() if k != "_integrity"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_session_state_payload(data: dict) -> str:
    payload = canonical_session_state_json(data)
    return hmac.new(session_state_hmac_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_session_state_payload(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    sig = data.get("_integrity")
    if not sig or not isinstance(sig, str):
        return False
    expected = sign_session_state_payload({k: v for k, v in data.items() if k != "_integrity"})
    return hmac.compare_digest(expected, sig)


def persistent_login_hmac_key() -> bytes:
    """Derive a dedicated HMAC key for the remembered-login record."""
    master = get_or_create_key()
    return hmac.new(master, b"bioauth.persistent_login.v1", hashlib.sha256).digest()


def canonical_persistent_login_json(data: dict) -> str:
    body = {k: v for k, v in data.items() if k != "_integrity"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_persistent_login_payload(data: dict) -> str:
    payload = canonical_persistent_login_json(data)
    return hmac.new(persistent_login_hmac_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_persistent_login_payload(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    sig = data.get("_integrity")
    if not sig or not isinstance(sig, str):
        return False
    expected = sign_persistent_login_payload({k: v for k, v in data.items() if k != "_integrity"})
    return hmac.compare_digest(expected, sig)


@lru_cache(maxsize=1)
def get_cipher() -> Fernet:
    """Cached Fernet instance backed by the cached master key for hot paths."""
    return Fernet(get_or_create_key())


def reset_security_caches() -> None:
    """Clear memoized key/cipher state for tests or future key-refresh flows."""
    get_or_create_key.cache_clear()
    get_cipher.cache_clear()


def _rows_to_csv_text(rows: list) -> str:
    return "\n".join(",".join(str(c) for c in row) for row in rows)


def _chunk_dir(filepath: str) -> str:
    return filepath + ".d"


def _counter_path(chunk_dir: str) -> str:
    return os.path.join(chunk_dir, "counter")


def _base_chunk_path(chunk_dir: str) -> str:
    return os.path.join(chunk_dir, "base.enc")


def _chunk_path(chunk_dir: str, index: int) -> str:
    return os.path.join(chunk_dir, f"{int(index):08d}.enc")


def _is_numbered_chunk(path: str) -> bool:
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    return ext == ".enc" and stem.isdigit()


def _iter_numbered_chunks(chunk_dir: str) -> list[str]:
    if not os.path.isdir(chunk_dir):
        return []
    return [
        os.path.join(chunk_dir, name)
        for name in sorted(os.listdir(chunk_dir))
        if _is_numbered_chunk(os.path.join(chunk_dir, name))
    ]


def _encrypt_csv_payload(text: str) -> bytes:
    return get_cipher().encrypt(text.encode("utf-8"))


def _decrypt_legacy_payload(filepath: str, header: str, *, strict: bool = False) -> str:
    if not os.path.exists(filepath):
        return header + "\n"
    data = _read_file_bytes(filepath)
    if not data:
        return header + "\n"
    try:
        return get_cipher().decrypt(data).decode("utf-8")
    except Exception as exc:
        LOGGER.warning("Failed decrypting legacy encrypted file %s; returning header-only fallback.", os.path.basename(filepath), exc_info=True)
        if strict:
            raise ValueError(f"Could not decrypt file: {filepath}") from exc
        return header + "\n"


def _chunk_lines_from_text(text: str, header: str) -> list[str]:
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if lines and lines[0] == header:
        lines = lines[1:]
    return [line for line in lines if line != ""]



def _read_chunk_text(path: str, header: str, *, strict: bool = False) -> str | None:
    try:
        payload = get_cipher().decrypt(_read_file_bytes(path)).decode("utf-8")
    except Exception as exc:
        LOGGER.warning("Failed decrypting chunk %s; skipping chunk.", os.path.basename(path), exc_info=True)
        if strict:
            raise ValueError(f"Could not decrypt chunk: {path}") from exc
        return None
    lines = _chunk_lines_from_text(payload, header)
    return "\n".join(lines)


def _scan_max_chunk_index(chunk_dir: str) -> int:
    max_index = -1
    for chunk_path in _iter_numbered_chunks(chunk_dir):
        try:
            index = int(os.path.splitext(os.path.basename(chunk_path))[0])
        except ValueError:
            continue
        max_index = max(max_index, index)
    return max_index


def _read_counter(chunk_dir: str) -> int:
    counter_path = _counter_path(chunk_dir)
    try:
        with open(counter_path, "r", encoding="utf-8") as handle:
            value = int(handle.read().strip() or "0")
        if value >= 0:
            return value
    except (OSError, ValueError):
        pass
    return _scan_max_chunk_index(chunk_dir) + 1


def _write_counter(chunk_dir: str, value: int) -> None:
    atomic_write_text(_counter_path(chunk_dir), str(max(0, int(value))))


def _chunks_total_size(chunk_dir: str) -> int:
    total = 0
    base_path = _base_chunk_path(chunk_dir)
    if os.path.exists(base_path):
        total += os.path.getsize(base_path)
    for chunk_path in _iter_numbered_chunks(chunk_dir):
        if os.path.exists(chunk_path):
            total += os.path.getsize(chunk_path)
    return total


def _read_chunks(chunk_dir: str, header: str, *, strict: bool = False) -> str:
    body_lines: list[str] = []
    base_path = _base_chunk_path(chunk_dir)
    if os.path.exists(base_path):
        base_text = _read_chunk_text(base_path, header, strict=strict)
        if base_text:
            body_lines.extend(_chunk_lines_from_text(base_text, header))
    for chunk_path in _iter_numbered_chunks(chunk_dir):
        chunk_text = _read_chunk_text(chunk_path, header, strict=strict)
        if chunk_text is None:
            continue
        body_lines.extend(_chunk_lines_from_text(chunk_text, header))
    if body_lines:
        return header + "\n" + "\n".join(body_lines)
    return header + "\n"


def _write_base_chunk(chunk_dir: str, body_text: str) -> None:
    body_text = body_text.rstrip("\n")
    if not body_text:
        base_path = _base_chunk_path(chunk_dir)
        if os.path.exists(base_path):
            try:
                os.remove(base_path)
            except OSError:
                pass
        return
    atomic_write_bytes(_base_chunk_path(chunk_dir), _encrypt_csv_payload(body_text))


def _ensure_chunk_store(filepath: str, header: str) -> str:
    chunk_dir = _chunk_dir(filepath)
    if os.path.isdir(chunk_dir):
        if not os.path.exists(_counter_path(chunk_dir)):
            _write_counter(chunk_dir, _scan_max_chunk_index(chunk_dir) + 1)
        return chunk_dir

    os.makedirs(chunk_dir, exist_ok=True)
    _write_counter(chunk_dir, 0)

    if os.path.exists(filepath):
        legacy_text = _decrypt_legacy_payload(filepath, header, strict=False)
        legacy_body_lines = _chunk_lines_from_text(legacy_text, header)
        if legacy_body_lines:
            _write_base_chunk(chunk_dir, "\n".join(legacy_body_lines))
        try:
            os.remove(filepath)
        except OSError:
            pass

    return chunk_dir


def write_encrypted(filepath: str, rows: list, header: str) -> None:
    """Initialize a fresh live encrypted CSV store using chunked writes."""
    active = _active_security_after_reload()
    if active is not None:
        return active.write_encrypted(filepath, rows, header)
    with _FILE_LOCK:
        chunk_dir = _chunk_dir(filepath)
        if os.path.isdir(chunk_dir):
            shutil.rmtree(chunk_dir, ignore_errors=True)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        os.makedirs(chunk_dir, exist_ok=True)
        _write_counter(chunk_dir, 0)
        if rows:
            body = _rows_to_csv_text(rows)
            atomic_write_bytes(_chunk_path(chunk_dir, 0), _encrypt_csv_payload(body))
            _write_counter(chunk_dir, 1)


def reset_encrypted_file(filepath: str, header: str) -> None:
    write_encrypted(filepath, [], header)


def append_encrypted_row(filepath: str, row: list, header: str) -> None:
    append_encrypted_rows(filepath, [row], header)


def append_encrypted_rows(filepath: str, rows: list, header: str) -> None:
    active = _active_security_after_reload()
    if active is not None:
        return active.append_encrypted_rows(filepath, rows, header)
    if not rows:
        return

    with _FILE_LOCK:
        chunk_dir = _ensure_chunk_store(filepath, header)
        next_index = _read_counter(chunk_dir)
        body = _rows_to_csv_text(rows)
        atomic_write_bytes(_chunk_path(chunk_dir, next_index), _encrypt_csv_payload(body))
        _write_counter(chunk_dir, next_index + 1)


def read_decrypted(filepath: str, header: str, *, strict: bool = False) -> str:
    active = _active_security_after_reload()
    if active is not None:
        return active.read_decrypted(filepath, header, strict=strict)
    chunk_dir = _chunk_dir(filepath)
    with _FILE_LOCK:
        if os.path.isdir(chunk_dir):
            return _read_chunks(chunk_dir, header, strict=strict)
        if os.path.exists(filepath):
            return _decrypt_legacy_payload(filepath, header, strict=strict)
        return header + "\n"


def compact_chunks(filepath: str, header: str) -> None:
    active = _active_security_after_reload()
    if active is not None:
        return active.compact_chunks(filepath, header)
    with _FILE_LOCK:
        chunk_dir = _chunk_dir(filepath)
        if not os.path.isdir(chunk_dir):
            return
        content = _read_chunks(chunk_dir, header)
        atomic_write_bytes(filepath, _encrypt_csv_payload(content.rstrip("\n") + "\n"))
        shutil.rmtree(chunk_dir, ignore_errors=True)


def rotate_encrypted(filepath: str, header: str, max_bytes: int = 5 * 1024 * 1024) -> None:
    with _FILE_LOCK:
        chunk_dir = _chunk_dir(filepath)
        if os.path.isdir(chunk_dir):
            if _chunks_total_size(chunk_dir) < max_bytes:
                return
            chunk_paths = _iter_numbered_chunks(chunk_dir)
            if not chunk_paths:
                return
            merge_count = max(1, len(chunk_paths) // 2)
            to_merge = chunk_paths[:merge_count]
            merged_lines: list[str] = []
            base_path = _base_chunk_path(chunk_dir)
            if os.path.exists(base_path):
                base_text = _read_chunk_text(base_path, header)
                if base_text:
                    merged_lines.extend(_chunk_lines_from_text(base_text, header))
            for chunk_path in to_merge:
                chunk_text = _read_chunk_text(chunk_path, header)
                if chunk_text is None:
                    continue
                merged_lines.extend(_chunk_lines_from_text(chunk_text, header))
            if merged_lines:
                _write_base_chunk(chunk_dir, "\n".join(merged_lines))
            for chunk_path in to_merge:
                try:
                    os.remove(chunk_path)
                except OSError:
                    pass
            if not os.path.exists(_counter_path(chunk_dir)):
                _write_counter(chunk_dir, _scan_max_chunk_index(chunk_dir) + 1)
            return

        if not os.path.exists(filepath):
            return
        if os.path.getsize(filepath) < max_bytes:
            return

        content = _decrypt_legacy_payload(filepath, header, strict=False)
        lines = content.splitlines()
        if not lines:
            return
        if len(lines) == 1:
            keep = lines
        else:
            data_lines = lines[1:]
            keep_start = max(0, len(data_lines) // 2)
            keep = [lines[0]] + data_lines[keep_start:]
        atomic_write_bytes(filepath, _encrypt_csv_payload("\n".join(keep)))


def _verify_integrity(raw_bytes: bytes, hash_path: str, hmac_label: bytes) -> bool:
    if not os.path.exists(hash_path):
        return False
    scheme, saved_digest = _read_saved_integrity(hash_path)
    if scheme == "hmac-sha256":
        current = _calculate_bytes_hmac(raw_bytes, hmac_label)
    else:
        current = _calculate_bytes_sha256(raw_bytes)
    return hmac.compare_digest(current, saved_digest)


def save_model_hash(model_path: str) -> None:
    hash_path = _model_hash_path(model_path)
    digest = _calculate_file_hmac(model_path, MODEL_INTEGRITY_LABEL)
    atomic_write_text(hash_path, _encode_integrity_value(digest))


def verify_model_hash(model_path: str, raw_bytes: bytes | None = None) -> bool:
    if not os.path.exists(model_path):
        return True
    raw = _read_file_bytes(model_path) if raw_bytes is None else raw_bytes
    return _verify_integrity(raw, _model_hash_path(model_path), MODEL_INTEGRITY_LABEL)


def save_metadata_hash(metadata_path: str) -> None:
    digest = _calculate_file_hmac(metadata_path, METADATA_INTEGRITY_LABEL)
    atomic_write_text(_metadata_hash_path(metadata_path), _encode_integrity_value(digest))


def verify_metadata_hash(metadata_path: str, raw_bytes: bytes | None = None) -> bool:
    if not os.path.exists(metadata_path):
        return True
    raw = _read_file_bytes(metadata_path) if raw_bytes is None else raw_bytes
    return _verify_integrity(raw, _metadata_hash_path(metadata_path), METADATA_INTEGRITY_LABEL)


def save_classifier_hash(classifier_path: str) -> None:
    """Write the classifier integrity sidecar using keyed HMAC with SHA256 fallback support."""
    digest = _calculate_file_hmac(classifier_path, CLASSIFIER_INTEGRITY_LABEL)
    atomic_write_text(_classifier_hash_path(classifier_path), _encode_integrity_value(digest))


def verify_classifier_hash(classifier_path: str, raw_bytes: bytes | None = None) -> bool:
    if not os.path.exists(classifier_path):
        return True
    raw = _read_file_bytes(classifier_path) if raw_bytes is None else raw_bytes
    return _verify_integrity(raw, _classifier_hash_path(classifier_path), CLASSIFIER_INTEGRITY_LABEL)


def remove_classifier_hash() -> None:
    if os.path.exists(CLASSIFIER_HASH_FILE):
        try:
            os.remove(CLASSIFIER_HASH_FILE)
        except OSError:
            pass


def save_user_classifier_hash(classifier_path: str) -> None:
    digest = _calculate_file_hmac(classifier_path, CLASSIFIER_INTEGRITY_LABEL)
    atomic_write_text(_classifier_hash_path(classifier_path), _encode_integrity_value(digest))


def verify_user_classifier_hash(classifier_path: str, raw_bytes: bytes | None = None) -> bool:
    if not os.path.exists(classifier_path):
        return True
    raw = _read_file_bytes(classifier_path) if raw_bytes is None else raw_bytes
    return _verify_integrity(raw, _classifier_hash_path(classifier_path), CLASSIFIER_INTEGRITY_LABEL)


def remove_user_classifier_hash(classifier_path: str) -> None:
    hash_path = _classifier_hash_path(classifier_path)
    if os.path.exists(hash_path):
        try:
            os.remove(hash_path)
        except OSError:
            pass
