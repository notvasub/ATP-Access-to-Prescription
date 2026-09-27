"""Real voice/model pitch rehearsal with RTC actors; no PSTN calls or Slack posts."""

import asyncio
import re
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from livekit import api, rtc

from atp.config import Settings
from atp.docupdates import DocUpdates
from atp.engine import Coordinator
from atp.store import Store
from atp.voice import VoiceTransport


async def until(predicate, timeout=35):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


async def main():
    settings = Settings()
    payer, doctor = rtc.Room(), rtc.Room()
    payer_source = rtc.AudioSource(24000, 1, queue_size_ms=150)
    doctor_source = rtc.AudioSource(24000, 1, queue_size_ms=150)
    acceptance = None
    posted = []
    started = time.monotonic()

    def checkpoint(label):
        print(f"{time.monotonic() - started:.1f}s: {label}", flush=True)

    class RehearsalTransport(VoiceTransport):
        async def dial(self):
            with patch.object(self.lk.sip, "create_sip_participant", self.synthetic_answer):
                await super().dial()

        async def dial_doctor(self, number, identity):
            # Replace the telephone dial API, but exercise real screening and room movement.
            with patch.object(self.lk.sip, "create_sip_participant", self.synthetic_answer):
                await super().dial_doctor(number, identity)

        async def synthetic_answer(self, request, **kwargs):
            nonlocal acceptance
            actor, source = (
                (payer, payer_source) if request.participant_identity == "payer" else (doctor, doctor_source)
            )
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
            await actor.connect(settings.livekit_url, token)
            await actor.local_participant.publish_track(
                rtc.LocalAudioTrack.create_audio_track("Rehearsal actor", source)
            )

            async def accept():
                await asyncio.sleep(3)
                await actor.local_participant.publish_dtmf(code=1, digit="1")

            acceptance = asyncio.create_task(accept())

    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "pitch.sqlite3")
        c = Coordinator(settings, store, RehearsalTransport)

        async def capture_slack(config, payload):
            posted.append(payload)

        completion = DocUpdates(
            settings, store, lambda: "https://rehearsal.invalid", lambda _: None, sender=capture_slack
        )
        c.notify_completion = completion.enqueue

        async def briefing(call, attempt):
            attempt["notification_status"] = "posted"
            checkpoint("Doctor briefing prepared (delivery stubbed)")

        c.notify_doctor = briefing

        async def say(source, text):
            stream = c.transport.tts.stream()
            try:
                stream.push_text(text)
                stream.end_input()
                async for packet in stream:
                    await source.capture_frame(packet.frame)
                await source.wait_for_playout()
                for _ in range(60):
                    await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
                await source.wait_for_playout()
            finally:
                await stream.aclose()

        def ai_turns():
            return [t for t in c.call["transcript"] if t["speaker"] == "ai" and not t.get("interrupted")]

        try:
            await c.start("phone", "pitch")
            await until(lambda: len(ai_turns()) >= 1)
            checkpoint("AI introduced itself")
            before = len(ai_turns())
            await say(payer_source, "I have the case. What treatment history was submitted?")
            await until(lambda: len(ai_turns()) > before or c.call["control"] == "handoff_pending")
            assert c.call["control"] == "ai", "Escalated on a neutral factual question"
            assert "atorvastatin" in ai_turns()[-1]["text"].lower()
            checkpoint("Routine question answered without escalation")
            before = len(ai_turns())
            await say(payer_source, "Those trials alone aren't enough. What do the labs show?")
            await until(lambda: len(ai_turns()) > before or c.call["control"] == "handoff_pending")
            assert c.call["control"] == "ai", "Escalated before answering a documented lab question"
            answer = ai_turns()[-1]["text"]
            assert "260" in answer and "190" in answer, answer
            assert "?" in answer, "ATP did not ask about the remaining requirement"
            checkpoint("ATP explained the lab trend and asked a targeted follow-up")
            await say(
                payer_source,
                "We keep going in circles. I can't approve this without someone taking clinical responsibility.",
            )
            await until(lambda: c.call["control"] == "doctor")
            checkpoint("Frustration triggered escalation; doctor pressed 1 and joined")
            await say(
                doctor_source,
                "Doctor Chen here. I verified adherence. These are Morgan's maximally tolerated therapies, and LDL remains 190. I recommend proceeding with Repatha.",
            )
            await until(lambda: any(t["speaker"] == "doctor" for t in c.call["transcript"]))
            before = len(ai_turns())
            await doctor.local_participant.publish_dtmf(code=11, digit="#")
            await until(lambda: len(ai_turns()) > before)
            assert c.call["control"] == "ai"
            checkpoint("Doctor pressed #; AI requested the final decision")
            await say(
                payer_source,
                "Morgan Ellis's Repatha authorization is approved for twelve months. Reference D E M O, eight four nine two one. The pharmacy can process it. That completes the case. Goodbye.",
            )
            await until(lambda: c.call["status"] == "ended")
            await until(lambda: bool(completion.tasks) or bool(posted))
            await completion.wait()
            assert len(posted) == 1, str((store.get("call:" + c.call["id"]) or {}).get("docupdates"))
            checkpoint("Final approval verified; Slack payload and DocUpdates link ready (delivery stubbed)")
            for turn in c.call["transcript"]:
                print(f"{turn['speaker']}: {turn['text']}", flush=True)
            reference = next(
                b["text"]["text"]
                for b in posted[0]["blocks"]
                if b.get("text", {}).get("text", "").startswith("*Authorization reference*")
            )
            print(reference, flush=True)
            assert "Morgan Ellis" in str(posted[0]) and "84921" in re.sub(r"\D", "", reference)
        finally:
            if acceptance:
                acceptance.cancel()
                await asyncio.gather(acceptance, return_exceptions=True)
            await c.end("Rehearsal finished.")
            await completion.close()
            await payer.disconnect()
            await doctor.disconnect()
            await payer_source.aclose()
            await doctor_source.aclose()
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
