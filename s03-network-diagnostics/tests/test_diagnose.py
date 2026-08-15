from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from diagnose import InvalidInput, diagnose, load_scenario  # noqa: E402


class DiagnoseTests(unittest.TestCase):
    fixture = ROOT / "fixtures" / "scenarios.json"

    def test_all_expected_decisions(self) -> None:
        expected = {
            "healthy": "HEALTHY",
            "route-missing": "ROUTE",
            "dns-forwarding-missing": "DNS",
            "security-blocked": "SECURITY",
            "reachability-blocked": "REACHABILITY",
        }
        for name, decision in expected.items():
            with self.subTest(name=name):
                version, observation = load_scenario(self.fixture, name)
                self.assertEqual(diagnose(version, name, observation)["decision"], decision)

    def test_diagnosis_stops_at_first_failure(self) -> None:
        version, observation = load_scenario(self.fixture, "route-missing")
        result = diagnose(version, "route-missing", observation)
        self.assertEqual(result["checked_stages"], ["route"])

    def test_unknown_scenario_fails_closed(self) -> None:
        with self.assertRaises(InvalidInput):
            load_scenario(self.fixture, "unknown")

    def test_missing_stage_fails_closed(self) -> None:
        payload = json.loads(self.fixture.read_text(encoding="utf-8"))
        broken = copy.deepcopy(payload)
        del broken["scenarios"]["healthy"]["dns"]
        temporary = ROOT / "tests" / ".invalid-fixture.json"
        try:
            temporary.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(InvalidInput):
                load_scenario(temporary, "healthy")
        finally:
            temporary.unlink(missing_ok=True)

    def test_wrong_passed_type_fails_closed(self) -> None:
        payload = json.loads(self.fixture.read_text(encoding="utf-8"))
        payload["scenarios"]["healthy"]["dns"]["passed"] = "true"
        temporary = ROOT / "tests" / ".invalid-type.json"
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(InvalidInput):
                load_scenario(temporary, "healthy")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
