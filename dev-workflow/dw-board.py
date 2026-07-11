#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Framework board tool — regenerate local board views and prune finished tickets.

    dw-board snapshot [--config dev-workflow.yml] [--team NAME] [--out DIR]
    dw-board prune    [--config dev-workflow.yml] [--team NAME] [--days N] [--yes]
    dw-board import   [FILE] [--config dev-workflow.yml] [--team NAME] [--yes]

    uv run dev-workflow/dw-board.py snapshot        # framework checkout (uv supplies PyYAML)
    python3 dev-workflow/dw-board.py snapshot       # bare system python3 (stdlib fallback)

A faithful port of niptao's `scripts/linear-snapshot.sh` + `scripts/linear-prune.sh`
+ `scripts/linear-import.sh`, parameterized by `dev-workflow.yml`: team, gate labels,
output dir, prune policy, and the import holding file all come from config; the proven
Linear GraphQL queries and bucketing/threshold/create logic are preserved. Talks to
Linear over `urllib` (no third-party HTTP dep).

Credentials come from the ENVIRONMENT ONLY — `LINEAR_API_KEY`, with the same
`.env` worktree fallback niptao's scripts use (we extract just that one key, never
source the whole file, and never read it from dev-workflow.yml).

`snapshot` is read-only. `prune` is the one gated mutation: it never deletes unless
`board.prune.allow_delete` is true in config AND `--yes` is passed at run time; with
allow_delete false (the default) it only ever prints the report and exits.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.linear.app/graphql"


