"""S3-compatible object storage using httpx (AWS S3, Cloudflare R2, MinIO).

Uses presigned-URL-style PUT/GET operations via the S3 REST API.
"""

from __future__ import annotations

import logging

from retrieval_service.storage.base import ObjectStorage, ObjectStorageError, _aws_sign

logger = logging.getLogger(__name__)


class S3ObjectStorage(ObjectStorage):
    """S3-compatible storage using httpx (AWS S3, Cloudflare R2, MinIO).

    Uses presigned-URL-style PUT/GET operations via the S3 REST API.
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "auto",
    ) -> None:
        self._endpoint = endpoint_url.rstrip("/")
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region

    async def put(self, key: str, content: bytes, content_type: str = "") -> None:
        import hmac
        import hashlib as hl
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        import httpx

        url = f"{self._endpoint}/{self._bucket}/{key}"

        payload_hash = hl.sha256(content).hexdigest()
        headers: dict[str, str] = {
            "Host": f"{self._endpoint.removeprefix('https://')}",
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            headers["Content-Type"] = content_type

        signed_headers = ";".join(sorted(h.lower() for h in headers))
        canonical_request = (
            f"PUT\n/{key}\n\n"
            + "\n".join(
                f"{h.lower()}:{headers[h]}" for h in sorted(headers, key=str.lower)
            )
            + f"\n\n{signed_headers}\n{payload_hash}"
        )
        scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
            f"{hl.sha256(canonical_request.encode()).hexdigest()}"
        )

        signature = _aws_sign(self._secret_key, date_stamp, self._region, string_to_sign)
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(url, content=content, headers=headers)
            if not response.is_success:
                raise ObjectStorageError(
                    f"S3 PUT failed {response.status_code}: {response.text}"
                )

    async def get(self, key: str) -> bytes:
        import hmac
        import hashlib as hl
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        import httpx

        url = f"{self._endpoint}/{self._bucket}/{key}"

        headers: dict[str, str] = {
            "Host": f"{self._endpoint.removeprefix('https://')}",
            "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "x-amz-date": amz_date,
        }

        signed_headers = ";".join(sorted(h.lower() for h in headers))
        canonical_request = (
            f"GET\n/{key}\n\n"
            + "\n".join(
                f"{h.lower()}:{headers[h]}" for h in sorted(headers, key=str.lower)
            )
            + f"\n\n{signed_headers}\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
            f"{hl.sha256(canonical_request.encode()).hexdigest()}"
        )

        signature = _aws_sign(self._secret_key, date_stamp, self._region, string_to_sign)
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            if not response.is_success:
                raise ObjectStorageError(
                    f"S3 GET failed {response.status_code}: {response.text}"
                )
            return response.content

    async def delete(self, key: str) -> None:
        import hmac
        import hashlib as hl
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        import httpx

        url = f"{self._endpoint}/{self._bucket}/{key}"

        headers: dict[str, str] = {
            "Host": f"{self._endpoint.removeprefix('https://')}",
            "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "x-amz-date": amz_date,
        }

        signed_headers = ";".join(sorted(h.lower() for h in headers))
        canonical_request = (
            f"DELETE\n/{key}\n\n"
            + "\n".join(
                f"{h.lower()}:{headers[h]}" for h in sorted(headers, key=str.lower)
            )
            + f"\n\n{signed_headers}\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        scope = f"{date_stamp}/{self._region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
            f"{hl.sha256(canonical_request.encode()).hexdigest()}"
        )

        signature = _aws_sign(self._secret_key, date_stamp, self._region, string_to_sign)
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(url, headers=headers)
            if not response.is_success:
                raise ObjectStorageError(
                    f"S3 DELETE failed {response.status_code}: {response.text}"
                )

    async def exists(self, key: str) -> bool:
        try:
            await self.get(key)
            return True
        except ObjectStorageError:
            return False
