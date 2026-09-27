"""Provider preflight and SIP discovery. Secrets never leave this module in diagnostics."""

import asyncio
import json
import os
import secrets
from pathlib import Path

import httpx
from livekit import api

from .config import ROOT, Settings
from .notifications import webhook_configured


def livekit_api(s: Settings):
    return api.LiveKitAPI(s.livekit_url, s.livekit_api_key, s.livekit_api_secret)


def lk_token(s: Settings, room: str, identity: str, publish: bool = False):
    from datetime import timedelta

    return (
        api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
        .with_identity(identity)
        .with_ttl(timedelta(minutes=20))
        .with_grants(
            api.VideoGrants(
                room_join=True, room=room, can_publish=publish, can_subscribe=True, can_publish_data=False
            )
        )
        .to_jwt()
    )


def save_private(path: Path, value):
    path.parent.mkdir(exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f)


async def discover_trunk(s: Settings) -> str:
    async with livekit_api(s) as lk:
        result = await lk.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        if s.livekit_sip_trunk_id:
            matches = [t for t in result.items if t.sip_trunk_id == s.livekit_sip_trunk_id]
        else:
            matches = [t for t in result.items if s.plivo_phone_number in t.numbers]
        if len(matches) == 1:
            return matches[0].sip_trunk_id
        if len(matches) > 1:
            raise ValueError("Multiple matching LiveKit trunks. Set LIVEKIT_SIP_TRUNK_ID in .env.")
        raise ValueError(
            "No matching LiveKit outbound trunk. Run make provision or set LIVEKIT_SIP_TRUNK_ID."
        )


async def provision(s: Settings):
    try:
        trunk_id = await discover_trunk(s)
        save_private(ROOT / ".local" / "trunk.json", {"trunk_id": trunk_id})
        return {"status": "reused", "trunk_id": trunk_id}
    except ValueError as exc:
        if "No matching" not in str(exc):
            raise
    path = ROOT / ".local" / "provisioning.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    base = f"https://api.plivo.com/v1/Account/{s.plivo_auth_id}/Zentrunk"
    async with httpx.AsyncClient(auth=(s.plivo_auth_id, s.plivo_auth_token), timeout=20) as client:
        if not data.get("credential_uuid"):
            data.update(username="atp" + secrets.token_hex(5), password=secrets.token_hex(8) + "!Aa1")
            save_private(path, data)
            response = await client.post(
                base + "/Credential/",
                json={"name": "ATP demo", "username": data["username"], "password": data["password"]},
            )
            response.raise_for_status()
            data["credential_uuid"] = response.json()["credential_uuid"]
            save_private(path, data)
        if not data.get("trunk_id"):
            response = await client.post(
                base + "/Trunk/",
                json={
                    "name": "ATP demo outbound",
                    "trunk_direction": "outbound",
                    "credential_uuid": data["credential_uuid"],
                    "secure": True,
                },
            )
            response.raise_for_status()
            data["trunk_id"] = response.json()["trunk_id"]
            save_private(path, data)
        response = await client.get(base + "/Trunk/" + data["trunk_id"] + "/")
        response.raise_for_status()
        obj = response.json().get("object", response.json())
        domain = obj.get("trunk_domain") or obj.get("domain") or obj.get("termination_domain")
        if not domain:
            raise ValueError("Plivo did not return a termination domain; inspect the trunk in its console.")
        async with livekit_api(s) as lk:
            trunk = await lk.sip.create_sip_outbound_trunk(
                api.CreateSIPOutboundTrunkRequest(
                    trunk=api.SIPOutboundTrunkInfo(
                        name="ATP demo",
                        address=domain,
                        numbers=[s.plivo_phone_number],
                        auth_username=data["username"],
                        auth_password=data["password"],
                        transport=api.SIPTransport.SIP_TRANSPORT_TLS,
                    )
                )
            )
            save_private(ROOT / ".local" / "trunk.json", {"trunk_id": trunk.sip_trunk_id})
            return {"status": "created", "trunk_id": trunk.sip_trunk_id}


async def readiness(s: Settings):
    async def check(name, fn):
        try:
            detail = await fn()
            return name, {"ok": True, "detail": detail}
        except Exception as exc:
            # Provider exception messages can contain URLs, credentials, or request bodies.
            code = getattr(getattr(exc, "response", None), "status_code", None)
            return name, {
                "ok": False,
                "detail": f"Check failed ({code or type(exc).__name__}); check credentials and account permissions.",
            }

    async def openai_check():
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(
                "https://api.openai.com/v1/models/" + s.openai_model,
                headers={"Authorization": "Bearer " + s.openai_api_key},
            )
            r.raise_for_status()
        return "Model accessible"

    async def eleven_check():
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(
                "https://api.elevenlabs.io/v1/voices/" + s.eleven_voice_id,
                headers={"xi-api-key": s.eleven_api_key},
            )
            r.raise_for_status()
        return "Selected voice accessible; streaming checked on call start"

    async def livekit_check():
        async with livekit_api(s) as lk:
            await lk.room.list_rooms(api.ListRoomsRequest())
        return "Room API connected"

    async def plivo_check():
        async with httpx.AsyncClient(auth=(s.plivo_auth_id, s.plivo_auth_token), timeout=12) as c:
            r = await c.get(
                f"https://api.plivo.com/v1/Account/{s.plivo_auth_id}/Number/{s.plivo_phone_number.lstrip('+')}/"
            )
            r.raise_for_status()
        return "Caller number accessible"

    async def trunk_check():
        await discover_trunk(s)
        return "Existing outbound trunk found"

    async def slack_check():
        if not webhook_configured(s):
            raise ValueError("Configure SLACK_WEBHOOK_URL")
        return "Webhook configured; posting is checked when a notification is sent"

    return dict(
        await asyncio.gather(
            *(
                check(n, f)
                for n, f in [
                    ("OpenAI", openai_check),
                    ("ElevenLabs", eleven_check),
                    ("LiveKit", livekit_check),
                    ("Plivo", plivo_check),
                    ("SIP trunk", trunk_check),
                    ("Slack", slack_check),
                ]
            )
        )
    )
