"""Keep ringing and voicemail outside the conversation until a human confirms."""

import asyncio
import re

from google.protobuf.duration_pb2 import Duration
from livekit import api, rtc
from livekit.agents import stt

from .engine import ControlError
from .providers import discover_trunk, lk_token

RING_SECONDS = 30
CONFIRM_SECONDS = 10
VOICEMAIL = re.compile(
    r"leave (?:me |us |your |a )*(?:message|name)|after the (?:tone|beep)|"
    r"(?:voice ?mail|mailbox)|not available|can't (?:take|answer)|"
    r"cannot (?:take|answer)|unable to (?:take|answer)|"
    r"(?:please |you can )?(?:record your message|call (?:back )?later)",
    re.I,
)


class AnswerScreen:
    def __init__(self, transport, identity, role="doctor"):
        if role not in {"doctor", "insurer"}:
            raise ValueError("Unknown answer-screening role")
        self.t = transport
        self.identity = identity
        self.role = role
        self.label = role.capitalize()
        self.destination = transport.c.call["room"]
        self.name = self.destination + "-screen-" + identity
        self.room = rtc.Room()
        self.source = rtc.AudioSource(24000, 1, queue_size_ms=150)
        self.result = asyncio.get_running_loop().create_future()
        self.tasks = set()
        self.moving = False
        self.created = False

    def finish(self, result):
        if not self.result.done():
            self.result.set_result(result)

    def wire_events(self):
        @self.room.on("sip_dtmf_received")
        def key(event):
            if event.participant and event.participant.identity == self.identity and event.digit == "1":
                self.finish("confirmed")

        @self.room.on("track_subscribed")
        def subscribed(track, publication, participant):
            if participant.identity == self.identity and track.kind == rtc.TrackKind.KIND_AUDIO:
                task = asyncio.create_task(self.listen(track))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

        @self.room.on("participant_disconnected")
        def disconnected(participant):
            if participant.identity == self.identity and not self.moving:
                self.finish("disconnected")

    async def listen(self, track):
        stream = self.t.stt.stream()
        audio = rtc.AudioStream(track, sample_rate=16000, num_channels=1)

        async def feed():
            async for packet in audio:
                stream.push_frame(packet.frame)

        feeder = asyncio.create_task(feed())
        try:
            async for event in stream:
                if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT and event.alternatives:
                    if VOICEMAIL.search(event.alternatives[0].text):
                        self.finish("voicemail")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Press 1 remains mandatory even if speech recognition is unavailable.
            pass
        finally:
            feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
            await audio.aclose()
            await stream.aclose()

    async def say(self, text):
        stream = self.t.tts.stream()
        try:
            stream.push_text(text)
            stream.end_input()
            async for packet in stream:
                await self.source.capture_frame(packet.frame)
            await self.source.wait_for_playout()
        finally:
            await stream.aclose()

    async def confirm(self):
        text = (
            "Hello, this is ATP. Press 1 to join the insurer call. Then press pound to return to the AI."
            if self.role == "doctor"
            else "Hello, this is ATP. Press 1 to connect with our AI assistant."
        )
        prompt = asyncio.create_task(self.say(text))
        try:
            async with asyncio.timeout(CONFIRM_SECONDS):
                return await asyncio.shield(self.result)
        except TimeoutError:
            return "unconfirmed"
        finally:
            prompt.cancel()
            await asyncio.gather(prompt, return_exceptions=True)
            self.source.clear_queue()

    async def run(self, number):
        self.wire_events()
        try:
            trunk_id = await discover_trunk(self.t.s)
            # Mark before awaiting so even an ambiguous create failure is cleaned up.
            self.created = True
            self.t.screen_rooms.add(self.name)
            await self.t.lk.room.create_room(api.CreateRoomRequest(name=self.name, empty_timeout=30))
            await self.room.connect(self.t.s.livekit_url, lk_token(self.t.s, self.name, "screen", True))
            await self.room.local_participant.publish_track(
                rtc.LocalAudioTrack.create_audio_track("Private answer check", self.source),
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
            try:
                async with asyncio.timeout(RING_SECONDS + 2):
                    await self.t.lk.sip.create_sip_participant(
                        api.CreateSIPParticipantRequest(
                            sip_trunk_id=trunk_id,
                            sip_call_to=number,
                            sip_number=self.t.s.plivo_phone_number,
                            room_name=self.name,
                            participant_identity=self.identity,
                            participant_name=self.label,
                            wait_until_answered=True,
                            play_dialtone=False,
                            ringing_timeout=Duration(seconds=RING_SECONDS),
                            max_call_duration=Duration(
                                seconds=min(max(self.t.s.demo_max_call_seconds, 30), 600)
                            ),
                        ),
                        timeout=RING_SECONDS + 2,
                    )
            except TimeoutError as exc:
                raise ControlError(f"{self.label} did not answer within 30 seconds.") from exc
            attempt = self.t.c.call.get("doctor_call")
            if attempt and attempt["identity"] == self.identity:
                attempt["status"] = "screening"
                self.t.c.emit()
            if self.role == "insurer":
                self.t.c.call["agent_status"] = "screening"
                self.t.c.emit()
            result = await self.confirm()
            if result != "confirmed":
                if result != "disconnected":
                    try:
                        async with asyncio.timeout(5):
                            await self.say("This is ATP. We couldn't connect with you. Goodbye.")
                    except Exception:
                        pass  # A speech outage must never prevent hanging up voicemail.
                reasons = {
                    "voicemail": f"{self.label}'s voicemail answered. The {self.role} call was ended.",
                    "unconfirmed": f"{self.label} did not press 1 to join. The {self.role} call was ended.",
                    "disconnected": f"{self.label} disconnected before joining.",
                }
                raise ControlError(reasons[result])
            pending = (
                self.t.c.call["control"] == "handoff_pending"
                if self.role == "doctor"
                else self.t.c.call["status"] == "dialing"
            )
            if not pending or self.t.closed:
                raise ControlError(
                    f"{self.label} call cancelled because the connection is no longer pending."
                )
            self.moving = True
            await self.t.lk.room.move_participant(
                api.MoveParticipantRequest(
                    room=self.name, identity=self.identity, destination_room=self.destination
                )
            )
        finally:
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            try:
                if self.created:
                    await self.t.lk.room.delete_room(api.DeleteRoomRequest(room=self.name))
                    self.t.screen_rooms.discard(self.name)
            finally:
                await self.room.disconnect()
                await self.source.aclose()
