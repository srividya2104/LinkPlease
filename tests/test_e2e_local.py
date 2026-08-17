import hashlib
import hmac
import time
import pytest
from app.crypto import derive_hmac_secret
from app.sender import PseudoGramClient, ReconcileResult, SendResult
from tests.conftest import TEST_API_KEY


@pytest.mark.asyncio
async def test_full_local_e2e(client, temp_db, monkeypatch):
    # Mock PseudoGram API response for send and status read
    async def mock_send_dm(self, api_key, recipient_user_id, message, comment_id, idempotency_key):
        return SendResult(status="accepted", dm_id=f"dm_e2e_{recipient_user_id}")

    async def mock_get_dm_status(self, api_key, dm_id):
        return ReconcileResult(status="delivered")

    monkeypatch.setattr(PseudoGramClient, "send_dm", mock_send_dm)
    monkeypatch.setattr(PseudoGramClient, "get_dm_status", mock_get_dm_status)

    # 1. Create rule
    rule_res = client.post(
        "/rules", json={"keyword": "PRICE", "dm_message": "Price list is $100"}
    )
    assert rule_res.status_code == 201

    # 2. Trigger webhook
    payload = {
        "event_id": "evt_e2e_001",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_e2e_1",
            "text": "What is the PRICE?",
            "from": {"user_id": "usr_e2e_1"},
        },
    }
    wh_res = client.post("/webhook", json=payload)
    assert wh_res.status_code == 200

    # Verify pending state
    stats1 = client.get("/stats").json()
    assert stats1["queued"] == 1
    assert stats1["sent"] == 0

    # 3. Execute Worker Send step
    import app.main as main_mod

    wm = main_mod.worker_manager
    claimed = temp_db.claim_pending_deliveries(limit=1)
    assert len(claimed) == 1
    await wm._process_send(claimed[0], TEST_API_KEY)

    # Verify dm_accepted state (still queued in stats)
    stats2 = client.get("/stats").json()
    assert stats2["queued"] == 1

    # 4. Execute Reconciliation step
    accepted = temp_db.get_accepted_deliveries_for_reconciliation()
    assert len(accepted) == 1
    await wm._reconcile_delivery(accepted[0], TEST_API_KEY)

    # 5. Verify final status: sent = 1, queued = 0
    stats3 = client.get("/stats").json()
    assert stats3["sent"] == 1
    assert stats3["queued"] == 0
    assert stats3["failed"] == 0
    assert stats3["duplicates_blocked"] == 0
