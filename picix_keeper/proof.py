"""ECDSA P-256 request proofs matching picix.us PICIX-PROOF-V1."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
from typing import Literal
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ProofKind = Literal["session", "login"]

_API_PREFIX = re.compile(r"^/api(?:/|$)")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def save_private_key(path, key: ec.EllipticCurvePrivateKey) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def load_private_key(path) -> ec.EllipticCurvePrivateKey | None:
    if not path.exists():
        return None
    loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(loaded, ec.EllipticCurvePrivateKey):
        raise TypeError(f"proof key at {path} is not an EC private key")
    return loaded


def public_key_spki_b64url(key: ec.EllipticCurvePrivateKey) -> str:
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return b64url(spki)


def request_target(url: str) -> str:
    parsed = urlparse(url)
    path = _API_PREFIX.sub("/", parsed.path)
    if not path.startswith("/"):
        path = "/" + path
    return path + (f"?{parsed.query}" if parsed.query else "")


def _raw_p256_signature(key: ec.EllipticCurvePrivateKey, message: bytes) -> bytes:
    der = key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def build_proof_headers(
    *,
    kind: ProofKind,
    credential: str,
    method: str,
    request_target_path: str,
    body: str = "",
    private_key: ec.EllipticCurvePrivateKey,
    now: int | None = None,
) -> dict[str, str]:
    """Return X-Picix-Proof-* headers for one request."""

    prefix = "PICIX-PROOF-V1" if kind == "session" else "PICIX-LOGIN-V1"
    unix_time = int(time.time() if now is None else now)
    nonce = b64url(os.urandom(16))
    message = "\n".join(
        [
            prefix,
            sha256_hex(credential),
            method.upper(),
            request_target_path,
            sha256_hex(body),
            str(unix_time),
            nonce,
        ]
    )
    signature = b64url(_raw_p256_signature(private_key, message.encode("utf-8")))
    return {
        "X-Picix-Proof-Time": str(unix_time),
        "X-Picix-Proof-Nonce": nonce,
        "X-Picix-Proof-Signature": signature,
    }
