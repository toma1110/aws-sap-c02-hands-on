#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import statistics
import subprocess
import tempfile


REPORT = re.compile(
    r"Duration: ([0-9.]+) ms.*Billed Duration: ([0-9]+) ms.*Memory Size: ([0-9]+) MB.*Max Memory Used: ([0-9]+) MB"
)


def invoke(function_name, region, iterations):
    response_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    response_file.close()
    try:
        command = [
            "aws", "lambda", "invoke", "--region", region,
            "--function-name", function_name, "--log-type", "Tail",
            "--cli-binary-format", "raw-in-base64-out",
            "--payload", json.dumps({"iterations": iterations}),
            "--output", "json", response_file.name,
        ]
        metadata = json.loads(subprocess.check_output(command, text=True))
        with open(response_file.name, encoding="utf-8") as stream:
            response = json.load(stream)
    finally:
        try:
            os.unlink(response_file.name)
        except FileNotFoundError:
            pass
    log = base64.b64decode(metadata["LogResult"]).decode("utf-8", errors="replace")
    match = REPORT.search(log.replace("\n", " "))
    if not match:
        raise RuntimeError("Lambda REPORT行を解析できませんでした")
    duration, billed, memory, max_memory = match.groups()
    return {
        "duration_ms": float(duration),
        "billed_duration_ms": int(billed),
        "memory_mb": int(memory),
        "max_memory_used_mb": int(max_memory),
        "work_duration_ms": response["work_duration_ms"],
        "iterations": response["iterations"],
        "checksum": response["checksum"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["before", "after"])
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--iterations", type=int, default=250_000)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    invoke(args.function_name, args.region, args.iterations)  # warm-up; excluded
    samples = [invoke(args.function_name, args.region, args.iterations) for _ in range(args.samples)]
    result = {
        "phase": args.phase,
        "region": args.region,
        "function_name": args.function_name,
        "fixed_conditions": {"iterations": args.iterations, "samples": args.samples, "warmup_excluded": 1},
        "samples": samples,
        "summary": {
            "median_duration_ms": statistics.median(x["duration_ms"] for x in samples),
            "median_billed_duration_ms": statistics.median(x["billed_duration_ms"] for x in samples),
            "memory_mb": samples[0]["memory_mb"],
            "max_memory_used_mb": max(x["max_memory_used_mb"] for x in samples),
            "median_cost_proxy_mb_ms": statistics.median(x["memory_mb"] * x["billed_duration_ms"] for x in samples),
            "checksum": samples[0]["checksum"],
        },
    }
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
