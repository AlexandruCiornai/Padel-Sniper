import pytest

from credentials import cipher_from_secret, decrypt, encrypt


def test_round_trip():
    cipher = cipher_from_secret("a" * 64)
    assert decrypt(cipher, encrypt(cipher, "parola-mea!")) == "parola-mea!"


def test_stored_value_does_not_contain_the_password():
    cipher = cipher_from_secret("a" * 64)
    assert "parola-mea" not in encrypt(cipher, "parola-mea")


def test_same_password_encrypts_differently_each_time():
    cipher = cipher_from_secret("a" * 64)
    assert encrypt(cipher, "x") != encrypt(cipher, "x")


def test_key_is_derived_deterministically_so_restarts_can_decrypt():
    token = encrypt(cipher_from_secret("same-secret"), "pw")
    assert decrypt(cipher_from_secret("same-secret"), token) == "pw"


def test_changed_secret_key_fails_clearly():
    token = encrypt(cipher_from_secret("old-secret"), "pw")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        decrypt(cipher_from_secret("new-secret"), token)


def test_cleared_or_legacy_plaintext_value_fails_clearly():
    with pytest.raises(ValueError):
        decrypt(cipher_from_secret("s"), "")
    with pytest.raises(ValueError):
        decrypt(cipher_from_secret("s"), "plaintext-password")
