from __future__ import annotations

from app_passcode import build_passcode_record, is_passcode_configured, validate_passcode_value, verify_passcode_record


def test_app_passcode_record_round_trip() -> None:
    ok, key = validate_passcode_value("1234")
    assert ok is True
    assert key == ""

    bad_ok, bad_key = validate_passcode_value("12ab")
    assert bad_ok is False
    assert bad_key == "app_passcode_digits_only"

    short_ok, short_key = validate_passcode_value("123")
    assert short_ok is False
    assert short_key == "app_passcode_length"

    record = build_passcode_record("1234")
    assert is_passcode_configured(record) is True
    assert verify_passcode_record(record, "1234") is True
    assert verify_passcode_record(record, "9999") is False
