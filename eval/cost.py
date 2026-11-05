"""Cost benchmark: anonymization and encryption latency + client memory (4.5).

Declares hardware. Runs with the regex-only detector (no model needed).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

from eval import common
from src import secure


def _cpu_name() -> str:
    """Nombre legible de la CPU (en Linux, `platform.processor()` suele dar
    solo la arquitectura)."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def load_sample(corpus: Path, n: int) -> list[str]:
    texts = []
    for ann in sorted((corpus / "dev" / "brat").glob("*.ann")):
        txt = ann.with_suffix(".txt")
        if txt.exists():
            texts.append(common.read_text(txt))
            if len(texts) >= n:
                break
    return texts


def measure_anonymization(texts, predictor, repeats=3):
    latencies = []
    for _ in range(repeats):
        for text in texts:
            predictor.anonymize(text)
            t0 = time.perf_counter()
            predictor.anonymize(text)
            latencies.append(time.perf_counter() - t0)
    latencies.sort()
    return latencies


def measure_encryption(secret_bytes, sizes=(64, 1024, 4096, 16384), repeats=200):
    rows = []
    for size in sizes:
        payload = b"x" * size
        lat = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            env = secure.encrypt_request(secret_bytes, payload)
            secure.decrypt_request(secret_bytes, env)
            lat.append(time.perf_counter() - t0)
        lat.sort()
        rows.append({
            "size_bytes": size,
            "p50_ms": round(statistics.median(lat) * 1000, 4),
            "p95_ms": round(lat[int(0.95 * (len(lat) - 1))] * 1000, 4),
        })
    return rows


def measure_memory(texts, predictor):
    tracemalloc.start()
    for text in texts:
        predictor.anonymize(text)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def main() -> int:
    parser = argparse.ArgumentParser(description="Cost benchmark")
    parser.add_argument("--corpus", default="data/meddocan/corpus")
    parser.add_argument("--sample", type=int, default=100)
    parser.add_argument("--mode", choices=["regex", "bert", "combined"],
                        default="combined")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--out", default="eval/results/cost.json")
    args = parser.parse_args()

    texts = load_sample(Path(args.corpus), args.sample)
    if not texts:
        print("[cost] No hay documentos para medir", file=sys.stderr)
        return 2

    predictor = common.Predictor(args.mode, args.model_dir)
    anon_lat = measure_anonymization(texts, predictor)
    secret_bytes = secure.load_secret(secure.generate_secret())
    enc_rows = measure_encryption(secret_bytes)
    peak_mem = measure_memory(texts, predictor)

    result = {
        "script": "eval/cost.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": _git(),
        "environment": common.environment(),
        "dirty": common.dirty(),
        "mode": args.mode,
        "hardware": {
            "cpu": _cpu_name(),
            "logical_cpus": os.cpu_count(),
            "platform": platform.platform(),
        },
        "anonymization_latency_ms": {
            "documents": len(texts),
            "p50": round(statistics.median(anon_lat) * 1000, 4),
            "p95": round(anon_lat[int(0.95 * (len(anon_lat) - 1))] * 1000, 4),
        },
        "encryption_ms": enc_rows,
        "client_peak_memory_bytes": peak_mem,
        "notes": [
            "Anonymization latency measured over the full pipeline "
            "(BERT + regex when mode=combined) on CPU.",
            "Peak memory is tracemalloc (Python allocations only); it does not "
            "include the ~473 MB of BERT weights held by torch.",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(
        f"[cost] anon p50={result['anonymization_latency_ms']['p50']:.3f} ms, "
        f"peak_mem={peak_mem} B"
    )
    return 0


def _git():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
