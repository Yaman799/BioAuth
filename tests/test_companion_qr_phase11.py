import json

from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.qr import build_qr_png_data_uri


class MemorySettings:
    def __init__(self):
        self.data = {}

    def load(self):
        return dict(self.data)

    def save(self, changes):
        self.data.update(dict(changes or {}))
        return dict(self.data)


def test_phase11_qr_data_uri_is_png_and_does_not_expose_token():
    memory = MemorySettings()
    registry = CompanionDeviceRegistry(memory.load, memory.save)
    pairing = PairingManager(registry)
    payload = pairing.create_pairing_payload(
        host="192.168.1.25",
        port=39081,
        desktop_name="BioAuth Desktop",
        ttl_sec=300,
    )
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    result = build_qr_png_data_uri(compact)

    assert result["ok"] is True
    assert result["dataUri"].startswith("data:image/png;base64,")
    assert result["byteLength"] > 100
    assert "deviceToken" not in compact
    assert "tokenHash" not in compact
    assert payload["type"] == "bioauth_companion_pairing"
    assert payload["host"] == "192.168.1.25"


def test_phase11_qr_empty_payload_is_rejected():
    result = build_qr_png_data_uri("")
    assert result["ok"] is False
    assert result["error"] == "empty_qr_payload"
