"""Laptop-only Local RAG ingestion, indexing, and retrieval primitives."""

from .chunking import IngestReport, SourceContentError, ingest_manifest, load_manifest
from .embeddings import (
    EmbeddingError,
    HashingCharNgramEmbedding,
    OnnxEmbedding,
    create_embedding_backend,
)
from .index import BuildReport, RagIndexBuilder, RagIndexManager
from .models import RagChunk, RagManifest, RagSource, RetrievalResult

__all__ = [
    "BuildReport",
    "EmbeddingError",
    "HashingCharNgramEmbedding",
    "IngestReport",
    "OnnxEmbedding",
    "RagChunk",
    "RagIndexBuilder",
    "RagIndexManager",
    "RagManifest",
    "RagSource",
    "RetrievalResult",
    "SourceContentError",
    "create_embedding_backend",
    "ingest_manifest",
    "load_manifest",
]
