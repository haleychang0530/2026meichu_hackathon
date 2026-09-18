from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol, Sequence


class EmbeddingError(RuntimeError):
    """Raised when an optional embedding backend cannot be initialized."""


class EmbeddingBackend(Protocol):
    name: str
    dimension: int

    def embed(self, text: str) -> tuple[float, ...]:
        ...

    def embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        ...


def normalize_for_embedding(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes, dimension: int) -> tuple[float, ...]:
    expected_size = dimension * struct.calcsize("f")
    if len(blob) != expected_size:
        raise EmbeddingError(f"stored vector has {len(blob)} bytes; expected {expected_size}")
    return struct.unpack(f"<{dimension}f", blob)


def _hash_feature(feature: str, dimension: int) -> tuple[int, int]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8, person=b"hol-rag-v1").digest()
    bucket = int.from_bytes(digest[:4], "little") % dimension
    sign = -1 if digest[4] & 1 else 1
    return bucket, sign


def _feature_stream(text: str) -> Iterable[tuple[str, float]]:
    normalized = normalize_for_embedding(text)
    if not normalized:
        return
    for token in re.findall(r"[^\W_]+(?:[-'’][^\W_]+)*", normalized, flags=re.UNICODE):
        yield f"word:{token}", 2.0
    compact = re.sub(r"\s+", "▁", normalized)
    for start in range(len(compact)):
        if compact[start] == "▁":
            continue
        for length in (1, 2, 3, 4):
            end = start + length
            if end > len(compact):
                break
            gram = compact[start:end]
            if "▁" in gram and length > 1:
                continue
            yield f"gram:{length}:{gram}", 0.75 + length * 0.2


@dataclass(frozen=True, slots=True)
class HashingCharNgramEmbedding:
    """Dependency-free multilingual CPU embedding.

    Unicode code-point n-grams keep Hanji and Latin/diacritic-heavy 臺羅
    text in one feature space. The backend is intentionally deterministic so
    an index can be rebuilt offline without downloading a model.
    """

    dimension: int = 256
    revision: str = "hashing-char-ngram-v1"

    @property
    def name(self) -> str:
        return f"{self.revision}:{self.dimension}d"

    def embed(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self.dimension
        for feature, weight in _feature_stream(text):
            bucket, sign = _hash_feature(feature, self.dimension)
            values[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return tuple(values)
        return tuple(value / norm for value in values)

    def embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [self.embed(text) for text in texts]


@dataclass(slots=True)
class OnnxEmbedding:
    """Optional CPU ONNX backend for a tokenizer.json + sentence encoder.

    The repository does not download or commit a model. This adapter is used
    only when the operator supplies an approved local model and installs
    ``onnxruntime``, ``numpy`` and ``tokenizers`` in the laptop environment.
    """

    model_path: Path
    tokenizer_path: Path
    revision: str = "onnx-local"
    _np: object = field(init=False, repr=False)
    _session: object = field(init=False, repr=False)
    _tokenizer: object = field(init=False, repr=False)
    dimension: int = field(init=False)
    name: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover - depends on local model setup
            raise EmbeddingError(
                "ONNX backend requires numpy, onnxruntime, and tokenizers; "
                "use the dependency-free hashing backend when unavailable"
            ) from exc
        if not self.model_path.is_file() or not self.tokenizer_path.is_file():
            raise EmbeddingError("ONNX model and tokenizer paths must point to existing files")
        object.__setattr__(self, "_np", np)
        object.__setattr__(self, "_session", ort.InferenceSession(
            str(self.model_path), providers=["CPUExecutionProvider"]
        ))
        object.__setattr__(self, "_tokenizer", Tokenizer.from_file(str(self.tokenizer_path)))
        object.__setattr__(self, "dimension", self._detect_dimension())
        object.__setattr__(self, "name", f"{self.revision}:{self.model_path.name}:{self.dimension}d")

    def _detect_dimension(self) -> int:
        probe = self._run("Taiwan", include_shape_only=True)
        return len(probe)

    def _run(self, text: str, *, include_shape_only: bool = False) -> tuple[float, ...]:
        encoding = self._tokenizer.encode(text)
        np = self._np
        input_ids = np.asarray([encoding.ids], dtype=np.int64)
        attention = np.asarray([encoding.attention_mask], dtype=np.int64)
        type_ids = np.asarray([encoding.type_ids], dtype=np.int64)
        inputs: dict[str, object] = {}
        for item in self._session.get_inputs():
            if item.name == "input_ids":
                inputs[item.name] = input_ids
            elif item.name == "attention_mask":
                inputs[item.name] = attention
            elif item.name == "token_type_ids":
                inputs[item.name] = type_ids
            else:
                raise EmbeddingError(f"unsupported ONNX input: {item.name}")
        output = self._session.run(None, inputs)[0]
        if output.ndim == 3:
            mask = attention.astype(np.float32)[..., None]
            vector = (output * mask).sum(axis=1)[0] / max(float(mask.sum()), 1.0)
        elif output.ndim == 2:
            vector = output[0]
        else:
            raise EmbeddingError(f"unsupported ONNX output rank: {output.ndim}")
        values = [float(value) for value in vector]
        norm = math.sqrt(sum(value * value for value in values))
        return tuple(value / norm for value in values) if norm else tuple(values)

    def embed(self, text: str) -> tuple[float, ...]:
        return self._run(text)

    def embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [self.embed(text) for text in texts]


def create_embedding_backend(
    backend: str = "hashing-char-ngram-v1",
    *,
    dimension: int = 256,
    onnx_model_path: Path | None = None,
    onnx_tokenizer_path: Path | None = None,
) -> EmbeddingBackend:
    if backend == "hashing-char-ngram-v1":
        if dimension < 32:
            raise EmbeddingError("hashing embedding dimension must be at least 32")
        return HashingCharNgramEmbedding(dimension=dimension)
    if backend == "onnx-local":
        if onnx_model_path is None or onnx_tokenizer_path is None:
            raise EmbeddingError("onnx-local requires RAG_ONNX_MODEL_PATH and RAG_ONNX_TOKENIZER_PATH")
        return OnnxEmbedding(onnx_model_path, onnx_tokenizer_path)
    raise EmbeddingError(f"unknown embedding backend: {backend}")
