import pytest


def test_stats_endpoint(client, temp_db):
    # Insert dummy records with various statuses
    temp_db.create_delivery(
        "d1", "r1", "u1", "c1", "rule:r1:user:u1", "msg"
    )  # pending
    temp_db.create_delivery(
        "d2", "r1", "u2", "c2", "rule:r1:user:u2", "msg"
    )  # pending
    temp_db.create_delivery(
        "d3", "r1", "u3", "c3", "rule:r1:user:u3", "msg"
    )  # pending

    temp_db.update_delivery("d1", status="sent")
    temp_db.update_delivery("d2", status="failed")
    temp_db.update_delivery("d3", status="dm_accepted", dm_id="dm_3")

    temp_db.increment_duplicates_blocked(5)

    res = client.get("/stats")
    assert res.status_code == 200
    data = res.json()

    assert data["sent"] == 1
    assert data["failed"] == 1
    assert data["queued"] == 1  # d3 in dm_accepted counts towards queued
    assert data["duplicates_blocked"] == 5
