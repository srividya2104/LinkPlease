import hashlib
import hmac
import pytest
import app.main as main_mod
from app.config import settings
from app.crypto import derive_hmac_secret
from tests.conftest import TEST_API_KEY


def test_create_rule(client):
    res = client.post(
        "/rules", json={"keyword": "PRICE", "dm_message": "Here is the price!"}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["keyword"] == "PRICE"
    assert data["dm_message"] == "Here is the price!"
    assert "rule_id" in data


def test_webhook_matching_rule(client):
    client.post(
        "/rules", json={"keyword": "PRICE", "dm_message": "Price list..."}
    )

    payload = {
        "event_id": "evt_test_001",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22.481Z",
        "data": {
            "comment_id": "cmt_001",
            "post_id": "post_001",
            "text": "Can I get the PRICE please?",
            "created_at": "2026-08-10T09:14:21.900Z",
            "from": {"user_id": "usr_001", "username": "alice"},
        },
    }

    res = client.post("/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["deliveries_created"] == 1


def test_webhook_duplicate_event_id(client):
    client.post(
        "/rules", json={"keyword": "PRICE", "dm_message": "Price list..."}
    )

    payload = {
        "event_id": "evt_dup_001",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_002",
            "text": "PRICE please",
            "from": {"user_id": "usr_002"},
        },
    }

    res1 = client.post("/webhook", json=payload)
    assert res1.status_code == 200

    res2 = client.post("/webhook", json=payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate_event_ignored"


def test_webhook_duplicate_rule_user_suppression(client):
    client.post(
        "/rules", json={"keyword": "PRICE", "dm_message": "Price list..."}
    )

    payload1 = {
        "event_id": "evt_user_001",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_u1",
            "text": "PRICE please",
            "from": {"user_id": "usr_same"},
        },
    }
    payload2 = {
        "event_id": "evt_user_002",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_u2",
            "text": "What is the price?",
            "from": {"user_id": "usr_same"},
        },
    }

    res1 = client.post("/webhook", json=payload1)
    assert res1.json()["deliveries_created"] == 1

    res2 = client.post("/webhook", json=payload2)
    assert res2.json()["deliveries_created"] == 0

    stats = client.get("/stats").json()
    assert stats["duplicates_blocked"] == 1


def test_webhook_comment_deleted_does_not_cancel_pending_delivery(client, temp_db):
    client.post(
        "/rules", json={"keyword": "PRICE", "dm_message": "Price list..."}
    )

    created_payload = {
        "event_id": "evt_del_test_1",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_to_delete",
            "text": "PRICE list",
            "from": {"user_id": "usr_del"},
        },
    }
    res_created = client.post("/webhook", json=created_payload)
    assert res_created.json()["deliveries_created"] == 1

    # Verify delivery is pending
    delivery_before = temp_db.get_delivery_by_idempotency_key("rule:rule_1:user:usr_del")
    if not delivery_before:
        # Find by user_id
        with temp_db.get_connection() as conn:
            row = conn.execute("SELECT * FROM deliveries WHERE recipient_user_id = 'usr_del'").fetchone()
            delivery_before = dict(row) if row else None
    assert delivery_before["status"] == "pending"

    # Send comment.deleted
    deleted_payload = {
        "event_id": "evt_del_test_2",
        "event_type": "comment.deleted",
        "data": {"comment_id": "cmt_to_delete"},
    }
    res_del = client.post("/webhook", json=deleted_payload)
    assert res_del.status_code == 200
    assert res_del.json()["action"] == "comment_deleted_logged"

    # Verify delivery status is STILL pending (NOT cancelled)
    delivery_after = temp_db.get_delivery_by_idempotency_key(delivery_before["idempotency_key"])
    assert delivery_after["status"] == "pending"

    # Verify it can still be claimed by the worker
    claimed = temp_db.claim_pending_deliveries(limit=1)
    assert len(claimed) == 1
    assert claimed[0]["id"] == delivery_before["id"]


def test_webhook_hmac_enforcement(client):
    settings.VERIFY_WEBHOOK_SIGNATURE = True

    payload_bytes = b'{"event_id": "evt_hmac_1", "event_type": "comment.created", "data": {"comment_id": "c1", "text": "PRICE", "from": {"user_id": "u1"}}}'
    secret = derive_hmac_secret(TEST_API_KEY)
    valid_sig = (
        "sha256=" + hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
    )

    res1 = client.post(
        "/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-PseudoGram-Signature": valid_sig,
        },
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-PseudoGram-Signature": "sha256=invalid",
        },
    )
    assert res2.status_code == 401

    settings.VERIFY_WEBHOOK_SIGNATURE = False


def test_concurrent_duplicate_deliveries(temp_db):
    created1 = temp_db.create_delivery(
        delivery_id="del_c1",
        rule_id="r1",
        recipient_user_id="u_concurrent",
        comment_id="c1",
        idempotency_key="rule:r1:user:u_concurrent",
        message="msg",
    )
    assert created1 is True

    created2 = temp_db.create_delivery(
        delivery_id="del_c2",
        rule_id="r1",
        recipient_user_id="u_concurrent",
        comment_id="c2",
        idempotency_key="rule:r1:user:u_concurrent",
        message="msg",
    )
    assert created2 is False

    stats = temp_db.get_stats()
    assert stats["duplicates_blocked"] == 1
