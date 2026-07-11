#!/usr/bin/env python3
"""Read one value out of a dev-workflow.yml by dotted path — for shell callers.

    python3 dev-workflow/dw-config.py <yml> <dotted.path> [default]

Prints a scalar on one line; prints a list one item per line; exits 1 if the
path is missing and no default was given (prints the default instead when it
is). Example:

    python3 dev-workflow/dw-config.py dev-workflow.yml tracker.team
    python3 dev-workflow/dw-config.py dev-workflow.yml build.model sonnet
"""
import sys

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "ERROR: PyYAML is required. Install it with "
        "`pip install pyyaml` (or `apt install python3-yaml`).\n"
    )
    sys.exit(1)

_MISSING = object()


def get(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("usage: dw-config.py <yml> <dotted.path> [default]\n")
        return 2
    path, dotted = argv[1], argv[2]
    default = argv[3] if len(argv) > 3 else _MISSING
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    value = get(data, dotted)
    if value is _MISSING:
        if default is _MISSING:
            sys.stderr.write("ERROR: %s not set in %s\n" % (dotted, path))
            return 1
        print(default)
        return 0
    if isinstance(value, list):
        for item in value:
            print(item)
    elif isinstance(value, dict):
        sys.stderr.write("ERROR: %s is a mapping, not a scalar\n" % dotted)
        return 1
    else:
        print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
