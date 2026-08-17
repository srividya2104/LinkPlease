import pytest
from app.sender import ReconcileResult
from app.worker import BackgroundWorkerManager


@pytest.mark.asyncio
async def test_reconcile_delivery_delivered(temp_db):
    class MockClient:

        async def get_dm_status(self, api_key, dm_id):
            return ReconcileResult(status="delivered")

    temp_db.create_delivery(
        delivery_id="del_rec_1",
        rule_id="r1",
        recipient_user_id="u1",
        comment_id="c1",
        idempotency_key="rule:r1:user:u1",
        message="msg",
    )
    temp_db.update_delivery("del_rec_1", status="dm_accepted", dm_id="dm_del_1")

    manager = BackgroundWorkerManager(db=temp_db, client=MockClient())
    delivery = temp_db.get_accepted_deliveries_for_reconciliation()[0]
    await manager._reconcile_delivery(delivery, "test_key")

    updated = temp_db.get_delivery_by_idempotency_key("rule:r1:user:u1")
    assert updated["status"] == "sent"


@pytest.mark.asyncio
async def test_reconcile_delivery_failed_requeue(temp_db):
    class MockClient:

        async def get_dm_status(self, api_key, dm_id):
            return ReconcileResult(status="failed")

    temp_db.create_delivery(
        delivery_id="del_rec_2",
        rule_id="r1",
        recipient_user_id="u2",
        comment_id="c2",
        idempotency_key="rule:r1:user:u2",
        message="msg",
    )
    temp_db.update_delivery("del_rec_2", status="dm_accepted", dm_id="dm_fail_1")

    manager = BackgroundWorkerManager(db=temp_db, client=MockClient())
    delivery = temp_db.get_accepted_deliveries_for_reconciliation()[0]
    await manager._reconcile_delivery(delivery, "test_key")

    updated = temp_db.get_delivery_by_idempotency_key("rule:r1:user:u2")
    assert updated["status"] == "pending"
    assert updated["attempt_count"] == 1
