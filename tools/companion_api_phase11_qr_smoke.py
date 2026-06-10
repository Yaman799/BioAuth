from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from companion.device_registry import CompanionDeviceRegistry
from companion.pairing import PairingManager
from companion.qr import build_qr_png_data_uri


_state = {}


def load_settings():
    return dict(_state)


def save_settings(changes):
    _state.update(dict(changes or {}))
    return dict(_state)


def main() -> int:
    registry = CompanionDeviceRegistry(load_settings, save_settings)
    pairing = PairingManager(registry)
    payload = pairing.create_pairing_payload(host="192.168.1.25", port=39081, desktop_name="BioAuth Desktop", ttl_sec=300)
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    qr = build_qr_png_data_uri(compact)
    assert qr.get("ok") is True, qr
    assert str(qr.get("dataUri") or "").startswith("data:image/png;base64,")
    assert len(str(qr.get("dataUri") or "")) > 100
    assert "deviceToken" not in compact
    assert "tokenHash" not in compact
    print("BioAuth Companion API Phase 11 QR smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
