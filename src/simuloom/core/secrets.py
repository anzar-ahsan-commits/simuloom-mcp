from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretVault:
    def __init__(self, master_key: str | None) -> None:
        if master_key is not None and len(master_key) < 32:
            raise ValueError("SIMULOOM_SECRETS_MASTER_KEY must contain at least 32 characters")
        self.available = master_key is not None
        self._fernet = (
            Fernet(base64.urlsafe_b64encode(hashlib.sha256(master_key.encode()).digest()))
            if master_key
            else None
        )

    def encrypt(self, value: str) -> bytes:
        if self._fernet is None:
            raise RuntimeError("SIMULOOM_SECRETS_MASTER_KEY is required")
        return self._fernet.encrypt(value.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        if self._fernet is None:
            raise RuntimeError("SIMULOOM_SECRETS_MASTER_KEY is required")
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except (InvalidToken, UnicodeError) as exc:
            raise RuntimeError("Stored secret cannot be decrypted with the configured key") from exc
