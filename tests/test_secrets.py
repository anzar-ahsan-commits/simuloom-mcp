import sqlite3
from pathlib import Path

import pytest

from simuloom.core.platform_store import PlatformStore
from simuloom.core.secrets import SecretVault


def test_vault_encrypts_and_decrypts_without_plaintext_storage(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    workspace = store.create_workspace("Secrets", "owner")
    vault = SecretVault("a-very-long-master-key-that-is-not-real")

    metadata = store.put_secret(workspace["id"], "WEBHOOK_TOKEN", vault.encrypt("sensitive-value"))
    ciphertext = store.secret_ciphertext(workspace["id"], "WEBHOOK_TOKEN")

    assert metadata["name"] == "WEBHOOK_TOKEN"
    assert b"sensitive-value" not in ciphertext
    assert vault.decrypt(ciphertext) == "sensitive-value"
    with sqlite3.connect(store.path) as connection:
        stored = connection.execute("SELECT ciphertext FROM platform_secrets").fetchone()[0]
    assert b"sensitive-value" not in stored


def test_vault_requires_strong_key_and_configuration() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        SecretVault("short")

    unavailable = SecretVault(None)
    assert unavailable.available is False
    with pytest.raises(RuntimeError, match="required"):
        unavailable.encrypt("value")


def test_secret_metadata_never_contains_ciphertext(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    workspace = store.create_workspace("Secrets", "owner")
    store.put_secret(workspace["id"], "API_TOKEN", b"encrypted")

    listed = store.list_secrets(workspace["id"])

    assert set(listed[0]) == {"name", "created_at", "updated_at"}
