import base64
import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def derive_hmac_secret(api_key: str) -> bytes:
    """Derives HMAC secret from API key.

    If API key has format `<base64-component>.<hex-component>`, secret is the
    base64-decoded first component. If string is not in dot format or decoding
    fails, falls back to raw API key bytes.
    """
    if not api_key:
        return b""

    parts = api_key.split(".", 1)
    b64_part = parts[0]

    # Add missing base64 padding
    padded_b64 = b64_part + "=" * (-len(b64_part) % 4)
    try:
        secret = base64.b64decode(padded_b64)
        return secret
    except Exception as err:
        logger.warning(
            "Failed to base64-decode API key prefix, using raw key: %s", err
        )
        return api_key.encode("utf-8")


def verify_signature(
    raw_body: bytes, signature_header: str | None, api_key: str
) -> bool:
    """Verifies PseudoGram HMAC SHA-256 webhook signature in constant time."""
    if not signature_header:
        return False

    sig = signature_header.strip()
    if sig.startswith("sha256="):
        expected_hex = sig[7:]
    else:
        expected_hex = sig

    if not expected_hex:
        return False

    secret = derive_hmac_secret(api_key)
    if not secret:
        return False

    computed_hex = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()

    return hmac.compare_digest(computed_hex.lower(), expected_hex.lower())
