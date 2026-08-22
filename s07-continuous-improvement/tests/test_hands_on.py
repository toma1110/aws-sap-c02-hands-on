import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Context:
    memory_limit_in_mb = 128


class HandsOnTests(unittest.TestCase):
    MUTATING_CALLS = (
        "lambda update-function-configuration",
        "lambda delete-function",
        "logs delete-log-group",
        "iam detach-role-policy",
        "iam delete-role",
    )

    def run_script_with_fake_aws(self, script_name, **overrides):
        bash = shutil.which("bash")
        if os.name == "nt":
            git_bash = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if git_bash.exists():
                bash = str(git_bash)
        if not bash:
            self.skipTest("bash is unavailable")

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        directory_path = Path(directory.name)
        fake_bin = directory_path / "bin"
        fake_bin.mkdir()
        call_log = directory_path / "aws-calls.txt"
        fake_aws = fake_bin / "aws"
        fake_aws.write_bytes(
            (
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$AWS_CALL_LOG\"\n"
                "if [[ \"$1 $2\" == 'sts get-caller-identity' ]]; then echo \"${ACTUAL_ACCOUNT_ID:-111122223333}\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == 'lambda get-function' ]]; then\n"
                "  [[ \"${FUNCTION_EXISTS:-0}\" == 1 ]] || exit 1\n"
                "  echo 'arn:aws:lambda:ap-northeast-1:111122223333:function:sap-c02-s07-learner-test'; exit 0\n"
                "fi\n"
                "if [[ \"$1 $2\" == 'lambda list-tags' ]]; then echo \"${FUNCTION_TAG:-s07-continuous-improvement}\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == 'logs describe-log-groups' ]]; then echo \"${LOG_COUNT:-0}\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == 'logs list-tags-for-resource' ]]; then echo \"${LOG_TAG:-s07-continuous-improvement}\"; exit 0; fi\n"
                "if [[ \"$1 $2\" == 'iam get-role' ]]; then exit 1; fi\n"
                "exit 0\n"
            ).encode("utf-8")
        )
        fake_aws.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
            "AWS_CALL_LOG": str(call_log),
            "AWS_REGION": "ap-northeast-1",
            "EXPECTED_ACCOUNT_ID": "",
            "ACTUAL_ACCOUNT_ID": "111122223333",
            "FUNCTION_EXISTS": "0",
            "FUNCTION_TAG": "s07-continuous-improvement",
            "LOG_COUNT": "0",
            "LOG_TAG": "s07-continuous-improvement",
            "LAB_ID": "learner-test",
        })
        env.update(overrides)
        result = subprocess.run(
            [bash, str(ROOT / script_name)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        calls = call_log.read_text(encoding="utf-8") if call_log.exists() else ""
        return result, calls

    def assert_no_aws_mutation(self, calls):
        for operation in self.MUTATING_CALLS:
            self.assertNotIn(operation, calls)

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

    def test_invoke_removes_temporary_response_on_aws_failure(self):
        measure = load_module("measure_cleanup", "measure.py")
        with tempfile.TemporaryDirectory() as directory:
            response_path = Path(directory) / "response.json"

            class ResponseFile:
                name = str(response_path)

                def close(self):
                    response_path.touch()

            with mock.patch.object(measure.tempfile, "NamedTemporaryFile", return_value=ResponseFile()), \
                    mock.patch.object(measure.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, ["aws"])):
                with self.assertRaises(subprocess.CalledProcessError):
                    measure.invoke("lab", "ap-northeast-1", 10)
            self.assertFalse(response_path.exists())

    def test_invoke_removes_temporary_response_on_metadata_parse_failure(self):
        measure = load_module("measure_parse_cleanup", "measure.py")
        with tempfile.TemporaryDirectory() as directory:
            response_path = Path(directory) / "response.json"

            class ResponseFile:
                name = str(response_path)

                def close(self):
                    response_path.touch()

            with mock.patch.object(measure.tempfile, "NamedTemporaryFile", return_value=ResponseFile()), \
                    mock.patch.object(measure.subprocess, "check_output", return_value="not-json"):
                with self.assertRaises(json.JSONDecodeError):
                    measure.invoke("lab", "ap-northeast-1", 10)
            self.assertFalse(response_path.exists())

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

    def test_cleanup_refuses_log_group_without_ownership_tag(self):
        result, calls = self.run_script_with_fake_aws(
            "cleanup.sh",
            EXPECTED_ACCOUNT_ID="111122223333",
            FUNCTION_EXISTS="0",
            LOG_COUNT="1",
            LOG_TAG="another-hands-on",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log group tagが一致しない", result.stderr)
        self.assert_no_aws_mutation(calls)

    def test_mutating_scripts_stop_without_expected_account(self):
        for script_name in ("improve.sh", "cleanup.sh"):
            with self.subTest(script_name=script_name):
                result, calls = self.run_script_with_fake_aws(script_name, FUNCTION_EXISTS="1")
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_aws_mutation(calls)

    def test_mutating_scripts_stop_on_wrong_account(self):
        for script_name in ("improve.sh", "cleanup.sh"):
            with self.subTest(script_name=script_name):
                result, calls = self.run_script_with_fake_aws(
                    script_name,
                    EXPECTED_ACCOUNT_ID="999900001111",
                    ACTUAL_ACCOUNT_ID="111122223333",
                    FUNCTION_EXISTS="1",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_aws_mutation(calls)

    def test_mutating_scripts_stop_on_non_owned_function(self):
        for script_name in ("improve.sh", "cleanup.sh"):
            with self.subTest(script_name=script_name):
                result, calls = self.run_script_with_fake_aws(
                    script_name,
                    EXPECTED_ACCOUNT_ID="111122223333",
                    FUNCTION_EXISTS="1",
                    FUNCTION_TAG="another-hands-on",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("関数tagが一致しない", result.stderr)
                self.assert_no_aws_mutation(calls)


if __name__ == "__main__":
    unittest.main()
