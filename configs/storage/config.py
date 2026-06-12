"""Raw object storage configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.config import get_optional_value, get_value


CONFIG_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class ObjectStorageSettings:
    provider: str
    filesystem_path: str | None
    s3_endpoint_url: str | None
    s3_bucket: str | None
    s3_region: str


def load_storage_settings(values: dict[str, str]) -> ObjectStorageSettings:
    return ObjectStorageSettings(
        provider=get_value(values, "RAG_OBJECT_STORAGE_PROVIDER", "memory"),
        filesystem_path=get_optional_value(values, "RAG_OBJECT_STORAGE_PATH"),
        s3_endpoint_url=get_optional_value(values, "RAG_S3_ENDPOINT_URL"),
        s3_bucket=get_optional_value(values, "RAG_S3_BUCKET"),
        s3_region=get_value(values, "RAG_S3_REGION", "auto"),
    )
