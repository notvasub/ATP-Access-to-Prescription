import asyncio
from urllib.parse import urlsplit

import httpx
import pytest
from test_engine import Transport

from atp.config import Settings
from atp.main import create_app


@pytest.fixture
async def api_client(tmp_path):
    config = Settings(
        _env_file=None,
        app_demo_password="test-demo",
        database_path=str(tmp_path / "api.db"),
        livekit_api_key="devkey",
        livekit_api_secret="x" * 40,
        livekit_url="wss://example.test",
        openai_api_key="test",
        eleven_api_key="test",
        eleven_voice_id="test",
    )
    app = create_app(config, Transport)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"X-ATP-Request": "1"}
        ) as client:
            yield app, client


async def test_auth_csrf_private_roles_and_one_use_links(api_client):
    app, client = api_client
    assert (await client.get("/api/case")).status_code == 401
    assert (await client.post("/api/login", json={"password": "wrong"})).status_code == 401
    assert (
        await client.post("/api/login", json={"password": "test-demo"}, headers={"X-ATP-Request": "0"})
    ).status_code == 403
    assert (await client.post("/api/login", json={"password": "test-demo"})).status_code == 200
    call = (await client.post("/api/calls", json={"mode": "browser"})).json()
    await asyncio.sleep(0.01)
    links = (await client.post(f"/api/calls/{call['id']}/join-links")).json()
    invite = urlsplit(links["presentation"]).fragment
    grant = await client.post("/api/access", json={"token": invite})
    assert grant.status_code == 200
    assert (await client.post("/api/access", json={"token": invite})).status_code == 401
    headers = {"Authorization": "Bearer " + grant.json()["token"]}
    assert (await client.get("/api/case", headers=headers)).status_code == 403
    c = app.state.coordinator
    c.call["briefing"] = {"reason": "Private briefing"}
    snapshot = (await client.get(f"/api/calls/{call['id']}", headers=headers)).json()
    assert "briefing" not in snapshot
    result = await client.post(
        f"/api/calls/{call['id']}/control",
        headers=headers,
        json={"action": "end", "request_id": "unauthorized", "revision": 0},
    )
    assert result.status_code == 403
    assert c.call["status"] == "active"
    assert (await client.patch("/api/case", json=(await client.get("/api/case")).json())).status_code == 409


async def test_websocket_first_message_auth_and_private_snapshot(api_client):
    import json
    from contextlib import suppress

    app, client = api_client
    await client.post("/api/login", json={"password": "test-demo"})
    call = (await client.post("/api/calls", json={"mode": "browser"})).json()
    await asyncio.sleep(0.01)
    app.state.coordinator.call["briefing"] = {"reason": "Private clinical briefing"}
    token = app.state.signer.dumps({"purpose": "session", "role": "presentation", "call_id": call["id"]})
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "server": ("test", 80),
        "client": ("test-client", 123),
        "root_path": "",
        "path": f"/api/calls/{call['id']}/events",
        "query_string": b"",
        "headers": [(b"host", b"test"), (b"origin", b"http://test")],
        "subprotocols": [],
    }
    await incoming.put({"type": "websocket.connect"})
    await incoming.put({"type": "websocket.receive", "text": json.dumps({"token": token})})
    task = asyncio.create_task(app(scope, incoming.get, outgoing.put))
    try:
        assert (await asyncio.wait_for(outgoing.get(), 2))["type"] == "websocket.accept"
        message = await asyncio.wait_for(outgoing.get(), 2)
        snapshot = json.loads(message["text"])
        assert snapshot["type"] == "snapshot"
        assert "briefing" not in snapshot["call"]
        assert app.state.coordinator.listeners
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert not app.state.coordinator.listeners


async def test_separate_contact_numbers_persist_and_cannot_change_on_call(api_client):
    app, client = api_client
    assert (await client.get("/api/contacts")).status_code == 401
    await client.post("/api/login", json={"password": "test-demo"})
    numbers = {"insurer_phone_number": "+12025550122", "doctor_phone_number": "+12025550123"}
    result = await client.put("/api/contacts", json=numbers)
    assert result.status_code == 200
    assert (await client.get("/api/contacts")).json() == numbers
    assert app.state.coordinator.store.get("contacts") == numbers
    assert (
        await client.put("/api/contacts", json=numbers, headers={"X-ATP-Request": "0"})
    ).status_code == 403
    assert (
        await client.put("/api/contacts", json={**numbers, "doctor_phone_number": "not-a-number"})
    ).status_code == 422
    assert (
        await client.put(
            "/api/contacts", json={**numbers, "doctor_phone_number": numbers["insurer_phone_number"]}
        )
    ).status_code == 422
    call = (await client.post("/api/calls", json={"mode": "browser"})).json()
    assert call["contacts"] == numbers
    assert (await client.put("/api/contacts", json=numbers)).status_code == 409
    token = app.state.signer.dumps(
        {
            "purpose": "session",
            "role": "doctor",
            "phone_control": True,
            "identity": "doctor-phone-test",
            "call_id": call["id"],
        }
    )
    response = await client.post(
        "/api/calls/" + call["id"] + "/join", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 409  # Control link must never replace the SIP participant with a browser.


async def test_doctor_briefing_posts_slack_control_link_without_sms(api_client, monkeypatch):
    from unittest.mock import AsyncMock

    from atp import main

    app, client = api_client
    app.state.coordinator.settings.public_base_url = "https://demo.test"
    sender = AsyncMock(return_value="posted")
    monkeypatch.setattr(main, "send_slack", sender)
    call = {
        "id": "slack-test",
        "transcript": [{"speaker": "payer", "text": "Please ask the doctor about prior therapy."}],
    }
    attempt = {"identity": "doctor-phone-test", "briefing": {"reason": "Confirm prior therapy"}}
    await app.state.coordinator.notify_doctor(call, attempt)
    assert attempt["notification_status"] == "posted"
    assert attempt["notification_provider"] == "slack"
    assert "sms_status" not in attempt
    payload = sender.call_args.args[1]
    assert "Confirm prior therapy" in str(payload)
    assert "press 1" in str(payload)
    assert attempt["control_url"] in str(payload)


async def test_uncertain_slack_delivery_does_not_claim_failure_or_success(api_client, monkeypatch):
    from unittest.mock import AsyncMock

    from atp import main
    from atp.notifications import NotificationUnconfirmed

    app, client = api_client
    monkeypatch.setattr(main, "send_slack", AsyncMock(side_effect=NotificationUnconfirmed("Not confirmed")))
    attempt = {"identity": "doctor-phone-test"}
    await app.state.coordinator.notify_doctor({"id": "slack-test", "transcript": []}, attempt)
    assert attempt["notification_status"] == "unconfirmed"


async def test_pitch_scenario_is_explicit_and_validated(api_client):
    app, client = api_client
    await client.post("/api/login", json={"password": "test-demo"})
    invalid = await client.post("/api/calls", json={"mode": "browser", "scenario": "invented"})
    assert invalid.status_code == 422
    response = await client.post("/api/calls", json={"mode": "browser", "scenario": "pitch"})
    assert response.status_code == 200
    assert response.json()["scenario"] == "pitch"
    assert response.json()["case"]["patient"] == "Morgan Ellis"
