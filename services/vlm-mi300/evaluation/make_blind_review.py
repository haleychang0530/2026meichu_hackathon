#!/usr/bin/env python3
"""Create anonymized model outputs and a human-review CSV for critical fields."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path


FIELDS = ["source_text", "vocabulary", "scene", "learning_objective", "accessible_activity"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260917)
    args = parser.parse_args()
    rows = []
    key = []
    for path in args.results:
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["warmup"] or record["run"] != 1:
                continue
            blind_id = hashlib.sha256(f"{record['model']}:{record['case_id']}".encode()).hexdigest()[:12]
            parsed = record.get("parsed_content") or {}
            rows.append({"blind_id": blind_id, "case_id": record["case_id"], **{f: parsed.get(f) for f in FIELDS}})
            key.append({"blind_id": blind_id, "model": record["model"], "case_id": record["case_id"]})
    random.Random(args.seed).shuffle(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "blind_outputs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "human_scores.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["blind_id", "case_id", "ocr_0_2", "tailo_0_2", "scene_0_2", "objective_0_2", "reconstruction_0_2", "answer_leak_0_1", "notes"])
        for row in rows:
            writer.writerow([row["blind_id"], row["case_id"], "", "", "", "", "", "", ""])


if __name__ == "__main__":
    main()
