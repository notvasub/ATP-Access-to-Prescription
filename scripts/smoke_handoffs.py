"""Real-provider rehearsal of AI → administrator → AI → doctor → AI. No phone call."""

import asyncio
import tempfile
from pathlib import Path

from livekit import rtc

from atp.config import Settings
from atp.engine import Coordinator
from atp.providers import lk_token
from atp.store import Store


async def until(predicate, message, seconds=35):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.1)
    print("PASS: " + message, flush=True)


async def main():
    s = Settings()
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "test.db")
        c = Coordinator(s, store)
        rooms, sources = {}, {}
        try:
            await c.start("browser")
            await until(lambda: c.call["status"] == "active", "audio room ready")
            room_id = c.call["room"]
            for identity, role in [("payer", "payer"), ("admin", "administrator"), ("doc", "doctor")]:
                c.session_participants[identity] = role
                room = rtc.Room()
                rooms[identity] = room
                await room.connect(s.livekit_url, lk_token(s, room_id, identity, identity == "payer"))
            await until(lambda: len(c.call["participants"]) == 3, "three participants on one call")

            async def speech(identity, text):
                if identity not in sources:
                    source = rtc.AudioSource(24000, 1, queue_size_ms=150)
                    sources[identity] = source
                    await rooms[identity].local_participant.publish_track(
                        rtc.LocalAudioTrack.create_audio_track("Synthetic speech", source)
                    )
                    await asyncio.sleep(0.4)
                source = sources[identity]
                stream = c.transport.tts.stream()
                stream.push_text(text)
                stream.end_input()
                async for packet in stream:
                    await source.capture_frame(packet.frame)
                await source.wait_for_playout()
                await stream.aclose()
                for _ in range(60):
                    await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
                await source.wait_for_playout()

            def ai_count():
                return len([t for t in c.call["transcript"] if t["speaker"] == "ai"])

            async def control(role, action, identity):
                await c.control(role, action, action + identity, c.call["revision"], identity)

            await speech("payer", "Thank you for calling Meridian Benefits. Who is calling?")
            await until(lambda: ai_count() >= 1, "AI introduction heard and captioned")
            await speech(
                "payer", "I cannot proceed without the fax confirmation. Please bring in your administrator."
            )
            await until(lambda: c.call["control"] == "handoff_pending", "AI requested administrative help")
            await control("administrator", "takeover", "admin")
            await asyncio.sleep(0.4)
            before = ai_count()
            await speech(
                "admin",
                "I am the administrator. We faxed the requested form today, with tracking number DEMO 731.",
            )
            await until(
                lambda: any(t["speaker"] == "administrator" for t in c.call["transcript"]),
                "administrator transcribed while AI is silent",
            )
            assert ai_count() == before
            await control("administrator", "handback", "admin")
            await until(lambda: ai_count() > before, "AI resumed after administrator")
            print("Resumed response:", c.call["transcript"][-1]["text"], flush=True)
            assert any(
                "731" in t["text"] or "fax" in t["text"].lower()
                for t in c.call["transcript"]
                if t["speaker"] == "ai"
            ), "AI did not use administrator context"
            await control("doctor", "takeover", "doc")
            await asyncio.sleep(0.4)
            before = ai_count()
            await speech(
                "doc",
                "I am Doctor Chen. For this fictional case, the LDL result is one hundred ninety. Please arrange a clinical review tomorrow.",
            )
            await until(
                lambda: any(t["speaker"] == "doctor" for t in c.call["transcript"]),
                "doctor transcribed while AI is silent",
            )
            assert ai_count() == before
            await control("doctor", "handback", "doc")
            await until(lambda: ai_count() > before, "AI resumed after doctor")
            last_ai = [t for t in c.call["transcript"] if t["speaker"] == "ai"][-1]["text"]
            assert any(word in last_ai.lower() for word in ["review", "190", "ninety", "tomorrow"]), (
                "AI did not use doctor context"
            )
            assert c.call["room"] == room_id
            for turn in c.call["transcript"]:
                print(f"{turn['speaker']}: {turn['text']}", flush=True)
            print("PASS: Full repeated handoff in the same LiveKit room, with retained context", flush=True)
        finally:
            import json

            from atp.config import ROOT

            (ROOT / ".local/handoff-smoke.json").write_text(json.dumps(c.call, indent=2))
            await c.end("Automated handoff rehearsal finished.")
            for room in rooms.values():
                await room.disconnect()
            for source in sources.values():
                await source.aclose()
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
