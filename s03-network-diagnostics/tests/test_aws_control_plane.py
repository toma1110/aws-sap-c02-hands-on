from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("aws_control_plane", ROOT / "scripts" / "aws_control_plane.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ControlPlane = MODULE.ControlPlane
SafetyError = MODULE.SafetyError


class FakeCli:
    def __init__(self, account: str = "111122223333") -> None:
        self.account = account
        self.calls: list[tuple[str, ...]] = []
        self.responses: dict[str, dict] = {}

    def call(self, *arguments: str) -> dict:
        self.calls.append(arguments)
        if arguments[:2] == ("sts", "get-caller-identity"):
            return {"Account": self.account}
        return self.responses.get(arguments[1], {})


def state(account: str = "111122223333", region: str = "us-east-1") -> dict:
    return {
        "schema_version": 1,
        "name": MODULE.NAME,
        "account_id": account,
        "region": region,
        "vpc_id": "vpc-123",
        "subnet_ids": ["subnet-123"],
        "route_table_id": "rtb-123",
        "association_id": "rtbassoc-123",
        "security_group_id": "sg-123",
    }


class ControlPlaneSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.cli = FakeCli()
        self.control = ControlPlane(self.root, "us-east-1", "111122223333", self.cli)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_state(self, payload: dict) -> None:
        self.control.state_dir.mkdir(parents=True, exist_ok=True)
        self.control.state_file.write_text(json.dumps(payload), encoding="utf-8")

    def test_wrong_current_account_fails_closed(self) -> None:
        self.write_state(state())
        self.cli.account = "999900001111"
        with self.assertRaises(SafetyError):
            self.control.load_state()

    def test_wrong_state_region_fails_closed(self) -> None:
        self.write_state(state(region="ap-northeast-1"))
        with self.assertRaises(SafetyError):
            self.control.load_state()

    def test_tampered_vpc_tags_fail_closed(self) -> None:
        payload = state()
        self.cli.responses["describe-vpcs"] = {
            "Vpcs": [{"VpcId": payload["vpc_id"], "CidrBlock": MODULE.VPC_CIDR, "Tags": [{"Key": "Name", "Value": "unrelated"}]}]
        }
        self.cli.responses["describe-subnets"] = {"Subnets": []}
        self.cli.responses["describe-route-tables"] = {"RouteTables": []}
        self.cli.responses["describe-security-groups"] = {"SecurityGroups": []}
        with self.assertRaises(SafetyError):
            self.control.validate_current_resources(payload)

    def test_partial_cleanup_retry_skips_absent_resources(self) -> None:
        payload = state()
        self.write_state(payload)
        self.control.load_state = Mock(return_value=payload)
        self.control.validate_current_resources = Mock(
            return_value={"association": False, "route_table": False, "security_group": False, "subnet": True, "vpc": True}
        )
        self.control.cleanup()
        operations = [item[1] for item in self.cli.calls]
        self.assertEqual(operations, ["delete-subnet", "delete-vpc"])

    def test_residual_reports_nonzero_then_zero_and_removes_state(self) -> None:
        payload = state()
        self.write_state(payload)
        self.control.load_state = Mock(return_value=payload)
        self.control.remaining = Mock(side_effect=[[{"type": "vpc", "id": "vpc-123"}], []])
        result = self.control.residual(attempts=2, delay_seconds=0)
        self.assertEqual(result, {"remaining": []})
        self.assertFalse(self.control.state_dir.exists())

    def test_duplicate_create_is_refused(self) -> None:
        self.write_state(state())
        with self.assertRaises(SafetyError):
            self.control.create()
        self.assertEqual(self.cli.calls, [("sts", "get-caller-identity")])

    def test_state_absent_but_tagged_resource_refuses_create(self) -> None:
        self.cli.responses["describe-vpcs"] = {"Vpcs": [{"VpcId": "vpc-existing"}]}
        self.cli.responses["describe-subnets"] = {"Subnets": []}
        self.cli.responses["describe-route-tables"] = {"RouteTables": []}
        self.cli.responses["describe-security-groups"] = {"SecurityGroups": []}
        with self.assertRaises(SafetyError):
            self.control.create()

    def test_state_absent_but_orphaned_tagged_subnet_refuses_create(self) -> None:
        self.cli.responses["describe-vpcs"] = {"Vpcs": []}
        self.cli.responses["describe-subnets"] = {"Subnets": [{"SubnetId": "subnet-existing"}]}
        self.cli.responses["describe-route-tables"] = {"RouteTables": []}
        self.cli.responses["describe-security-groups"] = {"SecurityGroups": []}
        with self.assertRaises(SafetyError):
            self.control.create()
        subnet_call = next(item for item in self.cli.calls if item[1] == "describe-subnets")
        self.assertIn(f"Name=tag:Name,Values={MODULE.NAME}-a", subnet_call)

    def test_missing_state_cannot_claim_cleanup_or_residual(self) -> None:
        with self.assertRaises(SafetyError):
            self.control.cleanup()
        with self.assertRaises(SafetyError):
            self.control.residual(attempts=1, delay_seconds=0)

    def test_observe_exposes_documented_cidrs_and_raw_field_paths(self) -> None:
        payload = state()
        self.control.state_dir.mkdir(parents=True)
        self.control.load_state = Mock(return_value=payload)
        self.control.validate_current_resources = Mock(
            return_value={"association": True, "route_table": True, "security_group": True, "subnet": True, "vpc": True}
        )

        def response(*arguments: str) -> dict:
            operation = arguments[1]
            if operation == "describe-vpcs":
                return {"Vpcs": [{"CidrBlock": MODULE.VPC_CIDR}]}
            if operation == "describe-vpc-attribute":
                value_key = "EnableDnsSupport" if "enableDnsSupport" in arguments else "EnableDnsHostnames"
                return {value_key: {"Value": True}}
            if operation == "describe-subnets":
                return {"Subnets": [{"CidrBlock": MODULE.SUBNET_CIDR}]}
            if operation == "describe-route-tables":
                return {
                    "RouteTables": [
                        {"Routes": [{"DestinationCidrBlock": MODULE.VPC_CIDR, "GatewayId": "local", "State": "active"}]}
                    ]
                }
            if operation == "describe-security-groups":
                return {"SecurityGroups": [{"IpPermissions": []}]}
            raise AssertionError(f"Unexpected operation: {arguments}")

        self.control.cli.call = Mock(side_effect=response)
        result = self.control.observe()
        self.assertEqual(result["vpc_cidr"], "10.63.0.0/24")
        self.assertEqual(result["subnet_cidr"], "10.63.0.0/28")
        self.assertEqual(result["routes"], [{"destination": "10.63.0.0/24", "gateway": "local", "state": "active"}])
        raw = json.loads(self.control.observation_file.read_text(encoding="utf-8"))
        self.assertEqual(raw["vpc"]["Vpcs"][0]["CidrBlock"], MODULE.VPC_CIDR)
        self.assertEqual(raw["subnet"]["Subnets"][0]["CidrBlock"], MODULE.SUBNET_CIDR)

    def test_cidrs_and_wrapper_source_mapping(self) -> None:
        wrapper = (ROOT / "scripts" / "aws-control-plane.sh").read_text(encoding="utf-8")
        self.assertEqual(MODULE.VPC_CIDR, "10.63.0.0/24")
        self.assertEqual(MODULE.SUBNET_CIDR, "10.63.0.0/28")
        self.assertIn('PYTHON_SOURCE="${SCRIPT_DIR}/aws_control_plane.py"', wrapper)
        self.assertIn('exec python3 "${PYTHON_SOURCE}" "$@"', wrapper)


if __name__ == "__main__":
    unittest.main()
