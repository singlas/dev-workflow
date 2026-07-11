#!/usr/bin/env python3
"""Offline unittests for queue-count.py — query construction + response parsing
only; the single urllib call in main() is never exercised here.

Run: python3 dev-workflow/test_queue_count.py
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("queue_count", HERE / "queue-count.py")
qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qc)


CONFIG = """\
tracker:
  provider: linear
  team: Acme
  roles:
    queue:   { label: agent, states: [Todo, In Progress] }
    blocked: { label: agent-blocked }
    exclude: { labels: [manual, gated] }
    done:    { state: Done }
"""


def load_cfg(text=CONFIG):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "dev-workflow.yml"
        p.write_text(text)
        return qc.load_config(str(p))


class TestReadRoles(unittest.TestCase):
    def test_reads_team_queue_and_excludes(self):
        data, mod = load_cfg()
        team, label, states, excludes = qc.read_roles(data, mod)
        self.assertEqual(team, "Acme")
        self.assertEqual(label, "agent")
        self.assertEqual(states, ["Todo", "In Progress"])
        self.assertEqual(excludes, ["manual", "gated"])

    def test_missing_queue_role_errors(self):
        data, mod = load_cfg("tracker:\n  team: Acme\n")
        with self.assertRaises(SystemExit):
            qc.read_roles(data, mod)

    def test_no_exclude_role_is_empty_list(self):
        data, mod = load_cfg(
            "tracker:\n  team: Acme\n  roles:\n"
            "    queue: { label: agent, states: [Todo] }\n")
        _, _, _, excludes = qc.read_roles(data, mod)
        self.assertEqual(excludes, [])


class TestBuildPayload(unittest.TestCase):
    def test_filter_shape(self):
        payload = qc.build_payload("Acme", "agent", ["Todo", "In Progress"])
        f = payload["variables"]["filter"]
        self.assertEqual(f["team"]["name"]["eq"], "Acme")
        self.assertEqual(f["labels"]["name"]["eq"], "agent")
        self.assertEqual(f["state"]["name"]["in"], ["Todo", "In Progress"])
        self.assertIn("issues(filter: $filter", payload["query"])


class TestCountEligible(unittest.TestCase):
    def body(self, nodes):
        return {"data": {"issues": {"nodes": nodes}}}

    def node(self, key, labels):
        return {"identifier": key,
                "labels": {"nodes": [{"name": n} for n in labels]}}

    def test_counts_and_drops_excluded(self):
        body = self.body([
            self.node("ABC-1", ["agent"]),
            self.node("ABC-2", ["agent", "manual"]),      # excluded
            self.node("ABC-3", ["agent", "Bug"]),
            self.node("ABC-4", ["agent", "GATED"]),       # excluded, case-insensitive
        ])
        self.assertEqual(qc.count_eligible(body, ["manual", "gated"]), 2)

    def test_empty(self):
        self.assertEqual(qc.count_eligible(self.body([]), ["manual"]), 0)


if __name__ == "__main__":
    unittest.main()
