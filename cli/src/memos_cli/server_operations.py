"""Shared parser and remote forwarding contract; embedded in the SSH worker."""

OPERATIONS = {
    "doctor": {
        "command": ["doctor", "--json"],
        "options": {"load_model": {"action": "store_true"}},
    },
    "reindex": {"command": ["reindex"], "options": {}},
    "bench": {"command": ["bench"], "options": {}},
    "drain-index": {
        "command": ["drain-index"],
        "options": {
            "limit": {"type": "int", "default": 100},
            "retry_now": {"action": "store_true"},
        },
    },
    "consolidate": {
        "command": ["consolidate"],
        "options": {"apply": {"action": "store_true"}, "merge": {"action": "store_true"}},
    },
    "reextract-report": {"command": ["reextract-report"], "options": {"user": {}}},
    "eval": {
        "command": ["eval"],
        "options": {
            "target": {"choices": ["raw", "memories"], "default": "memories"},
            "limit": {"type": "int", "default": 100},
            "compare": {"action": "store_true"},
        },
    },
    "import-claude-code": {
        "command": ["import-claude-code"],
        "options": {"user": {}, "limit": {"type": "int", "default": 100}},
    },
    "import-sqlite": {
        "command": ["import-sqlite"],
        "options": {"user": {}, "pending": {"action": "store_true"}},
    },
    "backup-create": {
        "command": ["create"],
        "options": {"kind": {"default": "manual"}, "protected": {"action": "store_true"}},
    },
}


def forwarded_args(payload):
    specification = OPERATIONS[payload["action"]]
    arguments = list(specification["command"])
    for name, option in specification["options"].items():
        value = payload.get(name, option.get("default"))
        if value is None:
            continue
        if name == "limit" and (type(value) is not int or value < 1):
            raise ValueError("--limit must be a positive integer")
        flag = "--" + name.replace("_", "-")
        if option.get("action") == "store_true":
            if value:
                arguments.append(flag)
        else:
            arguments.extend([flag, str(value)])
    return arguments
