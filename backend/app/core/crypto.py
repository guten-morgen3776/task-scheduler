from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class TokenCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("TOKEN_ENCRYPTION_KEY is empty")
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            raise ValueError("Failed to decrypt: invalid token or wrong key") from e


_cipher: TokenCipher | None = None


def get_cipher() -> TokenCipher:
    global _cipher
    if _cipher is None:
        _cipher = TokenCipher(get_settings().token_encryption_key)
    return _cipher


def reset_cipher_for_tests() -> None:
    global _cipher
    _cipher = None
