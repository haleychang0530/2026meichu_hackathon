from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .errors import AppError
from .models import ErrorCode


ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class PreparedImage:
    path: Path
    media_type: str
    width: int
    height: int
    byte_count: int


class ImagePreparer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def prepare(self, upload: UploadFile) -> PreparedImage:
        declared_type = (upload.content_type or "").lower()
        if declared_type not in ALLOWED_MEDIA_TYPES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "image must be JPEG, PNG, or WebP",
                status_code=400,
                details={"field": "image", "allowed_media_types": sorted(ALLOWED_MEDIA_TYPES)},
            )

        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        raw_path = self._temporary_path(".upload")
        normalized_path = self._temporary_path(".jpg")
        try:
            total = 0
            with raw_path.open("wb") as destination:
                while chunk := await upload.read(CHUNK_SIZE):
                    total += len(chunk)
                    if total > self.settings.max_image_bytes:
                        raise AppError(
                            ErrorCode.VALIDATION_ERROR,
                            "image exceeds the configured byte limit",
                            status_code=400,
                            details={"max_image_bytes": self.settings.max_image_bytes},
                        )
                    destination.write(chunk)
            if total == 0:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "image is empty",
                    status_code=400,
                    details={"field": "image"},
                )

            width, height = self._validate_and_normalize(raw_path, normalized_path)
            return PreparedImage(
                path=normalized_path,
                media_type="image/jpeg",
                width=width,
                height=height,
                byte_count=normalized_path.stat().st_size,
            )
        except (UnidentifiedImageError, OSError) as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "image container is invalid or corrupt",
                status_code=400,
                details={"field": "image"},
            ) from exc
        finally:
            raw_path.unlink(missing_ok=True)
            if not normalized_path.exists() or normalized_path.stat().st_size == 0:
                normalized_path.unlink(missing_ok=True)

    def _validate_and_normalize(self, source: Path, destination: Path) -> tuple[int, int]:
        with Image.open(source) as probe:
            actual_format = probe.format
            width, height = probe.size
            if actual_format not in {"JPEG", "PNG", "WEBP"}:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "image content does not match an allowed format",
                    status_code=400,
                )
            if width <= 0 or height <= 0:
                raise AppError(ErrorCode.IMAGE_QUALITY_LOW, "image has invalid dimensions", status_code=400)
            if width > self.settings.max_image_dimension or height > self.settings.max_image_dimension:
                raise AppError(
                    ErrorCode.IMAGE_QUALITY_LOW,
                    "image dimensions exceed the configured limit",
                    status_code=400,
                    retryable=True,
                    details={"max_dimension": self.settings.max_image_dimension},
                )
            if width * height > self.settings.max_image_pixels:
                raise AppError(
                    ErrorCode.IMAGE_QUALITY_LOW,
                    "image pixel count exceeds the configured limit",
                    status_code=400,
                    retryable=True,
                    details={"max_image_pixels": self.settings.max_image_pixels},
                )
            probe.verify()

        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.load()
            if image.mode != "RGB":
                if image.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background
                else:
                    image = image.convert("RGB")
            image.thumbnail(
                (self.settings.normalized_image_dimension, self.settings.normalized_image_dimension),
                Image.Resampling.LANCZOS,
            )
            image.save(destination, format="JPEG", quality=88, optimize=True)
            return image.size

    def _temporary_path(self, suffix: str) -> Path:
        descriptor, value = tempfile.mkstemp(prefix="lesson-", suffix=suffix, dir=self.settings.upload_dir)
        os.close(descriptor)
        return Path(value)

    def cleanup_stale(self) -> int:
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - self.settings.upload_ttl_seconds
        removed = 0
        for path in self.settings.upload_dir.glob("lesson-*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed
