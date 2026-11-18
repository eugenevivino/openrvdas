"""Lazy bridge to the #192 key vault."""
import importlib


VAULT_REQUIRED = "AI assist needs the key vault (#192), not installed yet."
VAULT_MODULE = "contrib.deepsignal.key_vault"


class VaultUnavailable(RuntimeError):
    pass


def installed_vault(module_path=VAULT_MODULE):
    """Return #192's vault interface without making it an import dependency."""
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return None
    return getattr(module, "vault", module)


def require(vault=None, loader=installed_vault):
    result = vault if vault is not None else loader()
    if result is None:
        raise VaultUnavailable(VAULT_REQUIRED)
    return result


def put(provider, value, vault=None, loader=installed_vault):
    target = require(vault, loader)
    target.put("ai-triage", provider, value)
    return target.protector()


def get(provider, vault=None, loader=installed_vault):
    return require(vault, loader).get("ai-triage", provider)
