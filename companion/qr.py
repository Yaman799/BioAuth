from __future__ import annotations

import base64
import io
from typing import Any, Dict


def build_qr_png_data_uri(text: str) -> Dict[str, Any]:
    """Build a QR PNG data URI.

    Used by the Desktop Mobile Companion card. The QR should contain only the
    short-lived pairing JSON challenge; it must never contain a device token.
    """
    payload = str(text or "").strip()
    if not payload:
        return {"ok": False, "error": "empty_qr_payload", "dataUri": "", "byteLength": 0}
    try:
        import qrcode
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": "qrcode_dependency_missing", "detail": str(exc), "dataUri": ""}

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"ok": True, "mimeType": "image/png", "dataUri": "data:image/png;base64," + encoded, "byteLength": len(buffer.getvalue())}


def pairing_json_to_qr_data_url(pairing_json: str) -> Dict[str, Any]:
    result = build_qr_png_data_uri(pairing_json)
    return {
        "ok": bool(result.get("ok")),
        "mimeType": result.get("mimeType", "image/png"),
        "dataUrl": result.get("dataUri", ""),
        "error": result.get("error", ""),
    }
