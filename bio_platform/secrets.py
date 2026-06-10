"""Secret-storage helpers for BioAuth.

The module is intentionally independent from :mod:`security` so it can be
imported while the security module is still initializing.  It preserves the
startup contract used by ``security.get_or_create_key``:

* Windows: prefer a current-user DPAPI-protected file.
* Other platforms: prefer a usable Python keyring backend.
* All platforms: load an existing secret before generating a new one.
* Fallback: use an owner-restricted local file when platform storage is not
  available, keeping encrypted settings and HMAC integrity operational.
"""

from __future__ import annotations

import base64
import ctypes
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Callable, Optional

LOGGER = logging.getLogger(__name__)

try:  # Tests monkeypatch this symbol to force local-file fallback behavior.
    import keyring as keyring  # type: ignore
except Exception:  # pragma: no cover - depends on optional host keyring support
    keyring = None  # type: ignore[assignment]

_KEYRING_SERVICE = "BioAuth"
_KEYRING_ACCOUNT_PREFIX = "bioauth:"
_SECRET_STORAGE_BACKEND = "local-file"

if os.name == "nt":
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
else:  # pragma: no cover - Windows-only structure
    DATA_BLOB = None  # type: ignore[assignment]


def get_secret_backend_name() -> str:
    """Return the active secret-storage backend name for diagnostics/tests."""

    return _SECRET_STORAGE_BACKEND


def _set_secret_backend_name(name: str) -> None:
    global _SECRET_STORAGE_BACKEND
    if name in {"keyring", "windows-dpapi", "local-file"}:
        _SECRET_STORAGE_BACKEND = name


def _normalize_secret(value: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _read_file_bytes(path: Path) -> bytes | None:
    try:
        if not path.exists():
            return None
        data = path.read_bytes()
        return data or None
    except OSError:
        LOGGER.warning("Failed reading local secret file %s", path.name, exc_info=True)
        return None


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
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


def _restrict_permissions(path: Path, callback: Optional[Callable[[str], None]]) -> None:
    try:
        if callback is not None:
            callback(str(path))
            return
    except Exception:
        LOGGER.warning("Provided secret permission callback failed for %s", path.name, exc_info=True)
    try:
        if os.name == "posix" and path.exists():
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        LOGGER.warning("Failed restricting local secret permissions for %s", path.name, exc_info=True)


def _save_local_secret(path: Path, secret: bytes, callback: Optional[Callable[[str], None]]) -> None:
    _atomic_write_bytes(path, secret)
    _restrict_permissions(path, callback)
    _set_secret_backend_name("local-file")


def _dpapi_protect(data: bytes) -> bytes | None:
    if os.name != "nt" or DATA_BLOB is None:
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        in_buffer = ctypes.create_string_buffer(data)
        in_blob = DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
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
    if os.name != "nt" or DATA_BLOB is None:
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        in_buffer = ctypes.create_string_buffer(blob)
        in_blob = DATA_BLOB(len(blob), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
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


def _load_windows_secret(protected_path: Path | None, plaintext_path: Path) -> bytes | None:
    if protected_path is not None:
        blob = _read_file_bytes(protected_path)
        if blob:
            secret = _dpapi_unprotect(blob)
            if secret:
                _set_secret_backend_name("windows-dpapi")
                return secret
    secret = _read_file_bytes(plaintext_path)
    if secret:
        _set_secret_backend_name("local-file")
        return secret
    return None


def _save_windows_secret(
    protected_path: Path | None,
    plaintext_path: Path,
    secret: bytes,
    restrict_permissions: Optional[Callable[[str], None]],
) -> None:
    if protected_path is not None:
        blob = _dpapi_protect(secret)
        if blob:
            _atomic_write_bytes(protected_path, blob)
            _restrict_permissions(protected_path, restrict_permissions)
            _set_secret_backend_name("windows-dpapi")
            return
    _save_local_secret(plaintext_path, secret, restrict_permissions)


def _keyring_account(secret_name: str) -> str:
    safe_name = str(secret_name or "master-key").strip() or "master-key"
    return f"{_KEYRING_ACCOUNT_PREFIX}{safe_name}"


def _load_keyring_secret(secret_name: str) -> bytes | None:
    if keyring is None:
        return None
    try:
        encoded = keyring.get_password(_KEYRING_SERVICE, _keyring_account(secret_name))
        if not encoded:
            return None
        secret = base64.urlsafe_b64decode(encoded.encode("ascii"))
        if secret:
            _set_secret_backend_name("keyring")
            return secret
    except Exception:
        LOGGER.debug("Keyring secret load is unavailable; falling back to local file.", exc_info=True)
    return None


def _save_keyring_secret(secret_name: str, secret: bytes) -> bool:
    if keyring is None:
        return False
    try:
        encoded = base64.urlsafe_b64encode(secret).decode("ascii")
        keyring.set_password(_KEYRING_SERVICE, _keyring_account(secret_name), encoded)
        _set_secret_backend_name("keyring")
        return True
    except Exception:
        LOGGER.debug("Keyring secret save is unavailable; falling back to local file.", exc_info=True)
        return False


def load_or_create_secret(
    *,
    secret_name: str,
    plaintext_path: str | os.PathLike[str],
    protected_path: str | os.PathLike[str] | None = None,
    generate_secret: Callable[[], bytes | bytearray | memoryview | str],
    restrict_permissions: Optional[Callable[[str], None]] = None,
) -> bytes:
    """Load an existing secret or create it in the strongest available backend.

    The function fails closed only when no configured backend can read or write the
    secret.  It does not log secret material and it does not import ``security`` to
    avoid startup circular imports.
    """

    plaintext = Path(plaintext_path)
    protected = Path(protected_path) if protected_path is not None else None

    if os.name == "nt":
        existing = _load_windows_secret(protected, plaintext)
        if existing:
            return existing
        secret = _normalize_secret(generate_secret())
        _save_windows_secret(protected, plaintext, secret, restrict_permissions)
        return secret

    existing = _load_keyring_secret(secret_name)
    if existing:
        return existing

    local = _read_file_bytes(plaintext)
    if local:
        _set_secret_backend_name("local-file")
        return local

    secret = _normalize_secret(generate_secret())
    if _save_keyring_secret(secret_name, secret):
        return secret
    _save_local_secret(plaintext, secret, restrict_permissions)
    return secret
