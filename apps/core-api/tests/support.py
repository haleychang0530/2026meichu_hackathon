from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "fixtures" / "contracts" / "v0.1" / "observer" / "success.lesson.json"


def jpeg_bytes(width: int = 64, height: int = 64) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="JPEG")
    return output.getvalue()


def lesson_payload(model_revision: str) -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["vlm_model_revision"] = model_revision
    payload["rag_index_revision"] = None
    return payload
