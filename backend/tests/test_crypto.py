import pytest
from cryptography.fernet import Fernet

from app.core.crypto import TokenCipher


def _key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = TokenCipher(_key())
    plaintext = "refresh_token_value_xyz"

    encrypted = cipher.encrypt(plaintext)
    assert encrypted != plaintext
    assert cipher.decrypt(encrypted) == plaintext


def test_decrypt_with_wrong_key_fails() -> None:
    a = TokenCipher(_key())
    b = TokenCipher(_key())

    encrypted = a.encrypt("secret")
    with pytest.raises(ValueError):
        b.decrypt(encrypted)


def test_empty_key_rejected() -> None:
    with pytest.raises(ValueError):
        TokenCipher("")
