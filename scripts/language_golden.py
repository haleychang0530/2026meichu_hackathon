"""Validate and report the Stage 06 Hanji/Tailo/POJ golden set."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_APP = ROOT / "apps" / "core-api"
if str(CORE_APP) not in sys.path:
    sys.path.insert(0, str(CORE_APP))

from core_api.language import (  # noqa: E402
    GOLDEN_LEXICON_VERSION,
    MMS_POJ_PROFILE_VERSION,
    NORMALIZER_VERSION,
    RULESET_VERSION,
    LanguageNormalizer,
    tailo_to_mms_poj,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    path = ROOT / "data" / "language" / "normalization-golden.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    normalizer = LanguageNormalizer(path)
    rows = []
    failures = []
    for entry in document["entries"]:
        poj, unknown = tailo_to_mms_poj(entry["tailo"])
        passed = poj == entry["poj"] and not unknown
        rows.append({
            "id": entry["id"],
            "input": {"hanji": entry["hanji"], "tailo": entry["tailo"]},
            "output": {"poj": poj, "unknown_characters": list(unknown)},
            "expected": {"poj": entry["poj"], "status": entry["status"]},
            "passed": passed,
        })
        if not passed:
            failures.append(entry["id"])
    report = {
        "passed": not failures,
        "entry_count": len(normalizer.entries),
        "failures": failures,
        "tools": {
            "pipeline": NORMALIZER_VERSION,
            "lexicon": GOLDEN_LEXICON_VERSION,
            "tailo_to_poj": RULESET_VERSION,
            "mms_vocab": MMS_POJ_PROFILE_VERSION,
        },
        "rows": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] and report["entry_count"] >= 30 else 1


if __name__ == "__main__":
    raise SystemExit(main())
