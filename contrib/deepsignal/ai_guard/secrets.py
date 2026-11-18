"""Secret storage and one-way bearer-token helpers."""
import base64
import hashlib
import hmac
import os
import shutil
import subprocess
import tempfile


ITERATIONS = 200000


class SystemRunner:
    def has_systemd_creds(self):
        return shutil.which("systemd-creds") is not None

    def encrypt(self, source, target):
        subprocess.run(["systemd-creds", "encrypt", source, target],
                       check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL)


def store_key(name, value, directory="/etc/deepsignal/credentials", runner=None):
    runner = runner or SystemRunner()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, name + (".cred" if runner.has_systemd_creds()
                                           else ".key"))
    if runner.has_systemd_creds():
        handle, source = tempfile.mkstemp(dir=directory)
        try:
            os.write(handle, value.encode())
            os.close(handle)
            runner.encrypt(source, path)
        finally:
            if os.path.exists(source):
                os.unlink(source)
        os.chmod(path, 0o600)
        return {"path": path, "encrypted": True, "warning": None}
    with open(path, "w", encoding="utf-8") as target:
        target.write(value)
    os.chmod(path, 0o600)
    return {"path": path, "encrypted": False,
            "warning": "AI key stored without encryption on this host"}


def load_key(name, directory="/etc/deepsignal/credentials", runner=None):
    encrypted = os.path.join(directory, name + ".cred")
    plain = os.path.join(directory, name + ".key")
    if os.path.exists(encrypted):
        if runner is None:
            output = subprocess.check_output(["systemd-creds", "decrypt",
                                              encrypted, "-"])
        else:
            output = runner(encrypted)
        return output.decode().strip()
    with open(plain, encoding="utf-8") as source:
        return source.read()


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
