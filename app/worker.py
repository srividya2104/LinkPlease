import asyncio
import logging
import random
import time
from typing import List, Optional
from app.config import settings
from app.database import Database
from app.sender import PseudoGramClient, SendResult

logger = logging.getLogger(__name__)


class RollingRateLimiter:
    """Enforces a rolling window rate limit for metered requests (e.g., <= 9 sends per 60 seconds)."""

    def __init__(self, max_requests: int = 9, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []

    def can_send(self) -> bool:
        now = time.time()
        self.timestamps = [
            t for t in self.timestamps if now - t < self.window_seconds
        ]
        return len(self.timestamps) < self.max_requests

    def record_send(self):
        self.timestamps.append(time.time())

    def time_until_next_available(self) -> float:
        now = time.time()
        self.timestamps = [
            t for t in self.timestamps if now - t < self.window_seconds
        ]
        if len(self.timestamps) < self.max_requests:
            return 0.0
        # Time until the oldest timestamp falls outside the window
        return max(0.0, self.window_seconds - (now - self.timestamps[0]) + 0.1)


class BackgroundWorkerManager:

    def __init__(
        self,
        db: Database,
        client: Optional[PseudoGramClient] = None,
        max_send_per_min: int = settings.MAX_SEND_PER_MINUTE,
    ):
        self.db = db
        self.client = client or PseudoGramClient()
        self.rate_limiter = RollingRateLimiter(
            max_requests=max_send_per_min, window_seconds=60.0
        )
        self.max_attempts = 5
        self.running = False
        self._send_task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None

    def start(self):
        if self.running:
            return
        self.running = True

        # Recover any stuck 'sending' records on boot
        try:
            self.db.reset_stuck_deliveries(timeout_seconds=30)
        except Exception as e:
            logger.error("Failed to reset stuck deliveries on startup: %s", e)

        self._send_task = asyncio.create_task(self._send_loop())
        self._reconcile_task = asyncio.create_task(self._reconcile_loop())
        logger.info("Background worker tasks started.")

    async def stop(self):
        self.running = False
        if self._send_task:
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass
        if self._reconcile_task:
            self._reconcile_task.cancel()
            try:
                await self._reconcile_task
            except asyncio.CancelledError:
                pass
        logger.info("Background worker tasks stopped.")

    async def _send_loop(self):
        while self.running:
            try:
                api_key = settings.API_KEY
                if not api_key:
                    await asyncio.sleep(1.0)
                    continue

                # Check rate limit capacity before claiming work
                if not self.rate_limiter.can_send():
                    wait_time = self.rate_limiter.time_until_next_available()
                    await asyncio.sleep(min(wait_time, 1.0))
                    continue

                claimed = self.db.claim_pending_deliveries(limit=1)
                if not claimed:
                    await asyncio.sleep(settings.WORKER_POLL_INTERVAL)
                    continue

                delivery = claimed[0]
                await self._process_send(delivery, api_key)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Unexpected error in send loop: %s", exc, exc_info=True)
                await asyncio.sleep(1.0)

    async def _process_send(self, delivery: dict, api_key: str):
        delivery_id = delivery["id"]
        attempt_count = delivery["attempt_count"]
        idempotency_key = delivery["idempotency_key"]

        # If this is a retry attempt after a previous reconciliation failure, append attempt suffix
        if attempt_count > 0 and delivery.get("last_error", "").startswith(
            "Reconciliation"
        ):
            effective_idem_key = f"{idempotency_key}:retry:{attempt_count}"
        else:
            effective_idem_key = idempotency_key

        # Record send timestamp for rate limiter
        self.rate_limiter.record_send()

        res: SendResult = await self.client.send_dm(
            api_key=api_key,
            recipient_user_id=delivery["recipient_user_id"],
            message=delivery["message"],
            comment_id=delivery["comment_id"],
            idempotency_key=effective_idem_key,
        )

        if res.status == "accepted":
            self.db.update_delivery(
                delivery_id=delivery_id,
                status="dm_accepted",
                dm_id=res.dm_id,
                last_error=None,
            )
            logger.info("Delivery %s accepted with dm_id %s", delivery_id, res.dm_id)

        elif res.status == "rate_limited":
            next_attempt = time.time() + res.retry_after
            self.db.update_delivery(
                delivery_id=delivery_id,
                status="pending",
                next_attempt_at=next_attempt,
                last_error=res.error,
            )
            logger.warning(
                "Delivery %s rate limited. Retrying after %s seconds.",
                delivery_id,
                res.retry_after,
            )

        elif res.status == "transient_error":
            new_attempt = attempt_count + 1
            if new_attempt < self.max_attempts:
                # Exponential backoff with jitter (2^attempt * 1.5 + jitter)
                delay = min(60.0, (2**new_attempt) * 1.5 + random.uniform(0.1, 0.5))
                next_attempt = time.time() + delay
                self.db.update_delivery(
                    delivery_id=delivery_id,
                    status="pending",
                    next_attempt_at=next_attempt,
                    last_error=res.error,
                    increment_attempt=True,
                )
                logger.warning(
                    "Delivery %s transient error: %s. Re-queued for attempt %s in"
                    " %.1fs.",
                    delivery_id,
                    res.error,
                    new_attempt,
                    delay,
                )
            else:
                self.db.update_delivery(
                    delivery_id=delivery_id,
                    status="failed",
                    last_error=f"Max attempts ({new_attempt}) reached: {res.error}",
                    increment_attempt=True,
                )
                logger.error(
                    "Delivery %s failed permanently after max attempts.", delivery_id
                )

        elif res.status == "permanent_error":
            self.db.update_delivery(
                delivery_id=delivery_id,
                status="failed",
                last_error=res.error,
                increment_attempt=True,
            )
            logger.error("Delivery %s failed permanently: %s", delivery_id, res.error)

    async def _reconcile_loop(self):
        """Reconciliation queries status of accepted DMs.

        Note: GET /v1/dm/{dm_id} calls do NOT count against PseudoGram rate
        limits.
        """
        while self.running:
            try:
                api_key = settings.API_KEY
                if not api_key:
                    await asyncio.sleep(1.0)
                    continue

                accepted = self.db.get_accepted_deliveries_for_reconciliation(
                    limit=10
                )
                if not accepted:
                    await asyncio.sleep(settings.RECONCILE_POLL_INTERVAL)
                    continue

                for delivery in accepted:
                    if not self.running:
                        break
                    await self._reconcile_delivery(delivery, api_key)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Unexpected error in reconcile loop: %s", exc, exc_info=True
                )
                await asyncio.sleep(1.0)

    async def _reconcile_delivery(self, delivery: dict, api_key: str):
        delivery_id = delivery["id"]
        dm_id = delivery["dm_id"]

        if not dm_id:
            return

        res = await self.client.get_dm_status(api_key, dm_id)

        if res.status == "delivered":
            self.db.update_delivery(
                delivery_id=delivery_id, status="sent", last_error=None
            )
            logger.info(
                "Delivery %s (dm_id: %s) confirmed delivered.", delivery_id, dm_id
            )

        elif res.status == "failed":
            attempt_count = delivery["attempt_count"] + 1
            if attempt_count < self.max_attempts:
                # Re-queue delivery for a new send attempt
                delay = min(60.0, (2**attempt_count) * 1.5 + random.uniform(0.1, 0.5))
                next_attempt = time.time() + delay
                self.db.update_delivery(
                    delivery_id=delivery_id,
                    status="pending",
                    dm_id=None,
                    next_attempt_at=next_attempt,
                    last_error="Reconciliation reported platform delivery failure",
                    increment_attempt=True,
                )
                logger.warning(
                    "Delivery %s failed during reconciliation. Re-queued for retry"
                    " (attempt %s).",
                    delivery_id,
                    attempt_count,
                )
            else:
                self.db.update_delivery(
                    delivery_id=delivery_id,
                    status="failed",
                    last_error=(
                        "Reconciliation reported platform delivery failure after max"
                        " retries"
                    ),
                    increment_attempt=True,
                )
                logger.error(
                    "Delivery %s marked failed after reconciliation.", delivery_id
                )

        elif res.status in ("queued", "transient_error"):
            # Still in progress or network glitch on status read; leave as 'dm_accepted'
            pass
