from __future__ import annotations

from companion.api import CompanionApiServer
from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.snapshots import build_status_snapshot


class MemorySettings:
    def __init__(self) -> None:
        self.payload = {}

    def load(self):
        return dict(self.payload)

    def save(self, value):
        self.payload = dict(value or {})
        return dict(self.payload)


def test_phase12_server_state_is_release_candidate_and_read_only():
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    server = CompanionApiServer(host="127.0.0.1", port=0, registry=registry, pairing=pairing, snapshot_provider=lambda: build_status_snapshot(None, registry=registry))
    try:
        state = server.start()
        assert state["phase"] == "phase12-release-candidate"
        assert state["readOnly"] is True
        assert state["controlActionsAllowed"] is False
    finally:
        server.stop()


def test_phase12_status_snapshot_does_not_include_control_or_raw_biometrics():
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    snapshot = build_status_snapshot(None, registry=registry)
    assert snapshot["readOnly"] is True
    assert snapshot["mobileSafe"] is True
    assert snapshot["transport"]["controlActionsAllowed"] is False
    assert snapshot["transport"]["rawBiometricDataIncluded"] is False
