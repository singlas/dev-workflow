#!/usr/bin/env python3
"""Parse one `claude -p --output-format json` pass: extract the human summary,
append a usage record, and report whether the pass hit the session limit.

Called by cron-run.sh AFTER the pass exits. Stdlib only — runs under any python3.

The pass's stdout is a single JSON result object on success; on a session-limit
hit or hard failure it may be non-JSON (a bare message on stdout or stderr, any
exit code). So detection reads the RAW stdout+stderr, never the parsed `.result`
(the limit notice and the harness guillotine line are harness-level, not part of
the model result). A missing usage field never fails the pass — the CLI
documents `json` mode but not its schema.

Usage:
  usage-parse.py --stdout OUT --stderr ERR --tenant NAME --rc N \
      --result-out RESULTFILE --usage-out usage.jsonl [--now ISO8601]

Writes:
  RESULTFILE   the human summary (`.result`, else raw stdout) for the cron log
  usage.jsonl  one appended record:
    {ts, tenant, input_tokens, output_tokens, cache_read, cache_creation,
     num_turns, duration_ms, total_cost_usd, rc, limit, reset}
Prints ONE tab-separated control line for the shell:
  limit=<0|1>\treset=<str>\tparsed=<0|1>
"""

import argparse
import datetime
import json
import re
import sys

# Broadened, case-insensitive — the exact phrase "hit your session limit" is NOT
# in the 2.1.210 binary; "session limit" and "limit resets" ARE. Match any of the
# real wordings rather than one brittle literal.
LIMIT_RE = re.compile(
    r"(?i)("
    r"hit your (?:usage|session) limit"
    r"|(?:session|usage|rate) limit(?:\s+(?:reached|exceeded))?"
    r"|limit(?:\s+will)?\s+reset"
    r"|limit resets"
    r")"
)
# Pull a human-readable reset hint: text right after "reset(s)" up to a sentence
# boundary — e.g. "resets 2pm (Asia/Kolkata)".
RESET_RE = re.compile(r"(?i)resets?\b[^\n.]{0,60}")


def _num(v):
    """int if it looks like a token count, else None (never raise)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_result(stdout_text):
    """(result_text, usage_dict) from a claude -p --output-format json stdout.
    Falls back to (raw_text, {}) when stdout isn't the expected JSON object."""
    stripped = stdout_text.strip()
    if not stripped:
        return "", {}
    try:
        obj = json.loads(stripped)
    except (ValueError, TypeError):
        return stdout_text, {}
    if not isinstance(obj, dict):
        return stdout_text, {}
    result = obj.get("result")
    if not isinstance(result, str):
        result = stdout_text
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    return result, {
        "input_tokens": _num(usage.get("input_tokens")),
        "output_tokens": _num(usage.get("output_tokens")),
        "cache_read": _num(usage.get("cache_read_input_tokens")),
        "cache_creation": _num(usage.get("cache_creation_input_tokens")),
        "num_turns": _num(obj.get("num_turns")),
        "duration_ms": _num(obj.get("duration_ms")),
        "total_cost_usd": obj.get("total_cost_usd"),
    }


def detect_limit(raw_text):
    """(hit: bool, reset_hint: str) from the RAW combined stdout+stderr."""
    if not LIMIT_RE.search(raw_text):
        return False, ""
    m = RESET_RE.search(raw_text)
    reset = m.group(0).strip() if m else ""
    return True, reset


def build_record(tenant, rc, usage, limit, reset, now_iso):
    rec = {"ts": now_iso, "tenant": tenant, "rc": rc, "limit": limit}
    if reset:
        rec["reset"] = reset
    for k in ("input_tokens", "output_tokens", "cache_read", "cache_creation",
              "num_turns", "duration_ms", "total_cost_usd"):
        rec[k] = usage.get(k)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", required=True)
    ap.add_argument("--stderr", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--rc", type=int, required=True)
    ap.add_argument("--result-out", required=True)
    ap.add_argument("--usage-out", required=True)
    ap.add_argument("--now", default=None, help="ISO8601 override (tests)")
    args = ap.parse_args(argv)

    def _read(p):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    out_text = _read(args.stdout)
    err_text = _read(args.stderr)
    result, usage = parse_result(out_text)
    limit, reset = detect_limit(out_text + "\n" + err_text)

    with open(args.result_out, "w", encoding="utf-8") as fh:
        fh.write(result if result else out_text)

    now_iso = args.now or datetime.datetime.now().isoformat(timespec="seconds")
    rec = build_record(args.tenant, args.rc, usage, limit, reset, now_iso)
    try:
        with open(args.usage_out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError as exc:  # usage tracking must never break the pass
        print(f"warning: could not append usage record: {exc}", file=sys.stderr)

    parsed = 1 if usage else 0
    print(f"limit={1 if limit else 0}\treset={reset}\tparsed={parsed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
