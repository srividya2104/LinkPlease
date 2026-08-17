import pytest
import httpx
from app.sender import PseudoGramClient


@pytest.mark.asyncio
async def test_sender_202_accepted(monkeypatch):
    async def mock_post(*args, **kwargs):
        return httpx.Response(
            202, json={"dm_id": "dm_accepted_123", "status": "queued"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = PseudoGramClient()
    res = await client.send_dm(
        "key", "usr_1", "msg", "cmt_1", "rule:1:user:usr_1"
    )
    assert res.status == "accepted"
    assert res.dm_id == "dm_accepted_123"


@pytest.mark.asyncio
async def test_sender_200_idempotent_replay(monkeypatch):
    async def mock_post(*args, **kwargs):
        return httpx.Response(
            200, json={"dm_id": "dm_accepted_123", "status": "queued"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = PseudoGramClient()
    res = await client.send_dm(
        "key", "usr_1", "msg", "cmt_1", "rule:1:user:usr_1"
    )
    assert res.status == "accepted"
    assert res.dm_id == "dm_accepted_123"


@pytest.mark.asyncio
async def test_sender_429_rate_limited(monkeypatch):
    async def mock_post(*args, **kwargs):
        return httpx.Response(
            429,
            json={"error": "rate_limited"},
            headers={"Retry-After": "45"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = PseudoGramClient()
    res = await client.send_dm(
        "key", "usr_1", "msg", "cmt_1", "rule:1:user:usr_1"
    )
    assert res.status == "rate_limited"
    assert res.retry_after == 45.0


@pytest.mark.asyncio
async def test_sender_500_transient(monkeypatch):
    async def mock_post(*args, **kwargs):
        return httpx.Response(500, json={"error": "internal_error"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = PseudoGramClient()
    res = await client.send_dm(
        "key", "usr_1", "msg", "cmt_1", "rule:1:user:usr_1"
    )
    assert res.status == "transient_error"


@pytest.mark.asyncio
async def test_sender_400_permanent(monkeypatch):
    async def mock_post(*args, **kwargs):
        return httpx.Response(
            400, json={"error": "invalid_request", "detail": "bad user"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = PseudoGramClient()
    res = await client.send_dm(
        "key", "usr_1", "msg", "cmt_1", "rule:1:user:usr_1"
    )
    assert res.status == "permanent_error"
    assert "bad user" in res.error


@pytest.mark.asyncio
async def test_get_dm_status(monkeypatch):
    async def mock_get(*args, **kwargs):
        return httpx.Response(200, json={"dm_id": "dm_1", "status": "delivered"})

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    client = PseudoGramClient()
    res = await client.get_dm_status("key", "dm_1")
    assert res.status == "delivered"
