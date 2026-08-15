#!/usr/bin/env python3
"""Diagnose a versioned synthetic network observation without AWS writes."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_STAGES = ("route", "dns", "security", "reachability")


class InvalidInput(ValueError):
    pass


def load_scenario(path: Path, scenario_name: str) -> tuple[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise InvalidInput("schema_version must be 1")
    dataset_version = payload.get("dataset_version")
    if not isinstance(dataset_version, str) or not dataset_version:
        raise InvalidInput("dataset_version is required")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict) or scenario_name not in scenarios:
        raise InvalidInput(f"unknown scenario: {scenario_name}")
    observation = scenarios[scenario_name]
    if not isinstance(observation, dict):
        raise InvalidInput("scenario must be an object")
    for stage in REQUIRED_STAGES:
        stage_value = observation.get(stage)
        if not isinstance(stage_value, dict) or not isinstance(stage_value.get("passed"), bool):
            raise InvalidInput(f"{stage}.passed must be boolean")
        if not isinstance(stage_value.get("evidence"), str) or not stage_value["evidence"]:
            raise InvalidInput(f"{stage}.evidence is required")
    return dataset_version, observation


def diagnose(dataset_version: str, scenario_name: str, observation: dict[str, Any]) -> dict[str, Any]:
    checked: list[str] = []
    evidence: list[dict[str, Any]] = []
    for stage in REQUIRED_STAGES:
        checked.append(stage)
        stage_value = observation[stage]
        evidence.append({"stage": stage, "passed": stage_value["passed"], "detail": stage_value["evidence"]})
        if not stage_value["passed"]:
            return {
                "dataset_version": dataset_version,
                "scenario": scenario_name,
                "decision": stage.upper(),
                "checked_stages": checked,
                "evidence": evidence,
            }
    return {
        "dataset_version": dataset_version,
        "scenario": scenario_name,
        "decision": "HEALTHY",
        "checked_stages": checked,
        "evidence": evidence,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(json.dumps({"decision": "INVALID_INPUT", "error": "usage: diagnose.py FIXTURE SCENARIO"}, ensure_ascii=False))
        return 2
    try:
        dataset_version, observation = load_scenario(Path(argv[1]), argv[2])
        result = diagnose(dataset_version, argv[2], observation)
    except (OSError, json.JSONDecodeError, InvalidInput) as error:
        print(json.dumps({"decision": "INVALID_INPUT", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
