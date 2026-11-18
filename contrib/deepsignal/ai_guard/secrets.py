"""One-way bearer-token helpers.

Provider keys belong to the #192 key vault and are deliberately not handled by
this shared module.
"""
import base64
import hashlib
import hmac
import os


ITERATIONS = 200000


def hash_token(token):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        ITERATIONS, base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode())


def check_token(token, stored):
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", token.encode(),
                                     base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False
