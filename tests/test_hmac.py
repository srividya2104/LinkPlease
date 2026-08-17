import base64
import hashlib
import hmac
import pytest
from app.crypto import derive_hmac_secret, verify_signature

TEST_KEY = "c3JpdmFsbGkudGVzdEBleGFtcGxlLmNvbQ.f6f5e6ef44eb17184a65"


def test_derive_hmac_secret():
    secret = derive_hmac_secret(TEST_KEY)
    assert secret == b"srivalli.test@example.com"


def test_verify_signature_valid():
    body = b'{"event_id": "evt_123", "text": "hello"}'
    secret = derive_hmac_secret(TEST_KEY)
    sig_hex = hmac.new(secret, body, hashlib.sha256).hexdigest()

    # Test with and without sha256= prefix
    assert verify_signature(body, f"sha256={sig_hex}", TEST_KEY) is True
    assert verify_signature(body, sig_hex, TEST_KEY) is True


def test_verify_signature_invalid():
    body = b'{"event_id": "evt_123"}'
    assert (
        verify_signature(
            body,
            "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            TEST_KEY,
        )
        is False
    )


def test_verify_signature_modified_body():
    body = b'{"event_id": "evt_123"}'
    secret = derive_hmac_secret(TEST_KEY)
    sig_hex = hmac.new(secret, body, hashlib.sha256).hexdigest()

    modified_body = b'{"event_id": "evt_123_tampered"}'
    assert (
        verify_signature(modified_body, f"sha256={sig_hex}", TEST_KEY) is False
    )


def test_verify_signature_missing_and_malformed():
    body = b'{"event_id": "evt_123"}'
    assert verify_signature(body, None, TEST_KEY) is False
    assert verify_signature(body, "", TEST_KEY) is False
    assert verify_signature(body, "sha256=", TEST_KEY) is False
