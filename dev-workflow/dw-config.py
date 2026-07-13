#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Read one value out of a dev-workflow.yml by dotted path — for shell callers.

    dw-config dev-workflow.yml <dotted.path> [default]                 # PATH shim (hardened install)
    uv run dev-workflow/dw-config.py <yml> <dotted.path> [default]     # framework checkout
    python3 dev-workflow/dw-config.py <yml> <dotted.path> [default]    # bare system python3

Batch mode — resolve many keys in one call (for a skill preamble):

    dw-config dev-workflow.yml --batch key[=default] [key[=default] ...]

prints one `key=value` line per key. The key keeps its dots on the left (it is a
label, not a shell variable); the value is shell-escaped so it is unambiguous. A
missing key with a default prints the (escaped) default; a missing key with no
default prints `key=` (empty value) and still exits 0. Single-key mode above is
unchanged.

PyYAML is used when importable (via `uv run` it comes from uv's cache — the PEP
723 header above; no venv, no project sync). When it is absent — e.g. the PATH
`dw-config` shim running under a bare system python3 — a stdlib-only parser
handles the small, flat dev-workflow.yml instead, so the helper never hard-fails
on a missing dependency.

Prints a scalar on one line; prints a list one item per line; exits 1 if the
path is missing and no default was given (prints the default instead when it
is). Example:

    dw-config dev-workflow.yml tracker.team
    dw-config dev-workflow.yml build.model sonnet
"""
import shlex
import sys

_MISSING = object()


def _scalar_str(v):
    """Render a scalar the way the batch line should carry it (bools lowercased
    to shell-friendly true/false; everything else via str)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _batch_value(value):
    """Shell-escape a resolved value for one batch `key=value` line. A list becomes
    space-separated, each item individually quoted."""
    if isinstance(value, list):
        return " ".join(shlex.quote(_scalar_str(v)) for v in value)
    return shlex.quote(_scalar_str(value))


def _strip_comment(line):
    """Drop a trailing YAML comment (`#` at line start or after whitespace),
    respecting single/double quotes so a `#` inside a value survives."""
    in_single = in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1] in " \t":
                return line[:idx]
    return line


def _split_flow(s):
    """Split a flow collection body on top-level commas, respecting nested
    `[]`/`{}` and quotes."""
    parts, depth, buf, in_s, in_d = [], 0, [], False, False
    for ch in s:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        if not in_s and not in_d:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    tail = "".join(buf)
    if tail.strip():
        parts.append(tail)
    return [p.strip() for p in parts]


def _scalar(s):
    """Coerce a YAML scalar token to a Python value (best-effort, stdlib only)."""
    if s == "":
        return None
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in _split_flow(inner)] if inner else []
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        result = {}
        for kv in _split_flow(inner):
            k, _sep, v = kv.partition(":")
            result[_scalar(k.strip())] = _scalar(v.strip())
        return result
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _minimal_yaml_load(text):
    """Indentation-based parser for the small, flat dev-workflow.yml — a stdlib
    fallback for when PyYAML is unavailable. Handles nested block mappings, block
    lists, scalars, and best-effort flow `[..]`/`{..}`. Not a general YAML parser;
    every value the skills read (tracker.team, build.model, quality.test, …) is a
    plain scalar or list, which this handles."""
    rows = []
    for raw in text.split("\n"):
        s = _strip_comment(raw)
        if not s.strip():
            continue
        indent = len(s) - len(s.lstrip(" "))
        rows.append((indent, s.strip()))
    if not rows:
        return {}
    value, _ = _parse_node(rows, 0, rows[0][0])
    return value


def _parse_node(rows, i, indent):
    if rows[i][1].startswith("- "):
        return _parse_seq(rows, i, indent)
    return _parse_map(rows, i, indent)


def _parse_map(rows, i, indent):
    result = {}
    n = len(rows)
    while i < n:
        cur, text = rows[i]
        if cur < indent:
            break
        if cur > indent:  # defensive; well-formed input won't hit this
            i += 1
            continue
        key, _sep, rest = text.partition(":")
        key = _scalar(key.strip())
        rest = rest.strip()
        i += 1
        if rest == "":
            # nested block: deeper mapping, or a list at same-or-deeper indent
            if i < n and (rows[i][0] > indent or (rows[i][0] == indent and rows[i][1].startswith("- "))):
                child, i = _parse_node(rows, i, rows[i][0])
                result[key] = child
            else:
                result[key] = None
        else:
            result[key] = _scalar(rest)
    return result, i


def _parse_seq(rows, i, indent):
    result = []
    n = len(rows)
    while i < n:
        cur, text = rows[i]
        if cur < indent or cur > indent or not text.startswith("- "):
            break
        result.append(_scalar(text[2:].strip()))
        i += 1
    return result, i


try:
    import yaml

    def _load(fh):
        return yaml.safe_load(fh) or {}
except ImportError:
    def _load(fh):
        return _minimal_yaml_load(fh.read()) or {}


def get(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(
            "usage: dw-config <yml> <dotted.path> [default]\n"
            "       dw-config <yml> --batch key[=default] [key[=default] ...]\n"
        )
        return 2

    # Batch mode: one shell-escaped `key=value` line per requested key.
    if argv[2] == "--batch":
        path = argv[1]
        with open(path) as fh:
            data = _load(fh)
        for spec in argv[3:]:
            key, sep, default = spec.partition("=")
            value = get(data, key)
            if value is _MISSING:
                if sep and default != "":
                    print("%s=%s" % (key, shlex.quote(default)))
                else:
                    print("%s=" % key)
            elif value is None:
                print("%s=" % key)
            else:
                print("%s=%s" % (key, _batch_value(value)))
        return 0

    path, dotted = argv[1], argv[2]
    default = argv[3] if len(argv) > 3 else _MISSING
    with open(path) as fh:
        data = _load(fh)
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
