"""Strict validation for model output."""


class InvalidAnswer(ValueError):
    pass


def validate(value, refs):
    if not isinstance(value, dict):
        raise InvalidAnswer("answer is not an object")
    required = {"summary", "causes", "checks", "cannot_tell", "confidence"}
    if not required.issubset(value):
        raise InvalidAnswer("answer is missing required fields")
    if not isinstance(value["summary"], str) or len(
            [part for part in value["summary"].split(".") if part.strip()]) > 2:
        raise InvalidAnswer("summary must contain at most two sentences")
    causes = []
    for cause in value["causes"][:3]:
        evidence = [ref for ref in cause.get("evidence", ()) if ref in refs]
        if evidence and cause.get("likelihood") in ("high", "medium", "low"):
            causes.append({"cause": str(cause.get("cause", "")),
                           "likelihood": cause["likelihood"],
                           "evidence": evidence})
    checks = []
    for check in value["checks"]:
        reference = check.get("runbook_ref")
        if reference is not None and reference not in refs:
            continue
        kind = check.get("kind")
        if kind not in ("look", "read_only_test", "write_action"):
            continue
        output = {"step": str(check.get("step", "")), "kind": kind}
        if reference is not None:
            output["runbook_ref"] = reference
        if kind == "write_action":
            output["kind"] = "proposal"
            output["needs_approval"] = True
        checks.append(output)
    return {"summary": value["summary"], "causes": causes, "checks": checks,
            "cannot_tell": bool(value["cannot_tell"]),
            "confidence": value["confidence"]}
