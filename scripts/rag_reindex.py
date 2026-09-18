from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "apps" / "core-api"))

from core_api.config import Settings  # noqa: E402
from core_api.rag import RagIndexBuilder, create_embedding_backend  # noqa: E402


def _resolve(value: str | None, default: Path) -> Path:
    if not value:
        return default
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else (REPOSITORY_ROOT / candidate).resolve()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build the laptop-only persistent Hear Our Language RAG index")
    parser.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    parser.add_argument("--manifest", help="manifest path; defaults to RAG_MANIFEST_PATH")
    parser.add_argument("--index-root", help="runtime index root; defaults to RAG_INDEX_ROOT or LOCALAPPDATA")
    parser.add_argument("--embedding-backend", choices=("hashing-char-ngram-v1", "onnx-local"))
    parser.add_argument("--dimension", type=int, help="hashing embedding dimension")
    parser.add_argument("--no-switch", action="store_true", help="build the revision without changing active.json")
    args = parser.parse_args()

    settings = Settings.from_env("test")
    manifest = _resolve(args.manifest, REPOSITORY_ROOT / settings.rag_manifest_path)
    index_root = _resolve(args.index_root, settings.rag_index_root)
    backend_name = args.embedding_backend or settings.rag_embedding_backend
    dimension = args.dimension or settings.rag_embedding_dimension
    backend = create_embedding_backend(
        backend_name,
        dimension=dimension,
        onnx_model_path=settings.rag_onnx_model_path,
        onnx_tokenizer_path=settings.rag_onnx_tokenizer_path,
    )
    builder = RagIndexBuilder(
        manifest_path=manifest,
        content_root=REPOSITORY_ROOT,
        index_root=index_root,
        backend=backend,
    )
    report = builder.build(mode=args.mode, switch=not args.no_switch)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
