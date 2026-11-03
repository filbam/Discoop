import base64
import hashlib
import os

import pytest

from discoop.remote_auth.crypto import OAEP_SHA256, RemoteAuthKeys, b64url, parse_user_payload, qr_url


@pytest.fixture(scope="module")
def keys():
    return RemoteAuthKeys()


def test_public_key_is_standard_base64_spki(keys):
    spki = base64.b64decode(keys.public_key_b64, validate=True)
    assert len(spki) == 294  # RSA-2048 SubjectPublicKeyInfo, as seen in the browser traffic


def test_fingerprint_is_b64url_sha256_of_spki(keys):
    spki = base64.b64decode(keys.public_key_b64)
    assert keys.fingerprint == b64url(hashlib.sha256(spki).digest())
    assert len(keys.fingerprint) == 43
    assert qr_url(keys.fingerprint) == f"https://discord.com/ra/{keys.fingerprint}"


def test_nonce_proof_is_the_decrypted_nonce_without_padding(keys):
    nonce = os.urandom(190)  # the size Discord sent in both observed sessions
    encrypted = base64.b64encode(keys.public_key.encrypt(nonce, OAEP_SHA256)).decode()
    proof = keys.nonce_proof(encrypted)
    assert "=" not in proof
    assert base64.urlsafe_b64decode(proof + "=" * (-len(proof) % 4)) == nonce


def test_decrypt_token(keys):
    encrypted = base64.b64encode(keys.public_key.encrypt(b"token.value.123", OAEP_SHA256)).decode()
    assert keys.decrypt(encrypted) == b"token.value.123"


def test_user_payload():
    user = parse_user_payload("123456789:0:a1b2c3:some_user")
    assert (user.id, user.discriminator, user.avatar, user.username) == ("123456789", "0", "a1b2c3", "some_user")
    assert parse_user_payload("1:0:0:x").avatar is None
    with pytest.raises(ValueError):
        parse_user_payload("garbage")
