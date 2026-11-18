# DeepSignal roles and access policy

This engine provides one rulebook for pages and APIs. It has no login code and
depends on no other DeepSignal module.

## Role ladder

Roles are ordered `public < science < tech < admin`. A higher role receives all
permissions granted to every lower role. The example policy is
`contrib/deepsignal/configs/roles_example.yaml`.

```python
from contrib.deepsignal.roles.policy import Policy

policy = Policy.load("contrib/deepsignal/configs/roles_example.yaml")
role = policy.role_for(authenticated_identity)
if not policy.can(role, "download.raw"):
    deny_request()
```

Unknown actions and runtime roles are denied. `Policy.load()` rejects unknown
roles in the policy. Run `policy.check()` after loading to log dangerous but
valid choices, such as exposing an admin action to the public. `explain(policy)`
prints the effective action-by-role table for an operator to review.

**The identity passed to `role_for()` must come from the trusted login layer,
never from a request parameter.** The optional `users` mapping is only a local
identity-to-role mapping; it contains no credentials.

## Open login decision

Authentication is deliberately out of scope. Eugene still needs to choose one
of three login layers: existing OpenRVDAS Django accounts, the FastAPI JWT
backend, or a reverse proxy such as nginx basic authentication or SSO. Any of
these may supply the trusted identity used above. This module stores no
passwords, tokens, sessions, or cryptographic material.
