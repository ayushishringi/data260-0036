"""Password hashing (PBKDF2-SHA256). Sessions were replaced by JWT in HW7 (see backend/jwt_auth.py)."""

import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    """Return "salt_hex$digest_hex" for a new random 16-byte salt."""

    salt = secrets.token_bytes(16)
    password_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${password_digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash in constant time; malformed hashes never match."""

    try:
        salt_hex, digest_hex = stored_hash.split("$", maxsplit=1)
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
        actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(actual_digest, expected_digest)
    except (ValueError, TypeError, AttributeError):
        return False
