#!/usr/bin/env python3
"""Unit tests for usage-parse.py + usage-rollup.py. Stdlib only:
    python3 skills/ticket-loop/test_usage.py
"""

import importlib.util
import json
import os
import tempfile
import unittest


def _load(name, filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


up = _load("usage_parse", "usage-parse.py")
ur = _load("usage_rollup", "usage-rollup.py")


class ParseResult(unittest.TestCase):
    def test_valid_json_extracts_result_and_usage(self):
        obj = {"result": "Pass summary here.", "num_turns": 4,
               "duration_ms": 12000, "total_cost_usd": 0,
               "usage": {"input_tokens": 3571, "output_tokens": 727,
                         "cache_read_input_tokens": 6656,
                         "cache_creation_input_tokens": 0}}
        result, usage = up.parse_result(json.dumps(obj))
        self.assertEqual(result, "Pass summary here.")
        self.assertEqual(usage["input_tokens"], 3571)
        self.assertEqual(usage["output_tokens"], 727)
        self.assertEqual(usage["cache_read"], 6656)
        self.assertEqual(usage["num_turns"], 4)

    def test_non_json_falls_back_to_raw(self):
        result, usage = up.parse_result("You've hit your session limit\n")
        self.assertIn("session limit", result)
        self.assertEqual(usage, {})

    def test_empty(self):
        self.assertEqual(up.parse_result("   "), ("", {}))

    def test_json_without_usage_yields_none_tokens(self):
        result, usage = up.parse_result(json.dumps({"result": "ok"}))
        self.assertEqual(result, "ok")
        self.assertIsNone(usage["input_tokens"])


class DetectLimit(unittest.TestCase):
    def test_real_outage_wording(self):
        # The exact 2.1.210 outage line.
        hit, reset = up.detect_limit(
            "You've hit your session limit · resets 2pm (Asia/Kolkata)")
        self.assertTrue(hit)
        self.assertIn("2pm", reset)

    def test_bare_session_limit(self):
        hit, _ = up.detect_limit("Error: session limit reached, try later")
        self.assertTrue(hit)

    def test_limit_resets_phrasing(self):
        hit, reset = up.detect_limit("your limit resets at 14:00 UTC")
        self.assertTrue(hit)
        self.assertIn("14:00", reset)

    def test_normal_output_is_not_a_limit(self):
        hit, reset = up.detect_limit("Pass complete. Opened PR #12. All green.")
        self.assertFalse(hit)
        self.assertEqual(reset, "")


class BuildRecord(unittest.TestCase):
    def test_shape(self):
        usage = {"input_tokens": 10, "output_tokens": 5, "cache_read": None,
                 "cache_creation": None, "num_turns": 1, "duration_ms": 900,
                 "total_cost_usd": 0}
        rec = up.build_record("paytunes", 1, usage, True, "resets 2pm", "2026-07-15T10:00:00")
        self.assertEqual(rec["tenant"], "paytunes")
        self.assertEqual(rec["rc"], 1)
        self.assertTrue(rec["limit"])
        self.assertEqual(rec["reset"], "resets 2pm")
        self.assertEqual(rec["input_tokens"], 10)


class Rollup(unittest.TestCase):
    def _recs(self, n, date, ins, limit=False):
        return [{"ts": f"{date}T0{i}:00:00", "tenant": "x",
                 "input_tokens": ins, "output_tokens": ins // 4,
                 "limit": limit} for i in range(n)]

    def test_aggregate_filters_by_date_and_sums(self):
        tenants = {
            "niptao": self._recs(3, "2026-07-15", 1000),
            "paytunes": self._recs(2, "2026-07-15", 500, limit=True)
                        + self._recs(1, "2026-07-14", 999),  # other day, excluded
        }
        agg = ur.aggregate(tenants, "2026-07-15")
        self.assertEqual(agg["per"]["niptao"]["passes"], 3)
        self.assertEqual(agg["per"]["niptao"]["input_tokens"], 3000)
        self.assertEqual(agg["per"]["paytunes"]["passes"], 2)
        self.assertEqual(agg["per"]["paytunes"]["limits"], 2)
        self.assertEqual(agg["total"]["passes"], 5)
        self.assertEqual(agg["total"]["input_tokens"], 4000)
        self.assertEqual(agg["total"]["limits"], 2)

    def test_render_has_lines_and_total(self):
        agg = ur.aggregate({"niptao": self._recs(1, "2026-07-15", 2000)}, "2026-07-15")
        out = ur.render(agg, "2026-07-15")
        self.assertIn("📊 Agent usage — 2026-07-15", out)
        self.assertIn("niptao:", out)
        self.assertIn("Total:", out)

    def test_render_empty_when_no_passes(self):
        agg = ur.aggregate({"niptao": self._recs(1, "2026-07-14", 2000)}, "2026-07-15")
        self.assertEqual(ur.render(agg, "2026-07-15"), "")

    def test_collect_reads_state_dirs(self):
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, "paytunes")
            os.makedirs(d)
            with open(os.path.join(d, "usage.jsonl"), "w") as fh:
                fh.write(json.dumps({"ts": "2026-07-15T01:00:00", "tenant": "paytunes",
                                     "input_tokens": 42, "output_tokens": 8}) + "\n")
                fh.write("garbage line — should be skipped\n")
            tenants = ur.collect(root)
            self.assertIn("paytunes", tenants)
            self.assertEqual(len(tenants["paytunes"]), 1)

    def test_cache_tokens_counted_in_input_total(self):
        # The "in 170" bug: a cached agent has tiny input_tokens but millions of
        # cache_read tokens; the digest must report the REAL input, not the delta.
        recs = [{"ts": "2026-07-15T01:00:00", "tenant": "rasa",
                 "input_tokens": 170, "output_tokens": 58000,
                 "cache_read": 4_000_000, "cache_creation": 200_000}]
        agg = ur.aggregate({"rasa": recs}, "2026-07-15")
        s = agg["per"]["rasa"]
        self.assertEqual(ur._input_total(s), 170 + 4_000_000 + 200_000)
        line = ur._line("rasa", s)
        self.assertIn("in 4.2M", line)      # real input total, not "in 170"
        self.assertIn("cache 4.2M", line)   # cache made visible
        self.assertNotIn("in 170", line)


if __name__ == "__main__":
    unittest.main()
