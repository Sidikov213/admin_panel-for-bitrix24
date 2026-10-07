import hashlib
import secrets
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph: Final[PasswordHasher] = PasswordHasher()


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, plain)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(24)
