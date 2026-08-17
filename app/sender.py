from dataclasses import dataclass
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    status: (
        str  # 'accepted', 'rate_limited', 'transient_error', 'permanent_error'
    )
    dm_id: Optional[str] = None
    retry_after: float = 60.0
    error: Optional[str] = None


@dataclass
class ReconcileResult:
    status: (
        str  # 'queued', 'delivered', 'failed', 'not_found', 'transient_error'
    )
    raw_status: Optional[str] = None
    error: Optional[str] = None


class PseudoGramClient:

    def __init__(
        self, base_url: str = settings.PSEUDOGRAM_BASE_URL, timeout: float = 10.0
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def send_dm(
        self,
        api_key: str,
        recipient_user_id: str,
        message: str,
        comment_id: str,
        idempotency_key: str,
    ) -> SendResult:
        url = f"{self.base_url}/v1/dm/send"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "Idempotency-Key": idempotency_key,
        }
        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
            "comment_id": comment_id,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)

            status_code = response.status_code

            if status_code in (200, 202):
                try:
                    data = response.json()
                    dm_id = data.get("dm_id")
                    return SendResult(status="accepted", dm_id=dm_id)
                except Exception as err:
                    return SendResult(
                        status="transient_error",
                        error=f"Invalid JSON response: {err}",
                    )

            if status_code == 429:
                retry_after_hdr = response.headers.get("retry-after")
                try:
                    retry_after = (
                        float(retry_after_hdr) if retry_after_hdr else 60.0
                    )
                except ValueError:
                    retry_after = 60.0
                return SendResult(
                    status="rate_limited",
                    retry_after=retry_after,
                    error="429 Rate limited",
                )

            if status_code == 400:
                try:
                    detail = response.json().get("detail", "Invalid request")
                except Exception:
                    detail = response.text
                return SendResult(
                    status="permanent_error", error=f"400 Bad Request: {detail}"
                )

            if status_code == 401:
                return SendResult(
                    status="permanent_error",
                    error="401 Unauthorized - Check API_KEY",
                )

            if status_code >= 500:
                return SendResult(
                    status="transient_error",
                    error=f"Server error HTTP {status_code}",
                )

            return SendResult(
                status="permanent_error",
                error=f"Unexpected status code {status_code}",
            )

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning("HTTP connection error in send_dm: %s", exc)
            return SendResult(
                status="transient_error", error=f"Network error: {exc}"
            )

    async def get_dm_status(self, api_key: str, dm_id: str) -> ReconcileResult:
        url = f"{self.base_url}/v1/dm/{dm_id}"
        headers = {"X-API-Key": api_key}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                raw_status = data.get("status")
                if raw_status in ("queued", "delivered", "failed"):
                    return ReconcileResult(
                        status=raw_status, raw_status=raw_status
                    )
                return ReconcileResult(
                    status="queued", raw_status=raw_status
                )  # default fallback

            if response.status_code == 404:
                return ReconcileResult(status="not_found")

            return ReconcileResult(
                status="transient_error",
                error=f"HTTP {response.status_code}",
            )

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning("HTTP connection error in get_dm_status: %s", exc)
            return ReconcileResult(
                status="transient_error", error=f"Network error: {exc}"
            )