# ── config reader: reuse dw-config.py so there is ONE config reader ───────────
def _dw_config():
    """Import the sibling dw-config.py as a module (its name has a hyphen, so it
    is not directly importable). Reuses its PyYAML-or-stdlib loader and get()."""
    # realpath (not abspath) resolves the /usr/local/bin/dw-board symlink to the
    # real file in /opt/.../bin, so dw-config.py is found next to it there rather
    # than looked for in /usr/local/bin (where only the dw-config symlink lives).
    here = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(here, "dw-config.py")
    if not os.path.isfile(path):
        sys.exit("ERROR: dw-config.py not found next to dw-board.py (looked in %s) "
                 "— they install together; run the framework installer." % here)
    spec = importlib.util.spec_from_file_location("dw_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_DWC = _dw_config()


def _load_config(path):
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return _DWC._load(fh)


def _cfg(data, dotted, default=None):
    val = _DWC.get(data, dotted)
    if val is _DWC._MISSING:
        return default
    return val


# ── credentials: environment only, with niptao's .env worktree fallback ──────
def _extract_key(env_path):
    """Return the LINEAR_API_KEY value from an env file (unquoted), or None.
    Extracts only that one line — never sources the whole .env."""
    if not os.path.isfile(env_path):
        return None
    val = None
    try:
        with open(env_path) as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("LINEAR_API_KEY="):
                    val = stripped[len("LINEAR_API_KEY="):].strip()
    except OSError:
        return None
    if val is None:
        return None
    if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
        val = val[1:-1]
    return val or None


def _git_common_dir(start):
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _resolve_key():
    """LINEAR_API_KEY from the environment, else the local .env, else the main
    repo's .env (linked worktrees don't carry the main .env). Environment only —
    never dev-workflow.yml."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key
    cwd = os.getcwd()
    key = _extract_key(os.path.join(cwd, ".env"))
    if key:
        return key
    common = _git_common_dir(cwd)
    if common:
        main_root = os.path.dirname(common)
        key = _extract_key(os.path.join(main_root, ".env"))
        if key:
            return key
    return None


# ── GraphQL over urllib ──────────────────────────────────────────────────────
def _gql(key, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Authorization": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.stderr.write("ERROR: Linear API HTTP %s: %s\n" % (exc.code, detail))
        sys.exit(1)
    except urllib.error.URLError as exc:
        sys.stderr.write("ERROR: could not reach Linear API: %s\n" % exc.reason)
        sys.exit(1)
    if payload.get("errors"):
        sys.stderr.write("ERROR: GraphQL error: %s\n" % json.dumps(payload["errors"]))
        sys.exit(1)
    return payload["data"]


def _paged_issues(key, team, state_types, node_fields):
    """Page through a team's issues filtered by state.type, returning all nodes.
    `state_types` is a dict like {"nin": [...]} or {"in": [...]}."""
    query = (
        "query($filter: IssueFilter, $after: String) {\n"
        "  issues(filter: $filter, first: 100, after: $after) {\n"
        "    pageInfo { hasNextPage endCursor }\n"
        "    nodes { %s }\n"
        "  }\n"
        "}" % node_fields
    )
    nodes = []
    after = None
    while True:
        variables = {
            "filter": {"team": {"name": {"eq": team}}, "state": {"type": state_types}},
            "after": after,
        }
        data = _gql(key, query, variables)
        page = data["issues"]
        nodes.extend(page["nodes"])
        if page["pageInfo"]["hasNextPage"]:
            after = page["pageInfo"]["endCursor"]
        else:
            break
    return nodes


# ── snapshot ──────────────────────────────────────────────────────────────────
SNAPSHOT_FIELDS = (
    "identifier title priority priorityLabel "
    "state { name type } project { name } "
    "labels { nodes { name } } projectMilestone { name }"
)


def _normalize(node, gates):
    labels = [n["name"] for n in node.get("labels", {}).get("nodes", [])]
    pr = node.get("priority") or 0
    stype = (node.get("state") or {}).get("type")
    project = (node.get("project") or {}).get("name") or "—"
    milestone = (node.get("projectMilestone") or {}).get("name")
    gate_labels = [g for g in gates if g in labels]
    # niptao's forward marker was a hardcoded `gated` label; parameterized here
    # as "carries any configured gate label" so team/gates come from config.
    gated = bool(gate_labels)
    if stype in ("started", "unstarted"):
        bucket = "todo"
    elif gated or milestone is not None:
        bucket = "v2"
    else:
        bucket = "backlog"
    return {
        "id": node["identifier"],
        "title": node["title"],
        "pr": pr,
        "prName": "No priority" if pr == 0 else node.get("priorityLabel"),
        "prSort": 99 if pr == 0 else pr,
        "stype": stype,
        "project": project,
        "milestone": milestone,
        "labels": labels,
        "gate_labels": gate_labels,
        "gated": gated,
        "bucket": bucket,
    }


def _grouped(items, keyfn):
    """Group items by keyfn, returning (key, [items]) pairs in first-seen order."""
    order, index = [], {}
    for it in items:
        k = keyfn(it)
        if k not in index:
            index[k] = len(order)
            order.append((k, []))
        order[index[k]][1].append(it)
    return order


def _header(title, stamp, team):
    return (
        "<!-- GENERATED by dw-board.py snapshot on %s — DO NOT EDIT.\n"
        "     Linear (team %s) is the source of truth; re-run to refresh. -->\n\n"
        "# %s\n\n" % (stamp, team, title)
    )


def _render_todo(issues):
    rows = sorted((i for i in issues if i["bucket"] == "todo"),
                  key=lambda i: (i["prSort"], i["project"]))
    if not rows:
        return "_(nothing active)_\n"
    out = []
    for pr_name, group in _grouped(rows, lambda i: i["prName"]):
        lines = []
        for i in group:
            lbl = " `%s`" % ",".join(i["labels"]) if i["labels"] else ""
            lines.append("- **%s** · %s%s — %s" % (i["id"], i["project"], lbl, i["title"]))
        out.append("### %s\n%s\n" % (pr_name, "\n".join(lines)))
    return "\n".join(out)


def _render_backlog(issues):
    rows = sorted((i for i in issues if i["bucket"] == "backlog"),
                  key=lambda i: (i["project"], i["prSort"]))
    if not rows:
        return "_(empty)_\n"
    out = []
    for project, group in _grouped(rows, lambda i: i["project"]):
        lines = ["- **%s** · %s — %s" % (i["id"], i["prName"], i["title"]) for i in group]
        out.append("### %s\n%s\n" % (project, "\n".join(lines)))
    return "\n".join(out)


def _render_v2(issues):
    rows = [i for i in issues if i["bucket"] == "v2"]
    for i in rows:
        i["mkey"] = i["milestone"] or "(no milestone)"
    rows.sort(key=lambda i: (i["mkey"], i["prSort"]))
    if not rows:
        return "_(empty)_\n"
    out = []
    for mkey, group in _grouped(rows, lambda i: i["mkey"]):
        lines = []
        for i in group:
            tag = " `%s`" % ",".join(i["gate_labels"]) if i["gate_labels"] else ""
            lines.append("- **%s** · %s · %s%s — %s"
                         % (i["id"], i["prName"], i["project"], tag, i["title"]))
        out.append("### %s\n%s\n" % (mkey, "\n".join(lines)))
    return "\n".join(out)


def _srank(stype):
    return 0 if stype == "started" else (1 if stype == "unstarted" else 2)


def _render_gate(issues, gate):
    rows = [i for i in issues if gate in i["labels"]]
    if not rows:
        return "_(nothing labeled %s)_\n" % gate
    sname = {0: "In Progress", 1: "Todo", 2: "Backlog (queued for %s)" % gate}
    for i in rows:
        i["_srank"] = _srank(i["stype"])
    rows.sort(key=lambda i: (i["_srank"], i["prSort"]))
    out = []
    for srank, group in _grouped(rows, lambda i: i["_srank"]):
        lines = []
        for i in group:
            tag = " `%s`" % ",".join(i["gate_labels"]) if i["gate_labels"] else ""
            lines.append("- **%s** · %s · %s%s — %s"
                         % (i["id"], i["prName"], i["project"], tag, i["title"]))
        out.append("### %s\n%s\n" % (sname[srank], "\n".join(lines)))
    return "\n".join(out)


def cmd_snapshot(args):
    key = _resolve_key()
    if not key:
        sys.stderr.write("ERROR: LINEAR_API_KEY not set in environment\n")
        return 1

    data = _load_config(args.config)
    team = args.team or _cfg(data, "tracker.team")
    if not team:
        sys.stderr.write("ERROR: no team — set tracker.team in %s or pass --team\n" % args.config)
        return 1
    gates = _cfg(data, "board.gates", []) or []
    if not isinstance(gates, list):
        sys.stderr.write("ERROR: board.gates must be a list of labels\n")
        return 1

    if args.out:
        out_dir = args.out
    else:
        views = _cfg(data, "board.views", ".local/board")
        base = os.path.dirname(os.path.abspath(args.config))
        out_dir = views if os.path.isabs(views) else os.path.join(base, views)

    nodes = _paged_issues(key, team, {"nin": ["completed", "canceled"]}, SNAPSHOT_FIELDS)
    # Drop onboarding stubs (no project), mirroring niptao.
    issues = [_normalize(n, gates) for n in nodes if (n.get("project") or {}).get("name")]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    os.makedirs(out_dir, exist_ok=True)

    # Single-writer lock — the board dir may be shared across worktrees, so two
    # snapshots at once can leave a torn file. mkdir is atomic everywhere; the
    # loser skips (the winner is regenerating the same fresh views).
    lock = os.path.join(out_dir, ".snapshot.lock")
    try:
        os.mkdir(lock)
    except FileExistsError:
        sys.stderr.write("dw-board snapshot: another run holds %s — skipping.\n" % lock)
        return 0
    try:
        _write(out_dir, "todo.md",
               _header("TODO — active work (In Progress + Todo)", stamp, team) + _render_todo(issues))
        _write(out_dir, "backlog.md",
               _header("BACKLOG — deferred, not yet a forward initiative", stamp, team) + _render_backlog(issues))
        _write(out_dir, "v2.md",
               _header("V2 — forward initiatives (gated / milestone work)", stamp, team) + _render_v2(issues))
        for gate in gates:
            _write(out_dir, "%s.md" % gate,
                   _header("GATE — label: %s" % gate, stamp, team) + _render_gate(issues, gate))
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass

    print("Wrote board snapshot (%d open issues) to %s/:" % (len(issues), out_dir))
    for bucket in ("todo", "backlog", "v2"):
        n = sum(1 for i in issues if i["bucket"] == bucket)
        print("  %-14s %d issues" % (bucket + ".md", n))
    for gate in gates:
        n = sum(1 for i in issues if gate in i["labels"])
        print("  %-14s %d issues (cross-cuts the above — gate label: %s)" % (gate + ".md", n, gate))
    return 0


def _write(out_dir, name, text):
    with open(os.path.join(out_dir, name), "w") as fh:
        fh.write(text)


# ── prune ─────────────────────────────────────────────────────────────────────
PRUNE_FIELDS = "id identifier title completedAt canceledAt state { type }"


def cmd_prune(args):
    key = _resolve_key()
    if not key:
        sys.stderr.write("ERROR: LINEAR_API_KEY not set in environment\n")
        return 1

    data = _load_config(args.config)
    team = args.team or _cfg(data, "tracker.team")
    if not team:
        sys.stderr.write("ERROR: no team — set tracker.team in %s or pass --team\n" % args.config)
        return 1
    days = args.days if args.days is not None else _cfg(data, "board.prune.threshold_days", 7)
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        sys.stderr.write("ERROR: board.prune.threshold_days must be an integer > 0\n")
        return 1
    allow_delete = bool(_cfg(data, "board.prune.allow_delete", False))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("Linear prune — team=%s  threshold=%dd  cutoff=%s" % (team, days, cutoff))

    nodes = _paged_issues(key, team, {"in": ["completed", "canceled"]}, PRUNE_FIELDS)
    matched = []
    for n in nodes:
        closed = n.get("completedAt") or n.get("canceledAt")
        if closed is not None and closed < cutoff:
            matched.append((n["id"], n["identifier"], (n.get("state") or {}).get("type"),
                            closed, n["title"]))

    if not matched:
        print("Nothing to prune — no Done/Canceled issues closed before %s." % cutoff)
        return 0

    print()
    print("%d issue(s) eligible for prune (closed > %dd ago):" % (len(matched), days))
    print()
    print("%-10s %-10s %-22s %s" % ("ID", "STATE", "CLOSED", "TITLE"))
    for _id, ident, stype, closed, title in matched:
        print("%-10s %-10s %-22s %s" % (ident, stype, closed, title))
    print()

    # CRITICAL gate: report-only unless the repo opted in. With allow_delete
    # false we NEVER mutate — we print the report (which doubles as hygiene input)
    # and exit. --yes is irrelevant here; it cannot delete.
    if not allow_delete:
        print("REPORT-ONLY — board.prune.allow_delete is false; nothing was deleted.")
        print("Set board.prune.allow_delete: true (and pass --yes) to actually trash them.")
        return 0

    if not args.yes:
        print("DRY-RUN — no issues were deleted. Re-run with --yes to trash them.")
        print("(Trashed issues stay recoverable in the Linear UI for ~2 weeks.)")
        return 0

    mutation = "mutation($id: String!) { issueDelete(id: $id) { success } }"
    ok = fail = 0
    for _id, ident, _stype, _closed, _title in matched:
        result = _gql(key, mutation, {"id": _id})
        if (result.get("issueDelete") or {}).get("success"):
            print("  trashed %s" % ident)
            ok += 1
        else:
            sys.stderr.write("  FAILED  %s\n" % ident)
            fail += 1
    print()
    print("Done: %d trashed, %d failed. Recoverable in the Linear UI (Trash) for ~2 weeks."
          % (ok, fail))
    return 0 if fail == 0 else 1


# ── import ──────────────────────────────────────────────────────────────────
# Bulk-create issues from a JSON holding file — a faithful port of niptao's
# linear-import.sh. One difference: niptao resolves the team by KEY; dw-board's
# convention everywhere else is the team NAME (tracker.team, as used by snapshot/
# prune), so import resolves teams by name too. Names → ids (project, labels,
# milestone) are resolved against the live board so you author with human names;
# labels and milestones must already exist. Dry-run by default; --yes creates.
IMPORT_RESOLVE = (
    "query($team: String!) {\n"
    "  teams(filter: {name: {eq: $team}}) { nodes { id name } }\n"
    "  projects(first: 50) {\n"
    "    nodes { id name projectMilestones(first: 50) { nodes { id name } } }\n"
    "  }\n"
    "  issueLabels(first: 100) { nodes { id name } }\n"
    "}"
)
IMPORT_CREATE = (
    "mutation($input: IssueCreateInput!) {\n"
    "  issueCreate(input: $input) { success issue { identifier url } }\n"
    "}"
)
_PRIORITY = {"urgent": 1, "high": 2, "medium": 3, "low": 4, "none": 0}
_PRIORITY_NAME = {0: "none", 1: "urgent", 2: "high", 3: "medium", 4: "low"}


def _priority_int(name):
    """Map a priority word to Linear's int; unknown/empty → 0 (none), as niptao."""
    return _PRIORITY.get(str(name if name is not None else "none").strip().lower(), 0)


def _import_file(args, data):
    """Resolve the input file: positional FILE wins, else <board.views>/import.json
    (relative to the config dir, mirroring snapshot's out-dir resolution)."""
    if args.file:
        return args.file
    views = _cfg(data, "board.views", ".local/board")
    base = os.path.dirname(os.path.abspath(args.config))
    views_dir = views if os.path.isabs(views) else os.path.join(base, views)
    return os.path.join(views_dir, "import.json")


def _print_planned(p):
    bits = ["project=%s" % p["project"], "priority=%s" % _PRIORITY_NAME[p["priority"]]]
    if p["milestone_id"]:
        bits.append("milestone=%s" % p["milestone"])
    if p["label_ids"]:
        bits.append("labels=%s" % ",".join(p["labels"]))
    print("  would create: %s  [%s]" % (p["title"], "  ".join(bits)))


def cmd_import(args):
    key = _resolve_key()
    if not key:
        sys.stderr.write("ERROR: LINEAR_API_KEY not set in environment\n")
        return 1

    data = _load_config(args.config)
    team = args.team or _cfg(data, "tracker.team")
    if not team:
        sys.stderr.write("ERROR: no team — set tracker.team in %s or pass --team\n" % args.config)
        return 1

    infile = _import_file(args, data)
    if not os.path.isfile(infile):
        sys.stderr.write("ERROR: input file not found: %s\n" % infile)
        return 1
    try:
        with open(infile) as fh:
            rows = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("ERROR: could not read %s: %s\n" % (infile, exc))
        return 1
    if not isinstance(rows, list):
        sys.stderr.write("ERROR: %s must be a JSON array of issue objects\n" % infile)
        return 1

    meta = _gql(key, IMPORT_RESOLVE, {"team": team})
    team_nodes = (meta.get("teams") or {}).get("nodes") or []
    if not team_nodes:
        sys.stderr.write("ERROR: team %r not found on the board\n" % team)
        return 1
    team_id = team_nodes[0]["id"]
    projects = {p["name"]: p for p in (meta.get("projects") or {}).get("nodes") or []}
    labels_by_name = {l["name"]: l["id"] for l in (meta.get("issueLabels") or {}).get("nodes") or []}

    # Resolve + validate EVERY row up front. Unresolved project/label/milestone
    # names are hard errors: we name them and create nothing (mirrors niptao's
    # "labels/milestones must already exist", but fails instead of skipping).
    planned, errors = [], []
    for idx, row in enumerate(rows):
        where = "issue #%d" % (idx + 1)
        if not isinstance(row, dict):
            errors.append("%s: not a JSON object" % where)
            continue
        title = row.get("title")
        project = row.get("project")
        if not title:
            errors.append("%s: missing required 'title'" % where)
            continue
        where = "%s (%s)" % (where, title)
        if not project:
            errors.append("%s: missing required 'project'" % where)
            continue
        proj = projects.get(project)
        if proj is None:
            errors.append("%s: project not found: %r" % (where, project))
            continue

        want_labels = row.get("labels") or []
        label_ids = []
        for name in want_labels:
            lid = labels_by_name.get(name)
            if lid is None:
                errors.append("%s: label not found: %r" % (where, name))
            else:
                label_ids.append(lid)

        milestone = row.get("milestone")
        milestone_id = None
        if milestone:
            ms = {m["name"]: m["id"]
                  for m in (proj.get("projectMilestones") or {}).get("nodes") or []}
            milestone_id = ms.get(milestone)
            if milestone_id is None:
                errors.append("%s: milestone %r not in project %r" % (where, milestone, project))

        planned.append({
            "title": title,
            "project": project,
            "project_id": proj["id"],
            "priority": _priority_int(row.get("priority")),
            "labels": list(want_labels),
            "label_ids": label_ids,
            "milestone": milestone,
            "milestone_id": milestone_id,
            "description": row.get("description") or "",
        })

    if errors:
        sys.stderr.write("ERROR: %d unresolved reference(s) — nothing was created:\n" % len(errors))
        for e in errors:
            sys.stderr.write("  - %s\n" % e)
        return 1

    print("linear-import — team=%s  file=%s  issues=%d" % (team, infile, len(planned)))
    print("Mode: %s" % ("APPLY (will create issues)" if args.yes else "DRY-RUN (no changes)"))
    print()

    if not args.yes:
        for p in planned:
            _print_planned(p)
        print()
        print("DRY-RUN — nothing created. Re-run with --yes to import. (%d ready)" % len(planned))
        return 0

    ok = fail = 0
    for p in planned:
        inp = {"teamId": team_id, "title": p["title"],
               "priority": p["priority"], "projectId": p["project_id"]}
        if p["description"]:
            inp["description"] = p["description"]
        if p["label_ids"]:
            inp["labelIds"] = p["label_ids"]
        if p["milestone_id"]:
            inp["projectMilestoneId"] = p["milestone_id"]
        result = _gql(key, IMPORT_CREATE, {"input": inp})
        created = result.get("issueCreate") or {}
        if created.get("success"):
            ident = (created.get("issue") or {}).get("identifier")
            print("  created %s — %s" % (ident, p["title"]))
            ok += 1
        else:
            sys.stderr.write("  FAILED — %s\n" % p["title"])
            fail += 1
    print()
    print("Done: %d created, %d failed. Run dw-board snapshot to refresh views." % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv):
    parser = argparse.ArgumentParser(prog="dw-board", description="Framework board tool (Linear).")
    sub = parser.add_subparsers(dest="cmd")

    sp = sub.add_parser("snapshot", help="regenerate local board views from the tracker")
    sp.add_argument("--config", default="dev-workflow.yml", help="path to dev-workflow.yml")
    sp.add_argument("--team", help="override tracker.team")
    sp.add_argument("--out", help="override board.views output dir")
    sp.set_defaults(func=cmd_snapshot)

    pp = sub.add_parser("prune", help="report (or, if opted in, trash) old Done/Canceled issues")
    pp.add_argument("--config", default="dev-workflow.yml", help="path to dev-workflow.yml")
    pp.add_argument("--team", help="override tracker.team")
    pp.add_argument("--days", type=int, help="override board.prune.threshold_days")
    pp.add_argument("--yes", action="store_true", help="actually trash (only if allow_delete)")
    pp.set_defaults(func=cmd_prune)

    ip = sub.add_parser("import", help="bulk-create issues from a JSON holding file (dry-run unless --yes)")
    ip.add_argument("file", nargs="?", help="JSON array of issues (default: <board.views>/import.json)")
    ip.add_argument("--config", default="dev-workflow.yml", help="path to dev-workflow.yml")
    ip.add_argument("--team", help="override tracker.team")
    ip.add_argument("--yes", action="store_true", help="actually create the issues (default: dry-run)")
    ip.set_defaults(func=cmd_import)

    args = parser.parse_args(argv[1:])
    if not getattr(args, "func", None):
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
