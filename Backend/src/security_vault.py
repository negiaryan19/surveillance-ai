"""Fernet encryption for exported reports.

The key is created once with ``O_CREAT|O_EXCL`` and mode 0600 so two
concurrent first requests cannot each mint a key (which would leave one
report undecryptable) and there is no window where the file is
world-readable. Encryption never happens in place: v1 encrypted the PDF on
disk and then served that file as ``.pdf``, so the download could not open.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("chanakya.security_vault")


def _fernet(key: bytes):
    from cryptography.fernet import Fernet

    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "report encryption key is invalid; restore it from backup or delete it to start over"
        ) from exc


def load_key(key_file=None) -> bytes:
    if key_file is None:
        from config import settings

        key_file = settings.KEY_FILE
    path = Path(key_file)
    if path.is_file():
        key = path.read_bytes().strip()
        _fernet(key)  # validate early so a truncated key fails loudly, once
        return key
    from cryptography.fernet import Fernet

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = path.read_bytes().strip()
        _fernet(key)
        return key
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    log.warning("created %s - back it up: encrypted reports cannot be recovered without it", path)
    return key


def encrypt_bytes(data: bytes, key_file=None) -> bytes:
    return _fernet(load_key(key_file)).encrypt(data)


def decrypt_bytes(data: bytes, key_file=None) -> bytes:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(load_key(key_file)).decrypt(data)
    except InvalidToken as exc:
        raise RuntimeError("cannot decrypt: wrong key or corrupted file") from exc


def encrypt_file(path, out_path=None, key_file=None) -> Path:
    src = Path(path)
    dst = Path(out_path) if out_path else src.with_name(src.name + ".enc")
    dst.write_bytes(encrypt_bytes(src.read_bytes(), key_file))
    return dst


def decrypt_file(path, out_path=None, key_file=None) -> Path:
    src = Path(path)
    if out_path:
        dst = Path(out_path)
    elif src.suffix == ".enc":
        dst = src.with_suffix("")
    else:
        dst = src.with_name(src.name + ".decrypted")
    dst.write_bytes(decrypt_bytes(src.read_bytes(), key_file))
    return dst
