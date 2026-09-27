"""Verify private answer screening with real LiveKit/ElevenLabs; never dial a phone."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from livekit import api, rtc

from atp.config import Settings
from atp.engine import ControlError, Coordinator
from atp.store import Store


async def check(voicemail, role="doctor"):
    settings = Settings()
    doctor = rtc.Room()
    source = rtc.AudioSource(24000, 1, queue_size_ms=150)
    simulated = None
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "screen.sqlite3")
        c = Coordinator(settings, store)
        try:
            await c.start("browser")
            async with asyncio.timeout(20):
                while c.call["status"] == "starting":
                    await asyncio.sleep(0.1)
            assert c.call["status"] == "active"
            c.call.update(control="handoff_pending", briefing={"reason": "Synthetic test"})
            c.call["contacts"]["doctor_phone_number"] = "+12025550101"

            async def input_audio():
                await asyncio.sleep(1)
                if not voicemail:
                    await doctor.local_participant.publish_dtmf(code=1, digit="1")
                    return
                stream = c.transport.tts.stream()
                try:
                    stream.push_text("Please leave a message after the tone.")
                    stream.end_input()
                    async for packet in stream:
                        await source.capture_frame(packet.frame)
                    await source.wait_for_playout()
                    for _ in range(75):
                        await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
                    await source.wait_for_playout()
                finally:
                    await stream.aclose()

            async def synthetic_answer(request, **kwargs):
                nonlocal simulated
                # This replaces the outbound SIP API entirely: no telephone is dialed.
                token = (
                    api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
                    .with_identity(request.participant_identity)
                    .with_grants(
                        api.VideoGrants(
                            room_join=True,
                            room=request.room_name,
                            can_publish=True,
                            can_subscribe=True,
                            can_publish_data=True,
                        )
                    )
                    .to_jwt()
                )
                await doctor.connect(settings.livekit_url, token)
                if voicemail:
                    await doctor.local_participant.publish_track(
                        rtc.LocalAudioTrack.create_audio_track("Synthetic voicemail", source)
                    )
                simulated = asyncio.create_task(input_audio())

            with patch.object(c.transport.lk.sip, "create_sip_participant", synthetic_answer):
                if role == "insurer":
                    c.call.update(mode="phone", status="dialing", control="ai")
                    try:
                        await c.transport.dial()
                    except ControlError as exc:
                        assert voicemail and "voicemail" in exc.message, exc.message
                    else:
                        assert not voicemail, "Voicemail was allowed into the conversation"
                    if voicemail:
                        assert "payer" not in c.call["participants"]
                        assert not c.call["transcript"]
                        print(
                            "PASS: Insurer voicemail rejected privately; no authorization conversation",
                            flush=True,
                        )
                    else:
                        async with asyncio.timeout(5):
                            while "payer" not in c.call["participants"]:
                                await asyncio.sleep(0.05)
                        assert not c.call["transcript"]
                        c.call["status"] = "active"
                        c.greet()
                        await asyncio.wait_for(c.reply_task, 20)
                        assert any(t["speaker"] == "ai" for t in c.call["transcript"])
                        print(
                            "PASS: Insurer pressed 1; moved to conversation; ATP greeted afterward",
                            flush=True,
                        )
                    assert not c.transport.screen_rooms
                    return
                else:
                    c.request_doctor()
                    await asyncio.wait_for(c.doctor_task, 35)
            attempt = c.call["doctor_call"]
            if voicemail:
                assert attempt["status"] == "failed", attempt["error"]
                assert "voicemail" in attempt["error"], attempt["error"]
                assert c.call["control"] == "ai"
                assert not any(t["speaker"] == "doctor" for t in c.call["transcript"])
                assert attempt["identity"] not in c.call["participants"]
                await asyncio.wait_for(c.reply_task, 20)
                assert any("couldn't reach our doctor" in t["text"] for t in c.call["transcript"])
                print("PASS: Real Scribe detected voicemail; no insurer transcript leak; AI spoke fallback")
            else:
                assert c.call["control"] == "doctor", attempt["error"]
                assert attempt["status"] == "connected"
                await doctor.local_participant.publish_dtmf(code=11, digit="#")
                async with asyncio.timeout(10):
                    while c.call["control"] != "ai":
                        await asyncio.sleep(0.1)
                assert attempt["status"] == "returned"
                print("PASS: Press 1 moved doctor into insurer room; # returned control to AI")
            assert not c.transport.screen_rooms
        finally:
            if simulated:
                simulated.cancel()
                await asyncio.gather(simulated, return_exceptions=True)
            await c.end("Screening smoke check finished.")
            await doctor.disconnect()
            await source.aclose()
            store.close()


async def main():
    await check(False, "insurer")
    await check(True, "insurer")
    await check(False)
    await check(True)


if __name__ == "__main__":
    asyncio.run(main())
