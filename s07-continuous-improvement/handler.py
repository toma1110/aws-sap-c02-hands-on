import hashlib
import time


def lambda_handler(event, context):
    iterations = int(event.get("iterations", 250_000))
    value = b"sap-c02-continuous-improvement"
    started = time.perf_counter()
    for _ in range(iterations):
        value = hashlib.sha256(value).digest()
    return {
        "iterations": iterations,
        "checksum": value.hex(),
        "work_duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "memory_mb": context.memory_limit_in_mb,
    }
