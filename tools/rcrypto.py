"""Encryption helpers for the Rabita lessons site.

Two layers:
1. Sources in the repo (sources/<date>/*.bin) are sealed with the repo's PUBLIC key
   (RSA-OAEP + AES-256-GCM). Anyone can add a lesson; only the GitHub job, which holds
   the private key (itself locked with the teacher password), can open them.
2. Pages on the site are locked with a key derived from the teacher password
   (PBKDF2-SHA256, site-wide salt) using AES-256-GCM, opened in the browser with WebCrypto.
"""
import gzip, os, struct
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000
MAGIC = b"RBT1"


def derive(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


# ---------- layer 1: sealing sources with the public key ----------
def _oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def seal(data: bytes, public_pem: bytes) -> bytes:
    pub = serialization.load_pem_public_key(public_pem)
    k = AESGCM.generate_key(256)
    nonce = os.urandom(12)
    wrapped = pub.encrypt(k, _oaep())
    ct = AESGCM(k).encrypt(nonce, gzip.compress(data, 9, mtime=0), MAGIC)
    return MAGIC + struct.pack(">H", len(wrapped)) + wrapped + nonce + ct


def unseal(blob: bytes, private_key) -> bytes:
    assert blob[:4] == MAGIC, "not a sealed file"
    n = struct.unpack(">H", blob[4:6])[0]
    wrapped = blob[6:6 + n]
    nonce = blob[6 + n:18 + n]
    k = private_key.decrypt(wrapped, _oaep())
    return gzip.decompress(AESGCM(k).decrypt(nonce, blob[18 + n:], MAGIC))


def new_keypair(password: str):
    """Returns (public_pem, locked_private) — private key locked with the password."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    salt, nonce = os.urandom(16), os.urandom(12)
    locked = salt + nonce + AESGCM(derive(password, salt)).encrypt(nonce, pem, b"rabita-private-key")
    pub = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    return pub, locked


def open_private(locked: bytes, password: str):
    salt, nonce, ct = locked[:16], locked[16:28], locked[28:]
    pem = AESGCM(derive(password, salt)).decrypt(nonce, ct, b"rabita-private-key")
    return serialization.load_pem_private_key(pem, password=None)


# ---------- layer 2: locking pages for the browser ----------
def lock_page(html: bytes, page_key: bytes) -> bytes:
    """nonce(12) | AES-GCM(gzip(html)). The browser derives page_key from the password."""
    nonce = os.urandom(12)
    return nonce + AESGCM(page_key).encrypt(nonce, gzip.compress(html, 6, mtime=0), None)
