import time
import pytest
from app.sender import SendResult
from app.worker import BackgroundWorkerManager, RollingRateLimiter


def test_rate_limiter_window():
    limiter = RollingRateLimiter(max_requests=2, window_seconds=1.0)
    assert limiter.can_send() is True

    limiter.record_send()
    assert limiter.can_send() is True

    limiter.record_send()
    assert limiter.can_send() is False

    time.sleep(1.05)
    assert limiter.can_send() is True


def test_stuck_sending_recovery(temp_db):
    # Insert a delivery in 'sending' state with old updated_at
    temp_db.create_delivery(
        delivery_id="del_stuck",
        rule_id="rule_1",
        recipient_user_id="usr_1",
        comment_id="cmt_1",
        idempotency_key="rule:rule_1:user:usr_1",
        message="test",
    )
    # Force status to sending and updated_at to 60s ago
    with temp_db.get_connection() as conn:
        with conn:
            conn.execute(
                "UPDATE deliveries SET status = 'sending', updated_at = ? WHERE"
                " id = 'del_stuck'",
                (time.time() - 60.0,),
            )

    # Reset stuck deliveries
    temp_db.reset_stuck_deliveries(timeout_seconds=30)

    # Verify status is reset to pending
    delivery = temp_db.get_delivery_by_idempotency_key("rule:rule_1:user:usr_1")
    assert delivery["status"] == "pending"


@pytest.mark.asyncio
async def test_worker_process_send_success(temp_db, monkeypatch):
    class MockClient:

        async def send_dm(self, *args, **kwargs):
            return SendResult(status="accepted", dm_id="dm_mock_999")

    temp_db.create_delivery(
        delivery_id="del_1",
        rule_id="rule_1",
        recipient_user_id="usr_1",
        comment_id="cmt_1",
        idempotency_key="rule:rule_1:user:usr_1",
        message="Hello",
    )

    manager = BackgroundWorkerManager(db=temp_db, client=MockClient())
    delivery = temp_db.claim_pending_deliveries(limit=1)[0]
    await manager._process_send(delivery, api_key="test_key")

    updated = temp_db.get_delivery_by_idempotency_key("rule:rule_1:user:usr_1")
    assert updated["status"] == "dm_accepted"
    assert updated["dm_id"] == "dm_mock_999"


@pytest.mark.asyncio
async def test_worker_process_send_transient_retry(temp_db):
    class MockClient:

        async def send_dm(self, *args, **kwargs):
            return SendResult(
                status="transient_error", error="500 internal_error"
            )

    temp_db.create_delivery(
        delivery_id="del_2",
        rule_id="rule_1",
        recipient_user_id="usr_2",
        comment_id="cmt_2",
        idempotency_key="rule:rule_1:user:usr_2",
        message="Hello",
    )

    manager = BackgroundWorkerManager(db=temp_db, client=MockClient())
    delivery = temp_db.claim_pending_deliveries(limit=1)[0]
    await manager._process_send(delivery, api_key="test_key")

    updated = temp_db.get_delivery_by_idempotency_key("rule:rule_1:user:usr_2")
    assert updated["status"] == "pending"
    assert updated["attempt_count"] == 1
    assert updated["next_attempt_at"] > time.time()
