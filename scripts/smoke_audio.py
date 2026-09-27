"""Exercise real ElevenLabs STT/TTS + OpenAI over LiveKit, without dialing a phone."""

import asyncio
import tempfile
from pathlib import Path

from livekit import rtc

from atp.config import Settings
from atp.engine import Coordinator
from atp.providers import lk_token
from atp.store import Store


async def main():
    s = Settings()
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "smoke.sqlite3")
        c = Coordinator(s, store)
        payer = rtc.Room()
        source = rtc.AudioSource(24000, 1, queue_size_ms=150)
        try:
            await c.start("browser")
            for _ in range(100):
                if c.call["status"] != "starting":
                    break
                await asyncio.sleep(0.1)
            if c.call["status"] != "active":
                raise RuntimeError(c.call["error"])
            print("PASS: LiveKit agent connected", flush=True)
            await payer.connect(s.livekit_url, lk_token(s, c.call["room"], "payer", True))
            track = rtc.LocalAudioTrack.create_audio_track("Synthetic payer", source)
            await payer.local_participant.publish_track(track)
            for _ in range(300):
                if any(t["speaker"] == "ai" for t in c.call["transcript"]):
                    break
                await asyncio.sleep(0.1)
            assert any(t["speaker"] == "ai" for t in c.call["transcript"]), (
                "AI did not proactively greet the caller"
            )
            print("PASS: AI greeted the connected caller without a human prompt", flush=True)
            before = len([t for t in c.call["transcript"] if t["speaker"] == "ai"])
            stream = c.transport.tts.stream()
            stream.push_text(
                "Thank you for calling Meridian Benefits. My name is Sam. Who am I speaking with?"
            )
            stream.end_input()
            packets = 0
            async for packet in stream:
                packets += 1
                await source.capture_frame(packet.frame)
            await source.wait_for_playout()
            await stream.aclose()
            print(f"PASS: ElevenLabs Viraj TTS produced {packets} audio packets", flush=True)
            # Silence permits server VAD to commit a final transcript.
            for _ in range(75):
                await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
            await source.wait_for_playout()
            for _ in range(450):
                if len([t for t in c.call["transcript"] if t["speaker"] == "ai"]) > before:
                    break
                if c.call["error"]:
                    raise RuntimeError(c.call["error"])
                await asyncio.sleep(0.1)
            turns = c.call["transcript"]
            assert any(t["speaker"] == "payer" for t in turns), "No Scribe transcript received"
            assert any(t["speaker"] == "ai" for t in turns), "No OpenAI/ElevenLabs response received"
            print("PASS: Scribe transcribed the remote LiveKit audio", flush=True)
            print("PASS: OpenAI answered and ElevenLabs played the complete response", flush=True)
            for t in turns:
                print(f"{t['speaker']}: {t['text']}", flush=True)
        finally:
            await c.end("Automated audio check finished.")
            await payer.disconnect()
            await source.aclose()
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
