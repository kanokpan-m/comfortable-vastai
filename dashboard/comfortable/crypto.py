"""Optional encryption of API keys in the shared database.

Keys are stored unencrypted on purpose: you can read them in MongoDB if you need
to, and reaching the database already takes its password. To encrypt them, set
COMFORTABLE_SECRET_KEY to the same passphrase on every instance (in the template).
The passphrase never goes into the database, so an instance without it can't
read encrypted keys; it shows them as missing instead.
"""
import base64
import hashlib

from . import config

PREFIX = "enc:v1:"
_fernet = None


def enabled():
    return bool(config.SECRET_KEY)


def _cipher():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet  # installed by lib/setup.sh
        key = hashlib.scrypt(config.SECRET_KEY.encode(), salt=b"comfortable-keys", n=2 ** 14, r=8, p=1, dklen=32)
        _fernet = Fernet(base64.urlsafe_b64encode(key))
    return _fernet


def is_encrypted(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value):
    """Encrypt when a passphrase is set; otherwise store the key as it is."""
    if not value or not enabled() or is_encrypted(value):
        return value
    return PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt(value):
    """The plain key, or None when it is encrypted and this instance can't read it."""
    if not is_encrypted(value):
        return value
    if not enabled():
        return None
    try:
        return _cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except Exception:  # wrong passphrase, or cryptography missing
        return None


def status(unreadable):
    if unreadable:
        why = "set" if not enabled() else "the same as on the instance that saved them"
        return {"encrypted": True, "unreadable": unreadable,
                "message": f"Some keys are encrypted and can't be read here: COMFORTABLE_SECRET_KEY must be {why}."}
    if enabled():
        return {"encrypted": True, "unreadable": [], "message": "Keys are encrypted in the shared database (COMFORTABLE_SECRET_KEY)."}
    return {"encrypted": False, "unreadable": [],
            "message": "Keys are stored unencrypted in the shared database on purpose, so you can read them there. "
                       "To encrypt them, set COMFORTABLE_SECRET_KEY in the template (the same value on every instance)."}
