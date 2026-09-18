#!/usr/bin/env python3
"""Minimal laptop-side client for the stateless MI300 gateway.

The client sends one image and prompt per request.  It does not keep a
conversation on MI300; callers that need multiple turns must resend the
messages/evidence they intentionally want to use.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


DEFAULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8100/internal/vlm/generate")
    parser.add_argument("--prompt", required=True)
    parser.add_argument(
        "--model-revision",
        default="d9748a51ae66354c4dad665aab2c71f26cf2c8cd",
    )
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    media_type, _ = mimetypes.guess_type(args.image.name)
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        parser.error("image must have a .jpg/.jpeg/.png/.webp extension")
    content = base64.b64encode(args.image.read_bytes()).decode("ascii")
    schema = json.loads(args.schema.read_text(encoding="utf-8")) if args.schema else DEFAULT_SCHEMA
    request_id = str(uuid.uuid4())
    payload = {
        "schema_version": "0.1.0",
        "request_id": request_id,
        "image": {"media_type": media_type, "content_base64": content},
        "prompt": args.prompt,
        "response_schema": schema,
        "model_revision": args.model_revision,
    }
    request = urllib.request.Request(
        args.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Request-ID": request_id},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = response.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as error:
        print(error.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"transport error: {error.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
