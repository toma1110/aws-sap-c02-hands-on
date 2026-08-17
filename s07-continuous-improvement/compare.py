#!/usr/bin/env python3
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


before = json.load(open(sys.argv[1], encoding="utf-8"))
after = json.load(open(sys.argv[2], encoding="utf-8"))

if before.get("phase") != "before" or after.get("phase") != "after":
    raise SystemExit("phaseはbefore、afterの順で指定してください")
if before.get("function_name") != after.get("function_name") or before.get("region") != after.get("region"):
    raise SystemExit("beforeとafterの対象関数またはRegionが一致しません")
if before["fixed_conditions"] != after["fixed_conditions"]:
    raise SystemExit("固定条件が一致しません")


def validate_phase(data):
    samples = data.get("samples", [])
    expected_count = data["fixed_conditions"]["samples"]
    expected_iterations = data["fixed_conditions"]["iterations"]
    if len(samples) != expected_count:
        raise SystemExit(f"{data['phase']}のsample数が固定条件と一致しません")
    checksums = {sample.get("checksum") for sample in samples}
    iterations = {sample.get("iterations") for sample in samples}
    memory_sizes = {sample.get("memory_mb") for sample in samples}
    if iterations != {expected_iterations}:
        raise SystemExit(f"{data['phase']}のiterationsがsample内で一致しません")
    if len(checksums) != 1 or None in checksums or data["summary"].get("checksum") not in checksums:
        raise SystemExit(f"{data['phase']}のchecksumがsample内で一致しません")
    if len(memory_sizes) != 1 or data["summary"].get("memory_mb") not in memory_sizes:
        raise SystemExit(f"{data['phase']}のmemoryがsample内で一致しません")
    return checksums.pop(), memory_sizes.pop()


before_checksum, before_memory = validate_phase(before)
after_checksum, after_memory = validate_phase(after)
if before_checksum != after_checksum:
    raise SystemExit("処理結果のchecksumが一致しません")
if (before_memory, after_memory) != (128, 512):
    raise SystemExit("比較対象のmemory変更が128 MBから512 MBではありません")

b = before["summary"]
a = after["summary"]
comparison = {
    "fixed_conditions_match": True,
    "result_checksum_match": True,
    "change": "Lambda memory 128 MB -> 512 MB",
    "median_duration_ms": {"before": b["median_duration_ms"], "after": a["median_duration_ms"]},
    "latency_improvement_percent": round((1 - a["median_duration_ms"] / b["median_duration_ms"]) * 100, 1),
    "median_cost_proxy_mb_ms": {"before": b["median_cost_proxy_mb_ms"], "after": a["median_cost_proxy_mb_ms"]},
    "cost_proxy_change_percent": round((a["median_cost_proxy_mb_ms"] / b["median_cost_proxy_mb_ms"] - 1) * 100, 1),
    "side_effect_to_check": "メモリ増加で応答時間は短縮しても、GB秒相当の費用が増える場合がある",
}
print(json.dumps(comparison, ensure_ascii=False, indent=2))
