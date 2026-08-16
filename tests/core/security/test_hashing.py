"""
Tests for `parika.core.security.hashing`.
"""

from __future__ import annotations

import pytest

from parika.core.security import (
    InvalidCredentialsError,
    constant_time_equals,
    hash_secret,
    verify_secret,
)


def test_hash_secret_produces_verifiable_hash() -> None:
    stored = hash_secret("my-secret-value")

    assert verify_secret("my-secret-value", stored) is True


def test_verify_secret_rejects_wrong_secret() -> None:
    stored = hash_secret("correct-secret")

    assert verify_secret("wrong-secret", stored) is False


def test_hash_secret_uses_random_salt_each_time() -> None:
    first = hash_secret("same-secret")
    second = hash_secret("same-secret")

    assert first != second
    assert verify_secret("same-secret", first) is True
    assert verify_secret("same-secret", second) is True


def test_verify_secret_raises_on_malformed_hash() -> None:
    with pytest.raises(InvalidCredentialsError):
        verify_secret("anything", "not-a-valid-hash")


def test_verify_secret_raises_on_unsupported_algorithm() -> None:
    stored = hash_secret("secret")
    algorithm, iterations, salt_hex, key_hex = stored.split("$")
    tampered = "$".join(("sha1", iterations, salt_hex, key_hex))

    with pytest.raises(InvalidCredentialsError):
        verify_secret("secret", tampered)


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc") is True
    assert constant_time_equals("abc", "abd") is False
