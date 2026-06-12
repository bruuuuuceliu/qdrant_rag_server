"""Manager service domain errors."""

from __future__ import annotations


class ManagerServiceError(RuntimeError):
    """Base error for manager-owned orchestration failures."""


class ManagerIngestFailedError(ManagerServiceError):
    """Raised when the ingestion service rejects or fails a queued request."""

    def __init__(self, message: str, *, request_id: str) -> None:
        super().__init__(message)
        self.request_id = request_id


class ManagerIngestTimeoutError(TimeoutError, ManagerServiceError):
    """Raised when an ingestion service response is not received in time."""

    def __init__(self, *, request_id: str, timeout: float) -> None:
        super().__init__(
            f"timed out waiting {timeout:g}s for ingest response {request_id}"
        )
        self.request_id = request_id
        self.timeout = timeout
