import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from livekit import rtc
from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT, TimedString

from atp.voice import VoiceTransport


async def test_handback_flush_waits_only_for_returning_human():
    t = VoiceTransport(SimpleNamespace(settings=None))
    doctor = Mock()
    payer = Mock()
    t.stt_streams = {"doctor-phone-test": doctor, "payer": payer}
    t.pending_transcripts = {"payer"}
    await t.flush_transcripts("doctor-phone-test")
    doctor.flush.assert_called_once_with()
    payer.flush.assert_not_called()
    assert t.pending_transcripts == {"payer"}


class Stream:
    def push_text(self, text):
        pass

    def end_input(self):
        pass

    async def aclose(self):
        pass

    def __aiter__(self):
        return self.generate()

    async def generate(self):
        frame = rtc.AudioFrame(bytes(48000), 24000, 1, 24000)
        frame.userdata[USERDATA_TIMED_TRANSCRIPT] = [
            TimedString("Hello ", start_time=0, end_time=0.3),
            TimedString("Sam. ", start_time=0.3, end_time=0.8),
            TimedString("Unplayed words", start_time=1.2, end_time=2),
        ]
        yield SimpleNamespace(frame=frame, delta_text="")
        raise asyncio.CancelledError


async def test_interrupted_caption_uses_only_played_alignment():
    turns = []
    events = []

    async def capture(frame):
        pass

    c = SimpleNamespace(
        settings=None,
        epoch=1,
        call={"control": "ai"},
        add_agent_turn=lambda text, interrupted: turns.append((text, interrupted)),
        emit=lambda *args, **kwargs: events.append(kwargs),
    )
    t = VoiceTransport(c)
    t.tts = SimpleNamespace(stream=Stream)
    t.source = SimpleNamespace(capture_frame=capture, queued_duration=0.15)
    with pytest.raises(asyncio.CancelledError):
        await t.speak("Hello Sam. Unplayed words", 1)
    assert turns == [("Hello Sam. ", True)]
    assert any(event.get("text") == "Hello Sam. " for event in events)
