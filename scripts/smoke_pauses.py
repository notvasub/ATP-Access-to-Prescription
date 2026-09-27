"""Verify a mid-sentence breath over real audio services; never dial or post Slack."""

import asyncio
import tempfile
from pathlib import Path

from livekit import rtc

from atp.config import Settings
from atp.engine import Coordinator
from atp.providers import lk_token
from atp.store import Store
from atp.voice import VoiceTransport


async def until(predicate):
    async with asyncio.timeout(40):
        while not predicate():
            await asyncio.sleep(0.05)


async def main():
    settings = Settings()
    payer = rtc.Room()
    source = rtc.AudioSource(24000, 1, queue_size_ms=150)
    human_turn = False
    overlaps = []

    class ObservedTransport(VoiceTransport):
        async def speak(self, text, epoch):
            if human_turn:
                overlaps.append(text)
            await super().speak(text, epoch)

    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "pauses.sqlite3")
        c = Coordinator(settings, store, ObservedTransport)

        async def prepare(text):
            stream = c.transport.tts.stream()
            frames = []
            try:
                stream.push_text(text)
                stream.end_input()
                async for packet in stream:
                    f = packet.frame
                    frames.append(
                        rtc.AudioFrame(bytes(f.data), f.sample_rate, f.num_channels, f.samples_per_channel)
                    )
                return frames
            finally:
                await stream.aclose()

        async def play(frames):
            for frame in frames:
                await source.capture_frame(frame)
            await source.wait_for_playout()

        async def silence(seconds):
            await play([rtc.AudioFrame(bytes(960), 24000, 1, 480) for _ in range(round(seconds / 0.02))])

        try:
            await c.start("browser", "pitch")
            await until(lambda: c.call["status"] != "starting")
            assert c.call["status"] == "active", c.call["error"]
            # Prepare both pieces before playback so network latency cannot lengthen the breath.
            first = await prepare("I have reviewed the request,")
            second = await prepare("and I need to know which treatments were tried.")
            await payer.connect(settings.livekit_url, lk_token(settings, c.call["room"], "payer", True))
            await payer.local_participant.publish_track(
                rtc.LocalAudioTrack.create_audio_track("Payer", source)
            )
            await until(lambda: any(t["speaker"] == "ai" for t in c.call["transcript"]))
            before = len([t for t in c.call["transcript"] if t["speaker"] == "ai"])
            human_turn = True
            await play(first)
            await silence(0.9)
            await play(second)
            human_turn = False
            await silence(2.5)
            await until(lambda: len([t for t in c.call["transcript"] if t["speaker"] == "ai"]) > before)
            assert not overlaps, f"AI started speaking during the human turn: {overlaps}"
            payer_text = " ".join(t["text"] for t in c.call["transcript"] if t["speaker"] == "payer")
            assert "reviewed" in payer_text.lower() and "treatments" in payer_text.lower(), payer_text
            assert c.call["control"] == "ai"
            print("PASS: 0.9-second mid-sentence breath did not trigger AI speech", flush=True)
            print("PASS: Both parts were transcribed before ATP answered", flush=True)
            for turn in c.call["transcript"]:
                print(f"{turn['speaker']}: {turn['text']}", flush=True)
        finally:
            await c.end("Pause rehearsal finished.")
            await payer.disconnect()
            await source.aclose()
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
