import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Context:
    memory_limit_in_mb = 128


class HandsOnTests(unittest.TestCase):
    def test_handler_is_deterministic(self):
        handler = load_module("handler", "handler.py")
        first = handler.lambda_handler({"iterations": 100}, Context())
        second = handler.lambda_handler({"iterations": 100}, Context())
        self.assertEqual(first["checksum"], second["checksum"])
        self.assertEqual(first["iterations"], 100)

    def test_report_parser_pattern(self):
        measure = load_module("measure", "measure.py")
        line = "REPORT RequestId: x Duration: 631.25 ms Billed Duration: 632 ms Memory Size: 512 MB Max Memory Used: 42 MB"
        self.assertEqual(measure.REPORT.search(line).groups(), ("631.25", "632", "512", "42"))

    def comparison_data(self):
        fixed = {"iterations": 10, "samples": 2, "warmup_excluded": 1}
        before_samples = [{"iterations": 10, "checksum": "abc", "memory_mb": 128}] * 2
        after_samples = [{"iterations": 10, "checksum": "abc", "memory_mb": 512}] * 2
        before = {"phase": "before", "region": "ap-northeast-1", "function_name": "lab", "fixed_conditions": fixed, "samples": before_samples, "summary": {"checksum": "abc", "memory_mb": 128, "median_duration_ms": 100, "median_cost_proxy_mb_ms": 12800}}
        after = {"phase": "after", "region": "ap-northeast-1", "function_name": "lab", "fixed_conditions": fixed, "samples": after_samples, "summary": {"checksum": "abc", "memory_mb": 512, "median_duration_ms": 50, "median_cost_proxy_mb_ms": 25600}}
        return before, after

    def run_compare(self, before, after, check=True):
        with tempfile.TemporaryDirectory() as directory:
            before_path = Path(directory) / "before.json"
            after_path = Path(directory) / "after.json"
            before_path.write_text(json.dumps(before), encoding="utf-8")
            after_path.write_text(json.dumps(after), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "compare.py"), str(before_path), str(after_path)],
                check=check, capture_output=True, text=True, encoding="utf-8"
            )
            return result

    def test_compare_accepts_same_conditions_and_checksum(self):
        before, after = self.comparison_data()
        result = self.run_compare(before, after)
        comparison = json.loads(result.stdout)
        self.assertTrue(comparison["fixed_conditions_match"])
        self.assertEqual(comparison["latency_improvement_percent"], 50.0)

    def test_compare_rejects_mismatched_target(self):
        before, after = self.comparison_data()
        after["function_name"] = "another-lab"
        self.assertNotEqual(self.run_compare(before, after, check=False).returncode, 0)

    def test_compare_rejects_inconsistent_sample(self):
        before, after = self.comparison_data()
        after["samples"][1] = {"iterations": 11, "checksum": "different", "memory_mb": 512}
        self.assertNotEqual(self.run_compare(before, after, check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
