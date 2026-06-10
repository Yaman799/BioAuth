"""BioAuth Companion API foundation.

This package is intentionally read-only for Phase 6.  It exposes mobile-safe
status snapshots, short-lived pairing challenges, and token validation helpers
without moving raw behavioral logs, model artifacts, passcodes, private keys, or
biometric templates into the companion transport.
"""

from .api import CompanionApiServer
from .device_registry import CompanionDeviceRegistry
from .pairing import PairingManager
from .snapshots import build_status_snapshot

__all__ = [
    "CompanionApiServer",
    "CompanionDeviceRegistry",
    "PairingManager",
    "build_status_snapshot",
]
