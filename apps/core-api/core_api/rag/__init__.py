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
from .retrieval import EvidenceCitation, HybridRetrievalConfig, HybridRetriever, RetrievalBundle

__all__ = [
    "BuildReport",
    "EmbeddingError",
    "EvidenceCitation",
    "HashingCharNgramEmbedding",
    "HybridRetrievalConfig",
    "HybridRetriever",
    "IngestReport",
    "OnnxEmbedding",
    "RagChunk",
    "RagIndexBuilder",
    "RagIndexManager",
    "RagManifest",
    "RagSource",
    "RetrievalResult",
    "RetrievalBundle",
    "SourceContentError",
    "create_embedding_backend",
    "ingest_manifest",
    "load_manifest",
]
