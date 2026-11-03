"""RSA-OAEP keys and the values the remote auth gateway (v2) expects."""

import base64
import hashlib
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

OAEP_SHA256 = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
)

_USER_PAYLOAD = re.compile(r"^(\d+):(\d{1,4}):([a-zA-Z0-9_]+):(.*)$", re.DOTALL)


def b64url(data: bytes) -> str:
    """URL-safe base64 without '=' padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def qr_url(fingerprint: str) -> str:
    return f"https://discord.com/ra/{fingerprint}"


class RemoteAuthKeys:
    """A fresh RSA-2048 key pair; the gateway gets a new one for every connection."""

    def __init__(self, private_key: rsa.RSAPrivateKey | None = None) -> None:
        self._private = private_key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self._private.public_key()
        self._spki = self.public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    @property
    def public_key_b64(self) -> str:
        """SPKI DER in standard base64 (the `init` message)."""
        return base64.b64encode(self._spki).decode("ascii")

    @property
    def fingerprint(self) -> str:
        """base64url(SHA-256(SPKI)), the last part of the QR URL."""
        return b64url(hashlib.sha256(self._spki).digest())

    def decrypt(self, data_b64: str) -> bytes:
        return self._private.decrypt(base64.b64decode(data_b64), OAEP_SHA256)

    def nonce_proof(self, encrypted_nonce: str) -> str:
        """Protocol v2 proof: the decrypted nonce itself, base64url without padding."""
        return b64url(self.decrypt(encrypted_nonce))


@dataclass(frozen=True)
class UserPayload:
    id: str
    discriminator: str
    avatar: str | None
    username: str


def parse_user_payload(text: str) -> UserPayload:
    """`id:discriminator:avatar:username` from `pending_ticket` (avatar "0" means none)."""
    match = _USER_PAYLOAD.match(text)
    if not match:
        raise ValueError("unexpected user payload format")
    user_id, discriminator, avatar, username = match.groups()
    return UserPayload(user_id, discriminator, None if avatar == "0" else avatar, username)
