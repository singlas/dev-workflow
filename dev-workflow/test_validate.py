#!/usr/bin/env python3
"""Unit tests for validate.py.

The dev-workflow/ directory has a hyphen, so it is not an importable
package — we insert this file's own directory on sys.path and import the
sibling `validate` module directly. Run with:

    python3 dev-workflow/test_validate.py
"""
import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402  (import after sys.path insert)

import validate  # noqa: E402


# A minimal config that satisfies every REQUIRED field.
MINIMAL = {
    "repo": {"base_branch": "dev", "prod_branch": "main"},
    "tracker": {"provider": "linear", "team": "Acme", "ticket_prefix": "ABC"},
}


def _errors_for(config):
    """Dump `config` to a temp file and return validate_file's error list."""
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        yaml.safe_dump(config, fh)
        path = fh.name
    try:
        return validate.validate_file(path)
    finally:
        os.unlink(path)


class ValidateTests(unittest.TestCase):
    def test_minimal_valid_config_passes(self):
        self.assertEqual(_errors_for(copy.deepcopy(MINIMAL)), [])

    def test_unknown_top_key_fails(self):
        cfg = copy.deepcopy(MINIMAL)
        cfg["bogus"] = {"x": 1}
        errors = _errors_for(cfg)
        self.assertTrue(any("bogus" in e for e in errors), errors)

    def test_cap_per_pass_over_ceiling_fails(self):
        cfg = copy.deepcopy(MINIMAL)
        cfg["build"] = {"cap_per_pass": 3}
        errors = _errors_for(cfg)
        self.assertTrue(any("cap_per_pass" in e for e in errors), errors)

    def test_max_lines_over_ceiling_fails(self):
        cfg = copy.deepcopy(MINIMAL)
        cfg["guardrails"] = {"diff_budget": {"max_lines": 900}}
        errors = _errors_for(cfg)
        self.assertTrue(any("max_lines" in e for e in errors), errors)

    def test_missing_tracker_team_fails(self):
        cfg = copy.deepcopy(MINIMAL)
        del cfg["tracker"]["team"]
        errors = _errors_for(cfg)
        self.assertTrue(any("tracker.team" in e for e in errors), errors)

    def test_off_limits_non_list_fails(self):
        cfg = copy.deepcopy(MINIMAL)
        cfg["guardrails"] = {"off_limits": "*.pem"}
        errors = _errors_for(cfg)
        self.assertTrue(any("off_limits" in e for e in errors), errors)

    def test_blog_non_mapping_fails(self):
        cfg = copy.deepcopy(MINIMAL)
        cfg["blog"] = "docs/blog"
        errors = _errors_for(cfg)
        self.assertTrue(any("blog" in e for e in errors), errors)

    def test_valid_blog_passes(self):
        cfg = copy.deepcopy(MINIMAL)
        cfg["blog"] = {"skill": "blog-from-session", "posts_dir": "docs/blog"}
        self.assertEqual(_errors_for(cfg), [])


if __name__ == "__main__":
    unittest.main()
