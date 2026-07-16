#!/usr/bin/env python3
"""Daily per-tenant usage rollup for the ops channel.

Scans <state-root>/*/usage.jsonl (EVERY tenant's state dir — single-mode and
paused tenants included, not just roster-enabled ones), aggregates the given
day's per-pass records, and prints a Telegram-ready summary to stdout. The
orchestrator sends the output verbatim to the ops channel. Pure aggregation —
no model call, no subscription tokens. Stdlib only.

Usage:
  usage-rollup.py --state-root /home/agent/state --date 2026-07-15

Prints nothing (empty) when no passes ran that day, so the caller sends nothing.
"""

import argparse
import glob
import json
import os
import sys

# All four token fields matter: for a cached agent, `input_tokens` is only the
# tiny non-cached delta — the real volume is `cache_read` (context re-read every
# turn). Summing just input+output made the digest read "in 170" while millions
# of cache-read tokens were invisible. Track all four; report a real input total.
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read", "cache_creation")


def parse_records(text):
    """Parse a usage.jsonl body into dict records, skipping malformed lines."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _add(a, b):
    """Sum treating None/missing as 0, but keep None if neither contributes."""
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


def aggregate(tenants, date):
    """tenants: {name: [record, ...]} -> {'per': {name: stats}, 'total': stats}.
    Only records whose `ts` starts with `date` count. stats keys: passes,
    input_tokens, output_tokens, limits."""
    def _blank():
        d = {"passes": 0, "limits": 0}
        for f in TOKEN_FIELDS:
            d[f] = None
        return d

    per = {}
    total = _blank()
    for name in sorted(tenants):
        recs = [r for r in tenants[name] if str(r.get("ts", "")).startswith(date)]
        if not recs:
            continue
        s = _blank()
        s["passes"] = len(recs)
        for r in recs:
            for f in TOKEN_FIELDS:
                s[f] = _add(s[f], r.get(f))
            if r.get("limit"):
                s["limits"] += 1
        per[name] = s
        total["passes"] += s["passes"]
        total["limits"] += s["limits"]
        for f in TOKEN_FIELDS:
            total[f] = _add(total[f], s[f])
    return {"per": per, "total": total}


def _hk(n):
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def _input_total(s):
    """Real input volume = non-cached input + cache reads + cache creation.
    None only when every contributing field is missing."""
    parts = [s.get(f) for f in ("input_tokens", "cache_read", "cache_creation")]
    if all(p is None for p in parts):
        return None
    return sum(p or 0 for p in parts)


def _line(name, s):
    flag = f" · {s['limits']} limit-hit{'s' if s['limits'] != 1 else ''}"
    flag += " ⚠️" if s["limits"] else ""
    cached = _add(s.get("cache_read"), s.get("cache_creation"))
    cache_note = f" (cache {_hk(cached)})" if cached else ""
    return (f"{name}: {s['passes']} pass{'es' if s['passes'] != 1 else ''} · "
            f"in {_hk(_input_total(s))}{cache_note} / out {_hk(s['output_tokens'])}{flag}")


def render(agg, date):
    """Build the summary string, or '' when nothing ran that day."""
    if not agg["per"]:
        return ""
    lines = [f"📊 Agent usage — {date}"]
    for name in agg["per"]:
        lines.append(_line(name, agg["per"][name]))
    lines.append(_line("Total", agg["total"]))
    return "\n".join(lines)


def collect(state_root):
    """{tenant_name: [records]} from <state_root>/*/usage.jsonl."""
    tenants = {}
    for path in sorted(glob.glob(os.path.join(state_root, "*", "usage.jsonl"))):
        name = os.path.basename(os.path.dirname(path))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                tenants[name] = parse_records(fh.read())
        except OSError:
            continue
    return tenants


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-root", required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    summary = render(aggregate(collect(args.state_root), args.date), args.date)
    if summary:
        print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
