#!/usr/bin/env python3
"""Unit tests for dw-config.py.

The filename has a hyphen, so it is not importable by name — load it from its
path with importlib and drive main() with stdout captured. Run with:

    python3 dev-workflow/test_dw_config.py
"""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "dw_config", os.path.join(_HERE, "dw-config.py")
)
dw_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw_config)


CONFIG = """\
repo:
  base_branch: dev
  prod_branch: main
tracker:
  provider: linear
  team: Acme
  ticket_prefix: ABC
  roles:
    queue: { label: agent, states: [Todo, In Progress] }
quality:
  test: "scripts/test.sh {pkgs}"
"""


def _run(*args):
    """Return (rc, stdout) for `dw-config <args>`."""
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        fh.write(CONFIG)
        path = fh.name
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = dw_config.main(["dw-config.py", path] + list(args))
    finally:
        os.unlink(path)
    return rc, buf.getvalue()


class DwConfigTests(unittest.TestCase):
    # ── single-key mode: byte-for-byte back-compat ──
    def test_single_scalar(self):
        rc, out = _run("tracker.team")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "Acme\n")

    def test_single_missing_with_default(self):
        rc, out = _run("build.model", "sonnet")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "sonnet\n")

    def test_single_missing_no_default_errors(self):
        rc, out = _run("nope.here")
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_single_list_one_per_line(self):
        rc, out = _run("tracker.roles.queue.states")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "Todo\nIn Progress\n")

    # ── batch mode ──
    def test_batch_happy_path(self):
        rc, out = _run("--batch", "tracker.team", "repo.base_branch")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertIn("tracker.team=Acme", lines)
        self.assertIn("repo.base_branch=dev", lines)

    def test_batch_value_is_shell_escaped(self):
        rc, out = _run("--batch", "quality.test")
        self.assertEqual(rc, 0)
        # a value with a space/brace must come back quoted
        self.assertEqual(out, "quality.test='scripts/test.sh {pkgs}'\n")

    def test_batch_missing_key_with_default(self):
        rc, out = _run("--batch", "build.model=sonnet")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "build.model=sonnet\n")

    def test_batch_missing_key_no_default(self):
        rc, out = _run("--batch", "nope.here")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "nope.here=\n")

    def test_batch_list_value(self):
        rc, out = _run("--batch", "tracker.roles.queue.states")
        self.assertEqual(rc, 0)
        # each item individually quoted, space-joined, on one line
        self.assertEqual(out, "tracker.roles.queue.states=Todo 'In Progress'\n")


if __name__ == "__main__":
    unittest.main()
