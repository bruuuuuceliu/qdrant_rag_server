"""Lightweight content-type and filename detection."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import urlparse


def source_extension(source_uri: str, filename: str = "") -> str:
    name = filename or urlparse(source_uri).path or source_uri
    return Path(name).suffix.lower()


def normalize_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def detect_content_type(
    *,
    declared_content_type: str,
    source_uri: str,
    filename: str = "",
    content: bytes = b"",
) -> str:
    declared = normalize_content_type(declared_content_type)
    if declared and declared not in {"application/octet-stream", "binary/octet-stream"}:
        return declared
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"PK\x03\x04"):
        ext = source_extension(source_uri, filename)
        if ext == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if ext == ".pptx":
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        if ext in {".xlsx", ".xlsm"}:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    guessed, _ = mimetypes.guess_type(filename or source_uri)
    return normalize_content_type(guessed or declared or "text/plain")
