"""Role-based access policy for DeepSignal pages and APIs."""

import logging
from collections.abc import Mapping
from pathlib import Path

import yaml


LOG = logging.getLogger(__name__)
ROLES = ("public", "science", "tech", "admin")
ADMIN_ACTIONS = frozenset(("config.deploy",))


class PolicyError(ValueError):
    """A plain-English policy configuration error."""


class Policy:
    """An immutable-in-practice mapping from actions and identities to roles."""

    def __init__(self, actions, users, default_role):
        self.actions = dict(actions)
        self.users = dict(users)
        self.default_role = default_role
        self._unknown_actions_logged = set()
        self._unknown_roles_logged = set()

    @classmethod
    def load(cls, path):
        """Load and validate a YAML policy at *path*."""
        policy_path = Path(path)
        try:
            with policy_path.open(encoding="utf-8") as stream:
                document = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as error:
            raise PolicyError(
                f"policy file saw {error}; expected readable YAML; example: "
                "actions: {view.live: public}") from error

        if not isinstance(document, Mapping):
            raise PolicyError(
                f"policy saw {document!r}; expected a YAML mapping; example: "
                "actions: {view.live: public}")
        actions = cls._mapping(document.get("actions"), "actions", required=True)
        users = cls._mapping(document.get("users", {}), "users")
        default_role = document.get("default_role", "public")
        cls._validate_role("default_role", default_role)

        for action, role in actions.items():
            if not isinstance(action, str) or not action:
                raise PolicyError(
                    f"actions key saw {action!r}; expected a non-empty action name; "
                    "example: view.live")
            cls._validate_role(f"actions.{action}", role)
        for identity, role in users.items():
            if not isinstance(identity, str) or not identity:
                raise PolicyError(
                    f"users key saw {identity!r}; expected a non-empty identity; example: alice")
            cls._validate_role(f"users.{identity}", role)
        return cls(actions, users, default_role)

    @staticmethod
    def _mapping(value, setting, required=False):
        if not isinstance(value, Mapping):
            example = "actions: {view.live: public}" if required else "users: {alice: tech}"
            raise PolicyError(
                f"{setting} saw {value!r}; expected a YAML mapping; example: {example}")
        return value

    @staticmethod
    def _validate_role(setting, role):
        if role not in ROLES:
            raise PolicyError(
                f"{setting} saw {role!r}; expected one of {', '.join(ROLES)}; example: public")

    def can(self, role, action):
        """Return whether *role* may perform *action*, failing closed."""
        minimum = self.actions.get(action)
        if minimum is None:
            if action not in self._unknown_actions_logged:
                LOG.warning("unknown action %r denied", action)
                self._unknown_actions_logged.add(action)
            return False
        if role not in ROLES:
            if role not in self._unknown_roles_logged:
                LOG.warning("unknown role %r denied", role)
                self._unknown_roles_logged.add(role)
            return False
        return ROLES.index(role) >= ROLES.index(minimum)

    def role_for(self, identity):
        """Return the configured role for trusted login-layer *identity*."""
        return self.users.get(identity, self.default_role)

    def check(self):
        """Warn about dangerous, valid policy choices."""
        for action in sorted(ADMIN_ACTIONS & self.actions.keys()):
            if self.actions[action] == "public":
                LOG.warning("admin action open to public: %s", action)


def explain(policy):
    """Print a plain action-by-role permission table."""
    print("action               public science tech admin")
    for action in sorted(policy.actions):
        cells = ["yes" if policy.can(role, action) else "-" for role in ROLES]
        print(f"{action:<20} {cells[0]:<6} {cells[1]:<7} {cells[2]:<4} {cells[3]}")
