#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


NAME = "sapc02-s03-network-diag"
COURSE_TAG = "SAP-C02"
VPC_CIDR = "10.63.0.0/24"
SUBNET_CIDR = "10.63.0.0/28"


class SafetyError(RuntimeError):
    pass


class AwsCli:
    def __init__(self, region: str) -> None:
        self.region = region

    def call(self, *arguments: str) -> dict[str, Any]:
        command = ["aws", *arguments, "--region", self.region, "--output", "json"]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise SafetyError(result.stderr.strip() or f"AWS CLI failed: {' '.join(command)}")
        return json.loads(result.stdout) if result.stdout.strip() else {}


class ControlPlane:
    def __init__(self, root: Path, region: str, expected_account_id: str, cli: AwsCli) -> None:
        self.root = root
        self.region = region
        self.expected_account_id = expected_account_id
        self.cli = cli
        self.state_dir = root / ".s03-state"
        self.state_file = self.state_dir / "aws-state.json"
        self.observation_file = self.state_dir / "aws-observation.json"

    def identity_account(self) -> str:
        account = self.cli.call("sts", "get-caller-identity").get("Account")
        if not isinstance(account, str) or not account:
            raise SafetyError("AWS account ID could not be read")
        if not self.expected_account_id:
            raise SafetyError("EXPECTED_ACCOUNT_ID is required")
        if account != self.expected_account_id:
            raise SafetyError(f"Account mismatch: expected {self.expected_account_id}, actual {account}")
        return account

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.state_file)

    def load_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SafetyError("Valid state file is required") from exc
        required = {
            "schema_version",
            "name",
            "account_id",
            "region",
            "vpc_id",
            "subnet_ids",
            "route_table_id",
            "association_id",
            "security_group_id",
        }
        if set(state) != required or state["schema_version"] != 1 or state["name"] != NAME:
            raise SafetyError("State schema or resource name mismatch")
        if state["account_id"] != self.identity_account():
            raise SafetyError("State account does not match current account")
        if state["region"] != self.region:
            raise SafetyError("State Region does not match command Region")
        if not isinstance(state["subnet_ids"], list) or len(state["subnet_ids"]) > 1:
            raise SafetyError("State subnet scope is invalid")
        for key in ("vpc_id", "route_table_id", "association_id", "security_group_id"):
            if state[key] is not None and not isinstance(state[key], str):
                raise SafetyError(f"State {key} type is invalid")
        if any(not isinstance(item, str) for item in state["subnet_ids"]):
            raise SafetyError("State subnet ID type is invalid")
        return state

    @staticmethod
    def tags(resource: dict[str, Any]) -> dict[str, str]:
        return {tag.get("Key", ""): tag.get("Value", "") for tag in resource.get("Tags", [])}

    def _one(self, operation: str, collection: str, filter_name: str, resource_id: str) -> dict[str, Any] | None:
        response = self.cli.call("ec2", operation, "--filters", f"Name={filter_name},Values={resource_id}")
        items = response.get(collection, [])
        if not isinstance(items, list) or len(items) > 1:
            raise SafetyError(f"Unexpected {collection} response cardinality")
        return items[0] if items else None

    def validate_current_resources(self, state: dict[str, Any]) -> dict[str, bool]:
        present = {"association": False, "route_table": False, "security_group": False, "subnet": False, "vpc": False}
        vpc_id = state["vpc_id"]
        vpc = self._one("describe-vpcs", "Vpcs", "vpc-id", vpc_id) if vpc_id else None
        if vpc:
            if vpc.get("CidrBlock") != VPC_CIDR or self.tags(vpc).get("Name") != NAME or self.tags(vpc).get("Course") != COURSE_TAG:
                raise SafetyError("VPC ownership or CIDR validation failed")
            present["vpc"] = True

        subnet_id = state["subnet_ids"][0] if state["subnet_ids"] else None
        subnet = self._one("describe-subnets", "Subnets", "subnet-id", subnet_id) if subnet_id else None
        if subnet:
            if subnet.get("VpcId") != vpc_id or subnet.get("CidrBlock") != SUBNET_CIDR or self.tags(subnet).get("Name") != f"{NAME}-a" or self.tags(subnet).get("Course") != COURSE_TAG:
                raise SafetyError("Subnet ownership, parent, or CIDR validation failed")
            present["subnet"] = True

        route_id = state["route_table_id"]
        route = self._one("describe-route-tables", "RouteTables", "route-table-id", route_id) if route_id else None
        if route:
            if route.get("VpcId") != vpc_id or self.tags(route).get("Name") != NAME or self.tags(route).get("Course") != COURSE_TAG:
                raise SafetyError("Route table ownership or parent validation failed")
            if any(item.get("Main") is True for item in route.get("Associations", [])):
                raise SafetyError("Refusing to delete a main route table")
            present["route_table"] = True
            association_id = state["association_id"]
            matches = [item for item in route.get("Associations", []) if item.get("RouteTableAssociationId") == association_id]
            if len(matches) > 1:
                raise SafetyError("Route association cardinality is invalid")
            if matches:
                if matches[0].get("SubnetId") != subnet_id:
                    raise SafetyError("Route association target validation failed")
                present["association"] = True

        group_id = state["security_group_id"]
        group = self._one("describe-security-groups", "SecurityGroups", "group-id", group_id) if group_id else None
        if group:
            if group.get("VpcId") != vpc_id or group.get("GroupName") != NAME or self.tags(group).get("Name") != NAME or self.tags(group).get("Course") != COURSE_TAG:
                raise SafetyError("Security group ownership or parent validation failed")
            present["security_group"] = True
        return present

    def precreate_collisions(self) -> list[dict[str, str]]:
        checks = (
            ("vpc", "describe-vpcs", "Vpcs", "VpcId", NAME),
            ("subnet", "describe-subnets", "Subnets", "SubnetId", f"{NAME}-a"),
            ("route-table", "describe-route-tables", "RouteTables", "RouteTableId", NAME),
            ("security-group", "describe-security-groups", "SecurityGroups", "GroupId", NAME),
        )
        collisions: list[dict[str, str]] = []
        for kind, operation, collection, id_key, expected_name in checks:
            response = self.cli.call(
                "ec2",
                operation,
                "--filters",
                f"Name=tag:Name,Values={expected_name}",
                f"Name=tag:Course,Values={COURSE_TAG}",
            )
            items = response.get(collection, [])
            if not isinstance(items, list):
                raise SafetyError(f"Unexpected {collection} response type")
            collisions.extend({"type": kind, "id": str(item.get(id_key, "unknown"))} for item in items)
        return collisions

    def create(self) -> dict[str, Any]:
        account_id = self.identity_account()
        if self.state_file.exists():
            raise SafetyError("State already exists; refusing duplicate creation")
        collisions = self.precreate_collisions()
        if collisions:
            raise SafetyError(f"Tagged resource collision; cleanup exact existing resources first: {collisions}")
        state = {
            "schema_version": 1,
            "name": NAME,
            "account_id": account_id,
            "region": self.region,
            "vpc_id": None,
            "subnet_ids": [],
            "route_table_id": None,
            "association_id": None,
            "security_group_id": None,
        }
        tags = f"ResourceType=vpc,Tags=[{{Key=Name,Value={NAME}}},{{Key=Course,Value={COURSE_TAG}}}]"
        state["vpc_id"] = self.cli.call("ec2", "create-vpc", "--cidr-block", VPC_CIDR, "--tag-specifications", tags)["Vpc"]["VpcId"]
        self.save_state(state)
        vpc_id = state["vpc_id"]
        self.cli.call("ec2", "wait", "vpc-available", "--vpc-ids", vpc_id)
        self.cli.call("ec2", "modify-vpc-attribute", "--vpc-id", vpc_id, "--enable-dns-support", '{"Value":true}')
        self.cli.call("ec2", "modify-vpc-attribute", "--vpc-id", vpc_id, "--enable-dns-hostnames", '{"Value":true}')
        zones = self.cli.call("ec2", "describe-availability-zones", "--filters", "Name=state,Values=available").get("AvailabilityZones", [])
        if not zones:
            raise SafetyError("No available Availability Zone found")
        subnet_tags = f"ResourceType=subnet,Tags=[{{Key=Name,Value={NAME}-a}},{{Key=Course,Value={COURSE_TAG}}}]"
        subnet_id = self.cli.call("ec2", "create-subnet", "--vpc-id", vpc_id, "--availability-zone", zones[0]["ZoneName"], "--cidr-block", SUBNET_CIDR, "--tag-specifications", subnet_tags)["Subnet"]["SubnetId"]
        state["subnet_ids"] = [subnet_id]
        self.save_state(state)
        route_tags = f"ResourceType=route-table,Tags=[{{Key=Name,Value={NAME}}},{{Key=Course,Value={COURSE_TAG}}}]"
        state["route_table_id"] = self.cli.call("ec2", "create-route-table", "--vpc-id", vpc_id, "--tag-specifications", route_tags)["RouteTable"]["RouteTableId"]
        self.save_state(state)
        state["association_id"] = self.cli.call("ec2", "associate-route-table", "--route-table-id", state["route_table_id"], "--subnet-id", subnet_id)["AssociationId"]
        self.save_state(state)
        group_tags = f"ResourceType=security-group,Tags=[{{Key=Name,Value={NAME}}},{{Key=Course,Value={COURSE_TAG}}}]"
        state["security_group_id"] = self.cli.call("ec2", "create-security-group", "--vpc-id", vpc_id, "--group-name", NAME, "--description", "SAP-C02 network diagnostics control-plane observation", "--tag-specifications", group_tags)["GroupId"]
        self.save_state(state)
        return state

    def observe(self) -> dict[str, Any]:
        state = self.load_state()
        present = self.validate_current_resources(state)
        if not all(present.values()):
            raise SafetyError("All scoped resources must exist before observation")
        vpc_id = state["vpc_id"]
        observation = {
            "schema_version": 1,
            "boundary": "control-plane configuration only; no packet or DNS query executed",
            "vpc": self.cli.call("ec2", "describe-vpcs", "--vpc-ids", vpc_id),
            "dns_support": self.cli.call("ec2", "describe-vpc-attribute", "--vpc-id", vpc_id, "--attribute", "enableDnsSupport"),
            "dns_hostnames": self.cli.call("ec2", "describe-vpc-attribute", "--vpc-id", vpc_id, "--attribute", "enableDnsHostnames"),
            "subnet": self.cli.call("ec2", "describe-subnets", "--subnet-ids", state["subnet_ids"][0]),
            "route_table": self.cli.call("ec2", "describe-route-tables", "--route-table-ids", state["route_table_id"]),
            "security_group": self.cli.call("ec2", "describe-security-groups", "--group-ids", state["security_group_id"]),
        }
        self.observation_file.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        route = observation["route_table"]["RouteTables"][0]
        group = observation["security_group"]["SecurityGroups"][0]
        return {
            "boundary": observation["boundary"],
            "vpc_cidr": observation["vpc"]["Vpcs"][0]["CidrBlock"],
            "subnet_cidr": observation["subnet"]["Subnets"][0]["CidrBlock"],
            "dns_support": observation["dns_support"]["EnableDnsSupport"]["Value"],
            "dns_hostnames": observation["dns_hostnames"]["EnableDnsHostnames"]["Value"],
            "routes": [{"destination": item.get("DestinationCidrBlock"), "gateway": item.get("GatewayId"), "state": item.get("State")} for item in route["Routes"]],
            "inbound_rule_count": len(group.get("IpPermissions", [])),
        }

    def cleanup(self) -> None:
        if not self.state_file.exists():
            raise SafetyError("State file is missing; cleanup target cannot be verified")
        state = self.load_state()
        present = self.validate_current_resources(state)
        if present["association"]:
            self.cli.call("ec2", "disassociate-route-table", "--association-id", state["association_id"])
        if present["route_table"]:
            self.cli.call("ec2", "delete-route-table", "--route-table-id", state["route_table_id"])
        if present["security_group"]:
            self.cli.call("ec2", "delete-security-group", "--group-id", state["security_group_id"])
        if present["subnet"]:
            self.cli.call("ec2", "delete-subnet", "--subnet-id", state["subnet_ids"][0])
        if present["vpc"]:
            self.cli.call("ec2", "delete-vpc", "--vpc-id", state["vpc_id"])

    def remaining(self, state: dict[str, Any]) -> list[dict[str, str]]:
        present = self.validate_current_resources(state)
        pairs = [
            ("route-table-association", state["association_id"], "association"),
            ("route-table", state["route_table_id"], "route_table"),
            ("security-group", state["security_group_id"], "security_group"),
            ("subnet", state["subnet_ids"][0] if state["subnet_ids"] else None, "subnet"),
            ("vpc", state["vpc_id"], "vpc"),
        ]
        return [{"type": kind, "id": resource_id} for kind, resource_id, key in pairs if resource_id and present[key]]

    def residual(self, attempts: int = 8, delay_seconds: float = 1.0) -> dict[str, Any]:
        if not self.state_file.exists():
            raise SafetyError("State file is missing; residual state cannot be verified")
        state = self.load_state()
        remaining: list[dict[str, str]] = []
        for attempt in range(attempts):
            remaining = self.remaining(state)
            if not remaining:
                shutil.rmtree(self.state_dir)
                return {"remaining": []}
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
        return {"remaining": remaining}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "observe", "cleanup", "residual"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    region = os.environ.get("AWS_REGION", "us-east-1")
    expected = os.environ.get("EXPECTED_ACCOUNT_ID", "")
    control = ControlPlane(root, region, expected, AwsCli(region))
    try:
        if args.action == "create":
            result: Any = {"created": control.create()}
        elif args.action == "observe":
            result = control.observe()
        elif args.action == "cleanup":
            control.cleanup()
            result = {"cleanup_requests_completed": True}
        else:
            result = control.residual()
            print(json.dumps(result, ensure_ascii=False))
            return 0 if not result["remaining"] else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SafetyError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
