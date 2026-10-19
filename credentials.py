"""Encryption at rest for the Calendis password the bot needs when it fires.

The key is derived from SECRET_KEY (already required), so there is no extra
setting to manage. Changing SECRET_KEY makes stored passwords unreadable; the
affected bookings then fail with a clear message instead of logging in wrong.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def cipher_from_secret(secret_key: str) -> Fernet:
    digest = hashlib.sha256(b"padel-sniper/credentials\0" + secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(cipher: Fernet, password: str) -> str:
    return cipher.encrypt(password.encode()).decode()


def decrypt(cipher: Fernet, token: str) -> str:
    try:
        return cipher.decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("stored password can't be decrypted (was SECRET_KEY changed?)") from e
