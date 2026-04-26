#!/usr/bin/env python3
"""Measure local JSON file storage throughput and latency."""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import storage  # noqa: E402


def _percentile(values, percentile):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _record(operation, durations, total_seconds):
    count = len(durations)
    return {
        "operation": operation,
        "count": count,
        "throughput_per_second": count / total_seconds if total_seconds else 0.0,
        "avg_ms": (sum(durations) / count * 1000) if count else 0.0,
        "p95_ms": _percentile(durations, 0.95) * 1000,
    }


def run_baseline(count, payload_bytes, expires_in, data_dir):
    original_data_dir = storage.DATA_DIR
    storage.DATA_DIR = data_dir
    storage._last_cleanup_at = 0
    storage._last_cleanup_cursor = 0

    payload = "x" * payload_bytes
    message_ids = []
    write_durations = []
    read_durations = []

    try:
        write_started = time.perf_counter()
        for _ in range(count):
            started = time.perf_counter()
            msg_id = storage.save_message(payload, expires_in)
            write_durations.append(time.perf_counter() - started)
            message_ids.append(msg_id)
        write_total = time.perf_counter() - write_started

        read_started = time.perf_counter()
        for msg_id in message_ids:
            started = time.perf_counter()
            data = storage.pop_message(msg_id)
            read_durations.append(time.perf_counter() - started)
            if data is None:
                raise RuntimeError(f"message disappeared during baseline: {msg_id}")
        read_total = time.perf_counter() - read_started
    finally:
        storage.DATA_DIR = original_data_dir

    return {
        "message_count": count,
        "payload_bytes": payload_bytes,
        "data_dir": data_dir,
        "results": [
            _record("save_message", write_durations, write_total),
            _record("pop_message", read_durations, read_total),
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Measure file storage throughput and p95 latency."
    )
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--payload-bytes", type=int, default=1024)
    parser.add_argument("--expires-in", type=int, default=3600)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep generated files when --data-dir is provided.",
    )
    args = parser.parse_args()

    if args.count <= 0:
        parser.error("--count must be greater than 0")
    if args.payload_bytes < 0:
        parser.error("--payload-bytes must be 0 or greater")

    temp_dir = None
    if args.data_dir:
        data_dir = os.path.abspath(args.data_dir)
        os.makedirs(data_dir, exist_ok=True)
    else:
        temp_dir = tempfile.mkdtemp(prefix="openmessage-storage-baseline-")
        data_dir = temp_dir

    try:
        result = run_baseline(
            count=args.count,
            payload_bytes=args.payload_bytes,
            expires_in=args.expires_in,
            data_dir=data_dir,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir)
        elif args.data_dir and not args.keep_data:
            for name in os.listdir(data_dir):
                if name.endswith(".json") or ".json.lock-" in name:
                    os.remove(os.path.join(data_dir, name))


if __name__ == "__main__":
    main()
